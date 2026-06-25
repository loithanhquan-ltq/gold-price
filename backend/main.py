import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend import config, cache, repository
from backend.logging_config import setup_logging
from backend.database import init_db, get_db
from backend.security import require_token
from backend.scrapers.sjc import fetch_sjc_price
from backend.scrapers.international import fetch_international_price
from backend.email_service import send_daily_email
from backend.scheduler import start_scheduler, scheduler, run_daily_job

logger = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    missing = config.validate()
    if missing:
        logger.warning("Missing required config: %s — email/auth features will fail", missing)
    init_db()
    start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(title="Gold Price Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    # Inject API token into the page so the dashboard can call protected endpoints
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__API_TOKEN__", config.API_TOKEN)
    return HTMLResponse(html)


@app.get("/api/health")
def health():
    return {"status": "ok", "scheduler": scheduler.running}


@app.get("/api/prices/current")
def current_prices():
    """Read-only: returns cached live prices; never writes to the DB."""
    cached = cache.get("live")
    if cached:
        return cached
    sjc_data = intl_data = None
    try:
        sjc_data = fetch_sjc_price().as_dict()
    except Exception as e:
        logger.warning("live SJC fetch failed: %s", e)
    try:
        intl_data = fetch_international_price().as_dict()
    except Exception as e:
        logger.warning("live intl fetch failed: %s", e)
    payload = {
        "sjc": sjc_data,
        "international": intl_data,
        "fetched_at": datetime.now(config.TZ).isoformat(),
    }
    cache.set("live", payload)
    return payload


@app.get("/api/prices/history")
def price_history(days: int = 7, db: Session = Depends(get_db)):
    return [
        {
            "price_date": r.price_date.isoformat(),
            "source": r.source,
            "buy_price": r.buy_price,
            "sell_price": r.sell_price,
            "high": r.high,
            "low": r.low,
            "is_stale": bool(r.is_stale),
        }
        for r in repository.history(db, days)
    ]


@app.get("/api/status")
def status():
    job = scheduler.get_job("daily_gold")
    return {
        "scheduler_running": scheduler.running,
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }


@app.post("/api/refresh", dependencies=[Depends(require_token)])
def refresh(db: Session = Depends(get_db)):
    """Fetch live prices and write canonical rows for today. Requires API token."""
    today = datetime.now(config.TZ).date()
    out = {}
    for name, fn in (("SJC", fetch_sjc_price), ("INTERNATIONAL", fetch_international_price)):
        try:
            r = fn()
            repository.upsert_daily(db, today, r)
            out[name] = r.as_dict()
        except Exception as e:
            out[name] = {"error": str(e)}
    cache.invalidate("live")
    return out


@app.post("/api/email/test", dependencies=[Depends(require_token)])
def email_test():
    """Trigger the daily job immediately. Requires API token."""
    run_daily_job()
    return {"status": "sent"}
