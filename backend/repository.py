from datetime import date, timedelta, datetime
from sqlalchemy.orm import Session
from sqlalchemy import select
from backend.models import GoldPrice
from backend.scrapers.base import PriceResult
from backend.config import TZ


def upsert_daily(db: Session, price_date: date, r: PriceResult, is_stale: bool = False) -> GoldPrice:
    obj = db.execute(
        select(GoldPrice).where(GoldPrice.price_date == price_date, GoldPrice.source == r.source)
    ).scalar_one_or_none()
    if obj is None:
        obj = GoldPrice(price_date=price_date, source=r.source)
        db.add(obj)
    obj.buy_price = r.buy_price
    obj.sell_price = r.sell_price
    obj.high = r.high
    obj.low = r.low
    obj.currency = r.currency
    obj.unit = r.unit
    obj.is_stale = 1 if is_stale else 0
    db.commit()
    db.refresh(obj)
    return obj


def latest_before(db: Session, source: str, before: date) -> GoldPrice | None:
    return db.execute(
        select(GoldPrice)
        .where(GoldPrice.source == source, GoldPrice.price_date < before)
        .order_by(GoldPrice.price_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def history(db: Session, days: int = 7) -> list[GoldPrice]:
    since = datetime.now(TZ).date() - timedelta(days=days)
    return list(
        db.execute(
            select(GoldPrice)
            .where(GoldPrice.price_date >= since)
            .order_by(GoldPrice.price_date)
        ).scalars()
    )
