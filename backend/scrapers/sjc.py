import logging
import requests
from bs4 import BeautifulSoup
from backend.scrapers.base import PriceResult, network_retry

logger = logging.getLogger(__name__)

# DOJI's gold price sub-site is publicly accessible (no Cloudflare / no auth).
# It displays the official SJC retail price (same government-set price shown by all retailers).
# Prices are in "nghìn/chỉ" (thousands VND per chỉ). 1 tael = 10 chỉ, so multiply by 10,000
# to convert to VND per tael.
DOJI_URL = "https://giavang.doji.vn"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) GoldTracker/1.0"}
# SJC.com.vn itself is behind Cloudflare with an interactive JS challenge and cannot be
# scraped with plain HTTP requests.


def _parse_doji_html(html: str) -> tuple[float, float]:
    """Return (buy_price, sell_price) in VND per tael from DOJI's gold page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True) for c in header_cells]
        # Target the table with "Loại" header (clean numeric data, no unit suffix)
        if "Loại" not in header_texts:
            continue
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            label = cells[0].get_text(strip=True)
            if "SJC" not in label or "Bán Lẻ" not in label:
                continue
            buy_raw = cells[1].get_text(strip=True).replace(",", "").replace(".", "")
            sell_raw = cells[2].get_text(strip=True).replace(",", "").replace(".", "")
            # Unit: nghìn/chỉ — multiply × 10,000 to get VND per tael (lượng)
            buy = float(buy_raw) * 10_000
            sell = float(sell_raw) * 10_000
            if not (10_000_000 < buy < 500_000_000):  # sanity: 10M–500M VND/tael
                raise ValueError(f"SJC buy price out of expected range: {buy}")
            return buy, sell
    raise ValueError("SJC row not found in DOJI table — page structure may have changed")


@network_retry
def _fetch_doji() -> PriceResult:
    resp = requests.get(DOJI_URL, timeout=10, headers=HEADERS)
    resp.raise_for_status()
    buy, sell = _parse_doji_html(resp.text)
    return PriceResult("SJC", "VND", "tael", buy_price=buy, sell_price=sell)


def fetch_sjc_price() -> PriceResult:
    """Fetch SJC retail gold price (VND per tael) from DOJI's public gold price page."""
    return _fetch_doji()
