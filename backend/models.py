from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, UniqueConstraint
from backend.database import Base


class GoldPrice(Base):
    __tablename__ = "gold_prices"
    __table_args__ = (UniqueConstraint("price_date", "source", name="uq_date_source"),)

    id = Column(Integer, primary_key=True)
    price_date = Column(Date, index=True, nullable=False)
    source = Column(String, index=True, nullable=False)   # "SJC" | "INTERNATIONAL"
    buy_price = Column(Float, nullable=True)
    sell_price = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    currency = Column(String, nullable=False)              # "VND" | "USD"
    unit = Column(String, nullable=False)                  # "tael" | "troy_oz"
    is_stale = Column(Integer, default=0)                  # 1 if carried forward from prior day
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
