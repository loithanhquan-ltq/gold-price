import logging
import requests
from backend.scrapers.base import PriceResult, network_retry

logger = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    "Accept": "application/json",
}


@network_retry
def _fetch_yahoo() -> PriceResult:
    resp = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF",
        params={"interval": "1d", "range": "2d"},
        headers=YAHOO_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    meta = resp.json()["chart"]["result"][0]["meta"]
    price = float(meta["regularMarketPrice"])
    high  = float(meta.get("regularMarketDayHigh", price))
    low   = float(meta.get("regularMarketDayLow", price))
    if not (500 < price < 20_000):
        raise ValueError(f"XAU/USD price out of expected range: {price}")
    return PriceResult("INTERNATIONAL", "USD", "troy_oz",
                       buy_price=price, sell_price=price, high=high, low=low)


@network_retry
def _fetch_coingecko() -> PriceResult:
    """Fallback: Tether Gold (XAUT) tracks spot XAU/USD closely."""
    resp = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "tether-gold", "vs_currencies": "usd"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    resp.raise_for_status()
    price = float(resp.json()["tether-gold"]["usd"])
    if not (500 < price < 20_000):
        raise ValueError(f"CoinGecko XAUT price out of expected range: {price}")
    # CoinGecko doesn't provide daily high/low for this endpoint
    return PriceResult("INTERNATIONAL", "USD", "troy_oz",
                       buy_price=price, sell_price=price, high=None, low=None)


def fetch_international_price() -> PriceResult:
    """Fetch XAU/USD spot price. Yahoo Finance primary, CoinGecko fallback."""
    try:
        return _fetch_yahoo()
    except Exception as e:
        logger.warning("Yahoo Finance failed (%s); trying CoinGecko", e)
        return _fetch_coingecko()
