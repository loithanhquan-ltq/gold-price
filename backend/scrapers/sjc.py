import requests
from backend.scrapers.base import PriceResult, network_retry

# PNJ's storefront API is served from Cloudflare's global anycast CDN, so it stays
# reachable from GitHub Actions runners outside Vietnam. It publishes the official
# SJC retail price (the same government-set price every retailer shows).
# Prices are strings in "nghìn/lượng" (thousands VND per tael): "146.600" → 146,600,000 VND/tael.
PNJ_URL = "https://edge-cf-api.pnj.io/ecom-frontend/v3/get-gold-price"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GoldTracker/1.0",
    "Accept": "application/json",
}
# SJC.com.vn itself is behind Cloudflare with an interactive JS challenge and cannot be
# scraped with plain HTTP requests. giavang.doji.vn was the original source, but on
# 2026-07-16 it went JS-only — it now serves no price table to plain HTTP clients, so it
# was dropped as a fallback rather than left in place failing silently.

SANE_MIN_VND_PER_TAEL = 10_000_000
SANE_MAX_VND_PER_TAEL = 500_000_000


def _vnd_per_tael(raw: str, multiplier: int) -> float:
    """Convert a Vietnamese-formatted price string to VND per tael."""
    return float(str(raw).replace(".", "").replace(",", "").strip()) * multiplier


def _check_range(buy: float, source: str) -> None:
    if not (SANE_MIN_VND_PER_TAEL < buy < SANE_MAX_VND_PER_TAEL):
        raise ValueError(f"{source} buy price out of expected range: {buy}")


def _parse_pnj_json(data: dict) -> tuple[float, float]:
    """Return (buy_price, sell_price) in VND per tael from PNJ's gold price API."""
    for location in data.get("locations", []):
        for item in location.get("gold_type", []):
            if item.get("name", "").strip().upper() != "SJC":
                continue
            buy = _vnd_per_tael(item.get("gia_mua", "0"), 1_000)
            sell = _vnd_per_tael(item.get("gia_ban", "0"), 1_000)
            _check_range(buy, "SJC")
            return buy, sell
    raise ValueError("SJC gold_type not found in PNJ response — API shape may have changed")


@network_retry
def _fetch_pnj() -> PriceResult:
    resp = requests.get(PNJ_URL, timeout=15, headers=HEADERS)
    resp.raise_for_status()
    buy, sell = _parse_pnj_json(resp.json())
    return PriceResult("SJC", "VND", "tael", buy_price=buy, sell_price=sell)


def fetch_sjc_price() -> PriceResult:
    """Fetch SJC retail gold price (VND per tael) from PNJ."""
    return _fetch_pnj()
