import logging
import requests
from backend.scrapers.base import PriceResult, network_retry

logger = logging.getLogger(__name__)

# Both endpoints are public, key-free daily reference rates. open.er-api.com updates
# around 00:00 UTC, before the 03:00 UTC Actions run. jsDelivr hosts a daily feed as
# a fallback; Yahoo's EURVND=X quote was dropped because it returns 429 like GC=F.
# ER-API's free tier requires attribution — the email and Pages footers credit it.
ER_API_URL = "https://open.er-api.com/v6/latest/EUR"
JSDELIVR_URL = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/eur.json"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GoldTracker/1.0",
    "Accept": "application/json",
}

SANE_MIN_VND_PER_EUR = 15_000
SANE_MAX_VND_PER_EUR = 45_000


def _check_range(rate: float, source: str) -> float:
    if not (SANE_MIN_VND_PER_EUR < rate < SANE_MAX_VND_PER_EUR):
        raise ValueError(f"{source} EUR/VND rate out of expected range: {rate}")
    return rate


def _parse_er_api(data: dict) -> float:
    """Return VND per EUR from open.er-api.com's latest-rates payload."""
    if data.get("result") != "success":
        raise ValueError(f"ER-API returned non-success result: {data.get('result')!r}")
    rate = (data.get("rates") or {}).get("VND")
    if rate is None:
        raise ValueError("VND missing from ER-API response — API shape may have changed")
    return _check_range(float(rate), "ER-API")


def _parse_jsdelivr(data: dict) -> float:
    """Return VND per EUR from the jsDelivr currency-api payload."""
    rate = (data.get("eur") or {}).get("vnd")
    if rate is None:
        raise ValueError("VND missing from jsDelivr response — API shape may have changed")
    return _check_range(float(rate), "jsDelivr")


@network_retry
def _fetch_er_api() -> PriceResult:
    resp = requests.get(ER_API_URL, timeout=15, headers=HEADERS)
    resp.raise_for_status()
    rate = _parse_er_api(resp.json())
    return PriceResult("EURVND", "VND", "EUR", buy_price=rate, sell_price=rate)


@network_retry
def _fetch_jsdelivr() -> PriceResult:
    resp = requests.get(JSDELIVR_URL, timeout=15, headers=HEADERS)
    resp.raise_for_status()
    rate = _parse_jsdelivr(resp.json())
    return PriceResult("EURVND", "VND", "EUR", buy_price=rate, sell_price=rate)


def fetch_eur_vnd_rate() -> PriceResult:
    """Fetch the mid-market EUR→VND reference rate. ER-API primary, jsDelivr fallback."""
    try:
        return _fetch_er_api()
    except Exception as e:
        logger.warning("ER-API failed (%s); trying jsDelivr currency-api", e)
        return _fetch_jsdelivr()
