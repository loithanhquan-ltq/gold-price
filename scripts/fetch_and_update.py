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
        from matplotlib.ticker import FuncFormatter

        recent = history[-7:]
        if not recent:
            return None

        dates       = [date.fromisoformat(h["date"]) for h in recent]
        sjc_prices  = [h.get("sjc_sell") for h in recent]
        intl_prices = [h.get("intl_price") for h in recent]

        BG, CARD, GRID = "#0d1117", "#161b22", "#21262d"
        GOLD, BLUE, TEXT = "#f59e0b", "#58a6ff", "#8b949e"

        fig, ax1 = plt.subplots(figsize=(10, 4.2))
        fig.patch.set_facecolor(BG)
        ax1.set_facecolor(BG)
        ax2 = ax1.twinx()

        has_sjc  = any(p for p in sjc_prices if p)
        has_intl = any(p for p in intl_prices if p)

        if has_sjc:
            vals = [p / 1_000_000 if p else None for p in sjc_prices]
            ax1.plot(dates, vals, color=GOLD, lw=2.5, marker="o", ms=5,
                     markerfacecolor=GOLD, label="SJC (triệu ₫/lượng)", zorder=3)
            ax1.fill_between(dates, vals, alpha=0.1, color=GOLD)
            ax1.set_ylabel("SJC (triệu VND/lượng)", color=GOLD, fontsize=9)
            ax1.tick_params(axis="y", labelcolor=GOLD, labelsize=8)
            ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}"))

        if has_intl:
            ax2.plot(dates, intl_prices, color=BLUE, lw=2.5, marker="o", ms=5,
                     markerfacecolor=BLUE, label="XAU/USD", zorder=3)
            ax2.fill_between(dates, intl_prices, alpha=0.08, color=BLUE)
            ax2.set_ylabel("XAU/USD ($/troy oz)", color=BLUE, fontsize=9)
            ax2.tick_params(axis="y", labelcolor=BLUE, labelsize=8)
            ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))

        for ax in (ax1, ax2):
            ax.tick_params(axis="x", colors=TEXT, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(GRID)

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        ax1.xaxis.set_major_locator(mdates.DayLocator())
        ax1.grid(axis="y", color=GRID, linestyle="--", lw=0.8, alpha=0.7)
        ax1.set_axisbelow(True)
        fig.autofmt_xdate(rotation=25, ha="right")

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        if lines1 or lines2:
            ax1.legend(lines1 + lines2, labels1 + labels2,
                       facecolor=CARD, edgecolor=GRID, labelcolor=TEXT,
                       fontsize=9, loc="upper left", framealpha=0.95)

        fig.suptitle("Diễn biến giá vàng — 7 ngày gần nhất",
                     fontsize=11, fontweight="bold", color="#e2e8f0", y=1.01)
        plt.tight_layout(pad=1.2)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                    facecolor=BG, edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as e:
        logger.warning("Chart generation failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Email templates — all inline styles, placeholders use %%NAME%% to avoid
# any conflict with CSS braces or Python str.format()
# ---------------------------------------------------------------------------

_EMAIL_HTML = """\
<!DOCTYPE html>
<html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0d1117;font-family:'Segoe UI',Tahoma,Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#0d1117">
<tr><td align="center" style="padding:24px 12px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <tr><td style="background:linear-gradient(160deg,#1c0e00 0%,#3b1f00 50%,#1c0e00 100%);
                 border-radius:16px 16px 0 0;padding:36px 32px 30px;text-align:center;
                 border-bottom:2px solid #f59e0b;">
    <div style="font-size:44px;line-height:1;margin-bottom:14px;">🥇</div>
    <h1 style="margin:0 0 10px;color:#f59e0b;font-size:26px;font-weight:800;
               letter-spacing:2px;text-transform:uppercase;">Bảng Giá Vàng Hôm Nay</h1>
    <p style="margin:0;color:#d4a017;font-size:15px;">%%WEEKDAY%% &mdash; %%DATE%%</p>
  </td></tr>

  %%SJC_BLOCK%%

  %%INTL_BLOCK%%

  %%CHART_BLOCK%%

  <tr><td style="background:#161b22;border-radius:0 0 16px 16px;padding:20px 32px;
                 text-align:center;border-top:1px solid #30363d;">
    <p style="margin:0 0 5px;color:#8b949e;font-size:12px;">
      Gửi lúc %%TIME%% ICT &nbsp;&bull;&nbsp; Nguồn: giavang.doji.vn &amp; Yahoo Finance / CoinGecko
    </p>
    <p style="margin:0;color:#484f58;font-size:11px;font-style:italic;">
      Thông tin chỉ mang tính tham khảo, không phải lời khuyên đầu tư.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

_SJC_OK = """\
<tr><td style="background:#161b22;padding:24px 32px;border-bottom:1px solid #21262d;">
  <p style="margin:0 0 16px;color:#f59e0b;font-size:11px;font-weight:700;
            text-transform:uppercase;letter-spacing:2px;">🇻🇳 &nbsp;Vàng SJC trong nước</p>
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="width:48%;vertical-align:top;padding-right:6px;">
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;
                 padding:18px;text-align:center;">
        <div style="color:#8b949e;font-size:10px;text-transform:uppercase;
                   letter-spacing:1px;margin-bottom:8px;">Giá Mua</div>
        <div style="color:#58a6ff;font-size:18px;font-weight:800;line-height:1.3;">%%SJC_BUY%%</div>
        <div style="color:#484f58;font-size:10px;margin-top:5px;">VND / lượng</div>
      </div>
    </td>
    <td style="width:4%;"></td>
    <td style="width:48%;vertical-align:top;padding-left:6px;">
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;
                 padding:18px;text-align:center;">
        <div style="color:#8b949e;font-size:10px;text-transform:uppercase;
                   letter-spacing:1px;margin-bottom:8px;">Giá Bán</div>
        <div style="color:#f59e0b;font-size:18px;font-weight:800;line-height:1.3;">%%SJC_SELL%%</div>
        <div style="color:#484f58;font-size:10px;margin-top:5px;">VND / lượng</div>
      </div>
    </td>
  </tr>
  </table>
  <div style="margin-top:10px;padding:11px 16px;background:#0d1117;border:1px solid #21262d;
             border-radius:8px;text-align:center;">
    <span style="color:#8b949e;font-size:11px;">Chênh lệch mua/bán: </span>
    <span style="color:#e2e8f0;font-size:13px;font-weight:700;">%%SJC_SPREAD%%</span>
  </div>
  <div style="margin-top:8px;padding:11px 16px;background:#0d1117;border:1px solid #21262d;
             border-radius:8px;text-align:center;">
    <span style="color:%%SJC_CC%%;font-size:15px;font-weight:700;">%%SJC_ARROW%% %%SJC_CHANGE%%</span>
    <span style="color:#8b949e;font-size:11px;margin-left:6px;">so với hôm qua (giá bán)</span>
  </div>
</td></tr>"""

_INTL_OK = """\
<tr><td style="background:#161b22;padding:24px 32px;border-bottom:1px solid #21262d;">
  <p style="margin:0 0 16px;color:#f59e0b;font-size:11px;font-weight:700;
            text-transform:uppercase;letter-spacing:2px;">🌐 &nbsp;Vàng thế giới (XAU/USD)</p>
  <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;
             padding:22px;text-align:center;margin-bottom:10px;">
    <div style="color:#8b949e;font-size:10px;text-transform:uppercase;
               letter-spacing:1px;margin-bottom:8px;">Giá Hiện Tại</div>
    <div style="color:#f59e0b;font-size:30px;font-weight:800;line-height:1.2;">%%INTL_PRICE%%</div>
    <div style="color:#484f58;font-size:10px;margin-top:5px;">USD / troy oz</div>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="width:48%;vertical-align:top;padding-right:6px;">
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;
                 padding:14px;text-align:center;">
        <div style="color:#8b949e;font-size:10px;margin-bottom:6px;">↑ Cao nhất</div>
        <div style="color:#3fb950;font-size:14px;font-weight:700;">%%INTL_HIGH%%</div>
      </div>
    </td>
    <td style="width:4%;"></td>
    <td style="width:48%;vertical-align:top;padding-left:6px;">
      <div style="background:#0d1117;border:1px solid #21262d;border-radius:10px;
                 padding:14px;text-align:center;">
        <div style="color:#8b949e;font-size:10px;margin-bottom:6px;">↓ Thấp nhất</div>
        <div style="color:#f85149;font-size:14px;font-weight:700;">%%INTL_LOW%%</div>
      </div>
    </td>
  </tr>
  </table>
  <div style="margin-top:10px;padding:11px 16px;background:#0d1117;border:1px solid #21262d;
             border-radius:8px;text-align:center;">
    <span style="color:%%INTL_CC%%;font-size:15px;font-weight:700;">%%INTL_ARROW%% %%INTL_CHANGE%%</span>
    <span style="color:#8b949e;font-size:11px;margin-left:6px;">so với hôm qua</span>
  </div>
</td></tr>"""

_MISSING = """\
<tr><td style="background:#161b22;padding:24px 32px;border-bottom:1px solid #21262d;">
  <p style="margin:0 0 12px;color:#f59e0b;font-size:11px;font-weight:700;
            text-transform:uppercase;letter-spacing:2px;">%%TITLE%%</p>
  <div style="background:#1a0a0a;border:1px solid #5a1e1e;border-radius:8px;
             padding:14px;text-align:center;color:#f85149;font-size:13px;">
    ⚠ Không lấy được dữ liệu hôm nay.
  </div>
</td></tr>"""

_CHART_ROW = """\
<tr><td style="background:#161b22;padding:20px 32px;border-bottom:1px solid #21262d;">
  <p style="margin:0 0 14px;color:#f59e0b;font-size:11px;font-weight:700;
            text-transform:uppercase;letter-spacing:2px;">📈 &nbsp;Diễn biến 7 ngày gần nhất</p>
  <img src="data:image/png;base64,%%B64%%"
       alt="7-day gold chart"
       style="width:100%;max-width:536px;border-radius:10px;display:block;">
</td></tr>"""

EMAIL_TXT = """\
BẢNG GIÁ VÀNG HÔM NAY — {date_str}
=========================================

VÀNG SJC (VND / Lượng)
  Mua       : {sjc_buy}
  Bán       : {sjc_sell}
  Chênh lệch: {sjc_spread}
  Thay đổi  : {sjc_change}

VÀNG THẾ GIỚI (USD / Troy oz)
  Giá       : {intl_price}
  Cao nhất  : {intl_high}
  Thấp nhất : {intl_low}
  Thay đổi  : {intl_change}

--
Gửi lúc {send_time} ICT | Nguồn: giavang.doji.vn & Yahoo Finance / CoinGecko
"""


def send_email(sjc, intl, prev_sjc_sell, prev_intl_price, history, now_local):
    WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    date_str  = now_local.strftime("%d/%m/%Y")
    send_time = now_local.strftime("%H:%M")
    weekday   = WEEKDAYS[now_local.weekday()]

    def _color(css): return {"up": "#3fb950", "down": "#f85149"}.get(css, "#8b949e")
    def _arrow(css): return {"up": "▲", "down": "▼"}.get(css, "—")

    # SJC section
    sjc_change, sjc_css = change_info(sjc.sell_price if sjc else None, prev_sjc_sell, fmt_vnd)
    if sjc:
        spread    = sjc.sell_price - sjc.buy_price
        sjc_block = (_SJC_OK
            .replace("%%SJC_BUY%%",    fmt_vnd(sjc.buy_price))
            .replace("%%SJC_SELL%%",   fmt_vnd(sjc.sell_price))
            .replace("%%SJC_SPREAD%%", fmt_vnd(spread))
            .replace("%%SJC_CC%%",     _color(sjc_css))
            .replace("%%SJC_ARROW%%",  _arrow(sjc_css))
            .replace("%%SJC_CHANGE%%", sjc_change))
    else:
        sjc_block = _MISSING.replace("%%TITLE%%", "🇻🇳 Vàng SJC trong nước")

    # International section
    intl_change, intl_css = change_info(intl.buy_price if intl else None, prev_intl_price, fmt_usd)
    if intl:
        intl_block = (_INTL_OK
            .replace("%%INTL_PRICE%%",  fmt_usd(intl.buy_price))
            .replace("%%INTL_HIGH%%",   fmt_usd(intl.high) if intl.high else "N/A")
            .replace("%%INTL_LOW%%",    fmt_usd(intl.low) if intl.low else "N/A")
            .replace("%%INTL_CC%%",     _color(intl_css))
            .replace("%%INTL_ARROW%%",  _arrow(intl_css))
            .replace("%%INTL_CHANGE%%", intl_change))
    else:
        intl_block = _MISSING.replace("%%TITLE%%", "🌐 Vàng thế giới (XAU/USD)")

    # Chart section
    chart_b64   = build_chart_b64(history)
    chart_block = _CHART_ROW.replace("%%B64%%", chart_b64) if chart_b64 else ""

    html = (_EMAIL_HTML
        .replace("%%WEEKDAY%%",     weekday)
        .replace("%%DATE%%",        date_str)
        .replace("%%TIME%%",        send_time)
        .replace("%%SJC_BLOCK%%",   sjc_block)
        .replace("%%INTL_BLOCK%%",  intl_block)
        .replace("%%CHART_BLOCK%%", chart_block))

    txt = EMAIL_TXT.format(
        date_str=date_str,    send_time=send_time,
        sjc_buy=fmt_vnd(sjc.buy_price if sjc else None),
        sjc_sell=fmt_vnd(sjc.sell_price if sjc else None),
        sjc_spread=fmt_vnd(sjc.sell_price - sjc.buy_price) if sjc else "N/A",
        sjc_change=sjc_change,
        intl_price=fmt_usd(intl.buy_price if intl else None),
        intl_high=fmt_usd(intl.high if intl else None),
        intl_low=fmt_usd(intl.low if intl else None),
        intl_change=intl_change)

    recipients = [e.strip() for e in RECIPIENT_EMAIL.split(",") if e.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Giá Vàng Hôm Nay — {date_str}"
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(txt, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, recipients, msg.as_string())
    logger.info("Email sent to %s", ", ".join(recipients))


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
