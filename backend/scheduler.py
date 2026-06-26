import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from backend.config import SEND_HOUR, TIMEZONE, TZ
from backend.database import SessionLocal
from backend.scrapers.sjc import fetch_sjc_price
from backend.scrapers.international import fetch_international_price
from backend.scrapers.base import PriceResult
from backend import repository
from backend.email_service import send_daily_email

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=TIMEZONE)


def _fetch_or_carry(db, today, fetch_fn, source: str) -> tuple[PriceResult | None, bool]:
    """Try to fetch live price; on total failure carry forward last-known DB row (marked stale)."""
    try:
        r = fetch_fn()
        repository.upsert_daily(db, today, r, is_stale=False)
        return r, False
    except Exception as e:
        logger.error("%s fetch failed: %s", source, e)
        last = repository.latest_before(db, source, today)
        if last:
            r = PriceResult(source, last.currency, last.unit,
                            last.buy_price, last.sell_price, last.high, last.low)
            repository.upsert_daily(db, today, r, is_stale=True)
            logger.warning("Using stale %s price from %s", source, last.price_date)
            return r, True
        return None, True


def run_daily_job():
    db = SessionLocal()
    try:
        today = datetime.now(TZ).date()
        logger.info("Running daily gold job for %s", today)
        sjc, sjc_stale = _fetch_or_carry(db, today, fetch_sjc_price, "SJC")
        intl, intl_stale = _fetch_or_carry(db, today, fetch_international_price, "INTERNATIONAL")
        send_daily_email(db, today, sjc, intl, sjc_stale, intl_stale)
        logger.info("Daily job done (sjc_stale=%s intl_stale=%s)", sjc_stale, intl_stale)
    except Exception:
        logger.exception("Daily job failed")
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(
        run_daily_job,
        "cron",
        hour=SEND_HOUR,
        minute=0,
        id="daily_gold",
        coalesce=True,
        misfire_grace_time=3600,
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — daily email at %02d:00 %s", SEND_HOUR, TZ)
