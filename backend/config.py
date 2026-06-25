import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")

API_TOKEN = os.getenv("API_TOKEN", "")
SEND_HOUR = int(os.getenv("SEND_HOUR", "7"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Ho_Chi_Minh")
TZ = ZoneInfo(TIMEZONE)
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "600"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/gold_prices.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

REQUIRED = ["GMAIL_USER", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL", "API_TOKEN"]


def validate() -> list[str]:
    return [k for k in REQUIRED if not globals().get(k)]
