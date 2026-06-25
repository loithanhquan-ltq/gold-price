"""
GitHub Actions entrypoint — runs daily at 10:00 ICT (03:00 UTC).

1. Fetch SJC + international gold prices
2. Update docs/data/prices.json (history kept for 90 days)
3. Send HTML email via Gmail SMTP
"""
import json
import logging
import os
import smtplib
import ssl
import sys
import io
import base64
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow imports from repo root (backend package)
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.scrapers.sjc import fetch_sjc_price
from backend.scrapers.international import fetch_international_price

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DATA_FILE = Path(__file__).parent.parent / "docs" / "data" / "prices.json"
MAX_HISTORY = 90

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def load_data() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"updated_at": None, "sjc": None, "international": None, "history": []}


def save_data(data: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_history(history: list, entry: dict) -> list:
    """Insert or replace today's entry, keep last MAX_HISTORY days sorted."""
    history = [h for h in history if h["date"] != entry["date"]]
    history.append(entry)
    history.sort(key=lambda x: x["date"])
    return history[-MAX_HISTORY:]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_vnd(v) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.0f} ₫"


def fmt_usd(v) -> str:
    if v is None:
        return "N/A"
    return f"${v:,.2f}"


def change_info(current, previous, fmt_fn) -> tuple[str, str]:
    if current is None or previous is None or previous == 0:
        return "N/A", "neutral"
    diff = current - previous
    pct = (diff / previous) * 100
    sign = "+" if diff >= 0 else ""
    css = "up" if diff > 0 else ("down" if diff < 0 else "neutral")
    return f"{sign}{fmt_fn(diff)} ({sign}{pct:.2f}%)", css


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def build_chart_b64(history: list) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        recent = history[-7:]
        if not recent:
            return None

        dates = [date.fromisoformat(h["date"]) for h in recent]
        sjc_prices  = [h.get("sjc_sell") for h in recent]
        intl_prices = [h.get("intl_price") for h in recent]

        fig, ax1 = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#1a1a1a")
        ax1.set_facecolor("#1a1a1a")
        ax2 = ax1.twinx()

        if any(p for p in sjc_prices if p):
            vals = [p / 1_000_000 if p else None for p in sjc_prices]
            ax1.plot(dates, vals, color="#e6a817", lw=2, marker="o", ms=4,
                     label="SJC (triệu VND/lượng)")
            ax1.set_ylabel("SJC (triệu VND/lượng)", color="#e6a817", fontsize=10)
            ax1.tick_params(axis="y", labelcolor="#e6a817")

        if any(p for p in intl_prices if p):
            ax2.plot(dates, intl_prices, color="#2196F3", lw=2, marker="o", ms=4,
                     label="XAU/USD")
            ax2.set_ylabel("XAU/USD ($/troy oz)", color="#2196F3", fontsize=10)
            ax2.tick_params(axis="y", labelcolor="#2196F3")

        for ax in (ax1, ax2):
            ax.tick_params(axis="x", colors="#999")
            ax.spines[:].set_color("#444")

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        ax1.grid(axis="y", color="#2a2a2a", linestyle="--", lw=0.8)
        fig.autofmt_xdate()

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        if lines1 or lines2:
            ax1.legend(lines1 + lines2, labels1 + labels2,
                       facecolor="#2a2a2a", labelcolor="#ccc", fontsize=9, loc="upper left")

        fig.suptitle("Giá Vàng — 7 Ngày Gần Nhất", fontsize=12, fontweight="bold", color="#eee")
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as e:
        logger.warning("Chart generation failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_HTML = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8">
<style>
body{font-family:Arial,sans-serif;background:#f0f0f0;margin:0;padding:16px}
.c{max-width:620px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.12)}
.h{background:linear-gradient(135deg,#e6a817,#c8860a);color:#fff;padding:28px 24px;text-align:center}
.h h1{margin:0 0 4px;font-size:22px}.h p{margin:0;font-size:14px;opacity:.88}
.s{padding:20px 24px;border-bottom:1px solid #eee}
.t{font-size:13px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.8px;margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;padding:7px 10px;background:#f7f7f7;color:#999;font-size:11px;text-transform:uppercase}
td{padding:10px;border-top:1px solid #f0f0f0;color:#333}
.up{color:#27ae60;font-weight:700}.down{color:#e74c3c;font-weight:700}.neu{color:#999}
.stale{color:#e67e22;font-size:12px;font-style:italic}
.cs{padding:20px 24px}.cs img{width:100%;border-radius:8px;display:block}
.f{padding:16px 24px;text-align:center;font-size:11px;color:#bbb;background:#fafafa}
</style></head><body><div class="c">
<div class="h"><h1>Bảng Giá Vàng Hôm Nay</h1><p>{date_str}</p></div>

<div class="s"><div class="t">🇻🇳 Vàng SJC — VND / Lượng</div>
{sjc_block}
</div>

<div class="s"><div class="t">🌐 Vàng Thế Giới — USD / Troy oz</div>
{intl_block}
</div>

{chart_block}

<div class="f">Gửi lúc {send_time} • Nguồn: giavang.doji.vn &amp; Yahoo Finance</div>
</div></body></html>"""

SJC_BLOCK = """<table>
<tr><th>Loại</th><th>Giá mua</th><th>Giá bán</th><th>Thay đổi (bán)</th></tr>
<tr><td>SJC 1 Lượng{stale}</td><td>{buy}</td><td>{sell}</td><td class="{css}">{change}</td></tr>
</table>"""

INTL_BLOCK = """<table>
<tr><th>Giá</th><th>Cao nhất</th><th>Thấp nhất</th><th>Thay đổi</th></tr>
<tr><td>{price}{stale}</td><td>{high}</td><td>{low}</td><td class="{css}">{change}</td></tr>
</table>"""

EMAIL_TXT = """\
BẢNG GIÁ VÀNG HÔM NAY — {date_str}
=========================================

VÀNG SJC (VND / Lượng)
  Mua     : {sjc_buy}
  Bán     : {sjc_sell}
  Thay đổi: {sjc_change}

VÀNG THẾ GIỚI (USD / Troy oz)
  Giá     : {intl_price}
  Cao nhất: {intl_high}
  Thấp nhất: {intl_low}
  Thay đổi: {intl_change}

--
Gửi lúc {send_time} | Nguồn: giavang.doji.vn & Yahoo Finance
"""


def send_email(sjc, intl, prev_sjc_sell, prev_intl_price, history, now_local):
    date_str  = now_local.strftime("%d/%m/%Y")
    send_time = now_local.strftime("%H:%M")

    sjc_change, sjc_css = change_info(
        sjc.sell_price if sjc else None, prev_sjc_sell, fmt_vnd)
    intl_change, intl_css = change_info(
        intl.buy_price if intl else None, prev_intl_price, fmt_usd)

    if sjc:
        sjc_block = SJC_BLOCK.format(
            stale="", buy=fmt_vnd(sjc.buy_price), sell=fmt_vnd(sjc.sell_price),
            css=sjc_css, change=sjc_change)
    else:
        sjc_block = "<p style='color:#e74c3c'>⚠ Không lấy được giá SJC hôm nay.</p>"

    if intl:
        intl_block = INTL_BLOCK.format(
            stale="", price=fmt_usd(intl.buy_price), high=fmt_usd(intl.high),
            low=fmt_usd(intl.low), css=intl_css, change=intl_change)
    else:
        intl_block = "<p style='color:#e74c3c'>⚠ Không lấy được giá vàng thế giới hôm nay.</p>"

    chart_b64 = build_chart_b64(history)
    chart_block = (f'<div class="cs"><img src="data:image/png;base64,{chart_b64}"></div>'
                   if chart_b64 else "")

    html = EMAIL_HTML.format(
        date_str=date_str, send_time=send_time,
        sjc_block=sjc_block, intl_block=intl_block, chart_block=chart_block)

    txt = EMAIL_TXT.format(
        date_str=date_str, send_time=send_time,
        sjc_buy=fmt_vnd(sjc.buy_price if sjc else None),
        sjc_sell=fmt_vnd(sjc.sell_price if sjc else None),
        sjc_change=sjc_change,
        intl_price=fmt_usd(intl.buy_price if intl else None),
        intl_high=fmt_usd(intl.high if intl else None),
        intl_low=fmt_usd(intl.low if intl else None),
        intl_change=intl_change)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Giá Vàng Hôm Nay — {date_str}"
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    logger.info("Email sent to %s", RECIPIENT_EMAIL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.now(TZ)
    today = now.date()
    data = load_data()
    history = data.get("history", [])

    # Fetch previous day's prices for day-over-day comparison
    yesterday_entries = [h for h in history if h["date"] < str(today)]
    prev = yesterday_entries[-1] if yesterday_entries else {}
    prev_sjc_sell    = prev.get("sjc_sell")
    prev_intl_price  = prev.get("intl_price")

    # Fetch today's prices
    sjc = intl = None
    try:
        sjc = fetch_sjc_price()
        logger.info("SJC: buy=%s sell=%s VND/tael", sjc.buy_price, sjc.sell_price)
    except Exception as e:
        logger.error("SJC fetch failed: %s", e)

    try:
        intl = fetch_international_price()
        logger.info("International: %.2f USD/troy oz", intl.buy_price)
    except Exception as e:
        logger.error("International fetch failed: %s", e)

    # Update JSON
    today_entry = {
        "date": str(today),
        "sjc_buy":    sjc.buy_price if sjc else None,
        "sjc_sell":   sjc.sell_price if sjc else None,
        "intl_price": intl.buy_price if intl else None,
        "intl_high":  intl.high if intl else None,
        "intl_low":   intl.low if intl else None,
    }
    history = upsert_history(history, today_entry)

    data.update({
        "updated_at":    now.isoformat(),
        "sjc":           sjc.as_dict() if sjc else None,
        "international": intl.as_dict() if intl else None,
        "history":       history,
    })
    save_data(data)
    logger.info("Saved prices.json for %s", today)

    # Send email
    if GMAIL_USER and GMAIL_APP_PASSWORD and RECIPIENT_EMAIL:
        try:
            send_email(sjc, intl, prev_sjc_sell, prev_intl_price, history, now)
        except Exception as e:
            logger.error("Email send failed: %s", e)
    else:
        logger.warning("Email skipped — GMAIL_USER / GMAIL_APP_PASSWORD / RECIPIENT_EMAIL not set")


if __name__ == "__main__":
    main()
