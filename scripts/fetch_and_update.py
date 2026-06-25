"""
GitHub Actions entrypoint — runs daily at 10:00 ICT (03:00 UTC).

1. Fetch SJC + international gold prices
2. Update docs/data/prices.json (history kept for 90 days)
3. Send HTML email via Gmail SMTP
"""
import argparse
import json
import logging
import os
import smtplib
import ssl
import sys
import io
import base64
from datetime import datetime, date, timedelta, timezone
from email.mime.image import MIMEImage
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


def backfill_history(history: list, days: int = 8) -> list:
    """Seed missing days with XAU/USD history from CoinGecko market_chart API.
    Only runs when history is sparse; SJC is left null for backfilled days."""
    import requests
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/tether-gold/market_chart",
            params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        prices = resp.json().get("prices", [])  # [[timestamp_ms, price], ...]
    except Exception as e:
        logger.warning("History backfill failed: %s", e)
        return history

    existing = {h["date"] for h in history}
    added = 0
    for ts_ms, price in prices:
        d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
        date_str = str(d)
        if date_str not in existing and 500 < price < 20_000:
            history.append({
                "date": date_str,
                "sjc_buy": None, "sjc_sell": None,
                "intl_price": round(price, 2),
                "intl_high": None, "intl_low": None,
            })
            existing.add(date_str)
            added += 1

    history.sort(key=lambda x: x["date"])
    logger.info("Backfilled %d day(s) of XAU/USD history from CoinGecko", added)
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
        import matplotlib.ticker as mticker
        import numpy as np
        import math

        recent = history[-7:]
        if not recent:
            return None

        dates       = [date.fromisoformat(h["date"]) for h in recent]
        sjc_prices  = [h.get("sjc_sell")   or float("nan") for h in recent]
        intl_prices = [h.get("intl_price") or float("nan") for h in recent]

        # --- Palette ---
        BG       = "#ffffff"
        GRID     = "#e5e7eb"
        NAVY     = "#1e3a5f"   # SJC line — deep navy, matches email header
        AMBER    = "#b45309"   # XAU/USD line — amber/gold accent
        TICK_CLR = "#6b7280"   # axis tick labels
        TEXT     = "#374151"   # legend text
        SUBTEXT  = "#9ca3af"   # subtitle / secondary

        fig, ax1 = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor(BG)
        ax1.set_facecolor(BG)
        ax2 = ax1.twinx()

        # Convert SJC to millions; build numpy arrays for easy NaN handling
        sjc_m    = np.array(
            [p / 1_000_000 if not math.isnan(p) else float("nan") for p in sjc_prices],
            dtype=float,
        )
        intl_arr = np.array(intl_prices, dtype=float)

        has_sjc  = bool(np.any(~np.isnan(sjc_m)))
        has_intl = bool(np.any(~np.isnan(intl_arr)))

        # --- SJC line (left axis) ---
        if has_sjc:
            sjc_mask   = ~np.isnan(sjc_m)
            sjc_dates  = [d for d, m in zip(dates, sjc_mask) if m]
            sjc_vals   = sjc_m[sjc_mask]
            sjc_base   = float(np.nanmin(sjc_m))

            ax1.plot(
                sjc_dates, sjc_vals,
                color=NAVY, lw=1.5, linestyle="-",
                marker="o", ms=4,
                markerfacecolor=NAVY, markeredgecolor=NAVY, markeredgewidth=0,
                label="SJC (VND / lượng)", zorder=3,
            )
            ax1.fill_between(
                sjc_dates, sjc_vals, sjc_base,
                alpha=0.10, color=NAVY, zorder=2,
            )
            # Annotate last valid data point
            ax1.annotate(
                f"{sjc_vals[-1]:.0f}M",
                xy=(sjc_dates[-1], sjc_vals[-1]),
                xytext=(5, 0), textcoords="offset points",
                fontsize=7.5, color=NAVY, fontweight="bold",
                va="center", ha="left", fontfamily="monospace",
            )
            ax1.set_ylabel(
                "SJC (triệu VND / lượng)",
                color=NAVY, fontsize=8.5, labelpad=8,
            )
            ax1.tick_params(axis="y", labelcolor=TICK_CLR, labelsize=8,
                            length=3, width=0.6)
            ax1.yaxis.set_major_formatter(
                mticker.FuncFormatter(lambda x, _: f"{x:.0f}")
            )
        else:
            ax1.set_yticks([])
            ax1.set_ylabel("")

        # --- XAU/USD line (right axis) ---
        if has_intl:
            intl_mask  = ~np.isnan(intl_arr)
            intl_dates = [d for d, m in zip(dates, intl_mask) if m]
            intl_vals  = intl_arr[intl_mask]
            intl_base  = float(np.nanmin(intl_arr))

            ax2.plot(
                intl_dates, intl_vals,
                color=AMBER, lw=1.5, linestyle="-",
                marker="o", ms=4,
                markerfacecolor=AMBER, markeredgecolor=AMBER, markeredgewidth=0,
                label="XAU/USD", zorder=3,
            )
            ax2.fill_between(
                intl_dates, intl_vals, intl_base,
                alpha=0.10, color=AMBER, zorder=2,
            )
            # Annotate last valid data point (offset left so it sits inside axes)
            ax2.annotate(
                f"${intl_vals[-1]:,.0f}",
                xy=(intl_dates[-1], intl_vals[-1]),
                xytext=(-5, 0), textcoords="offset points",
                fontsize=7.5, color=AMBER, fontweight="bold",
                va="center", ha="right", fontfamily="monospace",
            )
            ax2.set_ylabel(
                "XAU/USD ($ / troy oz)",
                color=AMBER, fontsize=8.5, labelpad=8,
            )
            ax2.tick_params(axis="y", labelcolor=TICK_CLR, labelsize=8,
                            length=3, width=0.6)
            ax2.yaxis.set_major_formatter(
                mticker.FuncFormatter(lambda x, _: f"${x:,.0f}")
            )
        else:
            ax2.set_yticks([])
            ax2.set_ylabel("")

        # --- Grid: horizontal dashed only, no vertical clutter ---
        ax1.grid(axis="y", color=GRID, linestyle="--", lw=0.7, zorder=0)
        ax1.grid(axis="x", visible=False)
        ax2.grid(visible=False)
        ax1.set_axisbelow(True)

        # --- Date axis: "DD/MM" labels, minimal 20° rotation ---
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
        ax1.xaxis.set_major_locator(mdates.DayLocator())
        ax1.tick_params(axis="x", colors=TICK_CLR, labelsize=8,
                        length=3, width=0.6)
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=20, ha="right")

        # --- Spines: remove top; keep others thin and light ---
        for ax in (ax1, ax2):
            ax.spines["top"].set_visible(False)
            ax.spines["left"].set_color(GRID)
            ax.spines["left"].set_linewidth(0.6)
            ax.spines["right"].set_color(GRID)
            ax.spines["right"].set_linewidth(0.6)
            ax.spines["bottom"].set_color(GRID)
            ax.spines["bottom"].set_linewidth(0.6)

        # --- Legend: combined, compact, inside upper-left ---
        lines1, lbl1 = ax1.get_legend_handles_labels()
        lines2, lbl2 = ax2.get_legend_handles_labels()
        if lines1 or lines2:
            leg = ax1.legend(
                lines1 + lines2, lbl1 + lbl2,
                loc="upper left",
                fontsize=7.5,
                frameon=True,
                facecolor=BG,
                edgecolor=GRID,
                labelcolor=TEXT,
                framealpha=0.92,
                borderpad=0.5,
                handlelength=1.2,
                handletextpad=0.4,
            )
            leg.get_frame().set_linewidth(0.6)

        # --- Subtitle: date range inside chart, centered at top ---
        if dates:
            d_start  = dates[0].strftime("%d/%m")
            d_end    = dates[-1].strftime("%d/%m")
            subtitle = f"{d_start} – {d_end}  ·  {len(dates)} ngày"
            ax1.text(
                0.5, 0.97, subtitle,
                transform=ax1.transAxes,
                fontsize=7.5, color=SUBTEXT,
                ha="center", va="top", style="italic",
            )

        plt.tight_layout(pad=0.8)

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130,
                    bbox_inches="tight", facecolor=BG, edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()
    except Exception as e:
        logger.warning("Chart generation failed: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Email templates — light scientific theme, inline styles, %%NAME%% placeholders
# ---------------------------------------------------------------------------

_EMAIL_HTML = """\
<!DOCTYPE html>
<html lang="vi">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,'Helvetica Neue',Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f3f4f6">
<tr><td align="center" style="padding:24px 12px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border:1px solid #d1d5db;">

  <!-- HEADER -->
  <tr><td style="background:#1e3a5f;padding:0;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="padding:22px 28px;">
        <div style="font-size:11px;font-weight:700;color:#93c5fd;letter-spacing:2px;
                    text-transform:uppercase;margin-bottom:6px;">GOLD MARKET REPORT</div>
        <div style="font-size:22px;font-weight:700;color:#ffffff;line-height:1.2;">
          Bảng Giá Vàng Hôm Nay
        </div>
        <div style="margin-top:6px;font-size:13px;color:#93c5fd;">
          %%WEEKDAY%%, %%DATE%%
        </div>
      </td>
      <td style="padding:22px 28px;text-align:right;vertical-align:top;">
        <div style="font-size:10px;color:#64748b;margin-bottom:3px;">PHÁT HÀNH LÚC</div>
        <div style="font-size:20px;font-weight:700;color:#fbbf24;font-family:monospace;">%%TIME%% ICT</div>
      </td>
    </tr>
    </table>
    <div style="height:3px;background:linear-gradient(90deg,#fbbf24 0%,#f59e0b 50%,#d97706 100%);"></div>
  </td></tr>

  %%SJC_BLOCK%%

  %%INTL_BLOCK%%

  %%CHART_BLOCK%%

  <!-- FOOTER -->
  <tr><td style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:14px 28px;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="font-size:11px;color:#9ca3af;">
        Nguồn: giavang.doji.vn &nbsp;&bull;&nbsp; Yahoo Finance / CoinGecko (XAU/USD)
      </td>
      <td style="font-size:11px;color:#9ca3af;text-align:right;font-style:italic;">
        Chỉ mang tính tham khảo
      </td>
    </tr>
    </table>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

_SJC_OK = """\
<tr><td style="padding:0;border-bottom:1px solid #e5e7eb;">
  <!-- section label -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
  <tr><td style="padding:9px 28px;">
    <span style="font-size:10px;font-weight:700;color:#1e3a5f;
                 text-transform:uppercase;letter-spacing:1.5px;">
      SJC &mdash; Vàng Trong Nước &nbsp;/&nbsp; VND per Lượng
    </span>
  </td></tr>
  </table>
  <!-- price row -->
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="width:33%;padding:18px 0 18px 28px;border-right:1px solid #e5e7eb;vertical-align:top;">
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">Giá Mua (Bid)</div>
      <div style="font-size:22px;font-weight:700;color:#1e3a5f;font-family:monospace;">%%SJC_BUY%%</div>
    </td>
    <td style="width:33%;padding:18px 0 18px 20px;border-right:1px solid #e5e7eb;vertical-align:top;">
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">Giá Bán (Ask)</div>
      <div style="font-size:22px;font-weight:700;color:#1e3a5f;font-family:monospace;">%%SJC_SELL%%</div>
    </td>
    <td style="width:34%;padding:18px 20px 18px 20px;vertical-align:top;">
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">Spread</div>
      <div style="font-size:16px;font-weight:700;color:#374151;font-family:monospace;">%%SJC_SPREAD%%</div>
    </td>
  </tr>
  </table>
  <!-- change row -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f9fafb;border-top:1px solid #e5e7eb;">
  <tr>
    <td style="padding:9px 28px;font-size:12px;color:#6b7280;">
      Thay đổi so với phiên trước (Ask):&nbsp;
      <strong style="color:%%SJC_CC%%;">%%SJC_ARROW%% %%SJC_CHANGE%%</strong>
    </td>
  </tr>
  </table>
</td></tr>"""

_INTL_OK = """\
<tr><td style="padding:0;border-bottom:1px solid #e5e7eb;">
  <!-- section label -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
  <tr><td style="padding:9px 28px;">
    <span style="font-size:10px;font-weight:700;color:#1e3a5f;
                 text-transform:uppercase;letter-spacing:1.5px;">
      XAU/USD &mdash; Vàng Thế Giới &nbsp;/&nbsp; USD per Troy Oz
    </span>
  </td></tr>
  </table>
  <!-- price row -->
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="width:33%;padding:18px 0 18px 28px;border-right:1px solid #e5e7eb;vertical-align:top;">
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">Spot Price</div>
      <div style="font-size:26px;font-weight:700;color:#b45309;font-family:monospace;">%%INTL_PRICE%%</div>
    </td>
    <td style="width:33%;padding:18px 0 18px 20px;border-right:1px solid #e5e7eb;vertical-align:top;">
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">High</div>
      <div style="font-size:16px;font-weight:700;color:#15803d;font-family:monospace;">%%INTL_HIGH%%</div>
      <div style="margin-top:12px;font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">Low</div>
      <div style="font-size:16px;font-weight:700;color:#b91c1c;font-family:monospace;">%%INTL_LOW%%</div>
    </td>
    <td style="width:34%;padding:18px 20px 18px 20px;vertical-align:top;">
      <div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px;">Thay Đổi</div>
      <div style="font-size:18px;font-weight:700;color:%%INTL_CC%%;font-family:monospace;">%%INTL_ARROW%% %%INTL_CHANGE%%</div>
      <div style="margin-top:4px;font-size:10px;color:#9ca3af;">so với phiên trước</div>
    </td>
  </tr>
  </table>
</td></tr>"""

_MISSING = """\
<tr><td style="padding:0;border-bottom:1px solid #e5e7eb;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
  <tr><td style="padding:9px 28px;">
    <span style="font-size:10px;font-weight:700;color:#1e3a5f;
                 text-transform:uppercase;letter-spacing:1.5px;">%%TITLE%%</span>
  </td></tr>
  </table>
  <div style="padding:16px 28px;font-size:13px;color:#b91c1c;">
    Không lấy được dữ liệu hôm nay.
  </div>
</td></tr>"""

_CHART_ROW = """\
<tr><td style="padding:0;border-bottom:1px solid #e5e7eb;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
  <tr><td style="padding:9px 28px;">
    <span style="font-size:10px;font-weight:700;color:#1e3a5f;
                 text-transform:uppercase;letter-spacing:1.5px;">
      7-Day Price Chart &mdash; SJC &amp; XAU/USD
    </span>
  </td></tr>
  </table>
  <div style="padding:16px 28px;">
    <img src="cid:goldchart@tracker"
         alt="7-day gold chart"
         style="width:100%;max-width:544px;display:block;border:1px solid #e5e7eb;">
  </div>
</td></tr>"""

# Preview variant: data: URI so the HTML file is self-contained in a browser
_CHART_ROW_PREVIEW = """\
<tr><td style="padding:0;border-bottom:1px solid #e5e7eb;">
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
  <tr><td style="padding:9px 28px;">
    <span style="font-size:10px;font-weight:700;color:#1e3a5f;
                 text-transform:uppercase;letter-spacing:1.5px;">
      7-Day Price Chart &mdash; SJC &amp; XAU/USD
    </span>
  </td></tr>
  </table>
  <div style="padding:16px 28px;">
    <img src="data:image/png;base64,%%B64%%"
         alt="7-day gold chart"
         style="width:100%;max-width:544px;display:block;border:1px solid #e5e7eb;">
  </div>
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

    # Chart: generate PNG bytes; attach as CID inline image
    # (data: URIs are blocked by Gmail; cid: works in all major clients)
    chart_b64   = build_chart_b64(history)
    chart_bytes = base64.b64decode(chart_b64) if chart_b64 else None
    logger.info("Chart generated: %s", f"{len(chart_bytes):,} bytes" if chart_bytes else "None — chart will be omitted")
    chart_block = _CHART_ROW if chart_bytes else ""

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

    # Three-layer MIME nesting for maximum Gmail/Outlook/Apple Mail compatibility:
    # multipart/mixed → multipart/related → multipart/alternative + image
    msg_root    = MIMEMultipart("mixed")
    msg_related = MIMEMultipart("related")
    msg_alt     = MIMEMultipart("alternative")
    msg_alt.attach(MIMEText(txt, "plain", "utf-8"))
    msg_alt.attach(MIMEText(html, "html", "utf-8"))
    msg_related.attach(msg_alt)

    if chart_bytes:
        img = MIMEImage(chart_bytes, "png")
        img.add_header("Content-ID", "<goldchart@tracker>")
        img.add_header("Content-Disposition", "inline", filename="chart.png")
        msg_related.attach(img)

    msg_root.attach(msg_related)
    msg_root["Subject"] = f"Giá Vàng Hôm Nay — {date_str}"
    msg_root["From"]    = GMAIL_USER
    msg_root["To"]      = ", ".join(recipients)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        s.sendmail(GMAIL_USER, recipients, msg_root.as_string())
    logger.info("Email sent to %s", ", ".join(recipients))


# ---------------------------------------------------------------------------
# Preview helper
# ---------------------------------------------------------------------------

def build_preview_html(sjc, intl, prev_sjc_sell, prev_intl_price, history, now_local) -> str:
    """Return the full email HTML with the chart as a self-contained data: URI.
    Suitable for writing to a file and opening in a browser — no MIME/CID needed."""
    WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    date_str  = now_local.strftime("%d/%m/%Y")
    send_time = now_local.strftime("%H:%M")
    weekday   = WEEKDAYS[now_local.weekday()]

    def _color(css): return {"up": "#15803d", "down": "#b91c1c"}.get(css, "#6b7280")
    def _arrow(css): return {"up": "▲", "down": "▼"}.get(css, "—")

    sjc_change, sjc_css = change_info(sjc.sell_price if sjc else None, prev_sjc_sell, fmt_vnd)
    if sjc:
        sjc_block = (_SJC_OK
            .replace("%%SJC_BUY%%",    fmt_vnd(sjc.buy_price))
            .replace("%%SJC_SELL%%",   fmt_vnd(sjc.sell_price))
            .replace("%%SJC_SPREAD%%", fmt_vnd(sjc.sell_price - sjc.buy_price))
            .replace("%%SJC_CC%%",     _color(sjc_css))
            .replace("%%SJC_ARROW%%",  _arrow(sjc_css))
            .replace("%%SJC_CHANGE%%", sjc_change))
    else:
        sjc_block = _MISSING.replace("%%TITLE%%", "SJC — Vàng Trong Nước")

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
        intl_block = _MISSING.replace("%%TITLE%%", "XAU/USD — Vàng Thế Giới")

    chart_b64   = build_chart_b64(history)
    chart_block = (_CHART_ROW_PREVIEW.replace("%%B64%%", chart_b64)
                   if chart_b64 else "")

    return (_EMAIL_HTML
        .replace("%%WEEKDAY%%",     weekday)
        .replace("%%DATE%%",        date_str)
        .replace("%%TIME%%",        send_time)
        .replace("%%SJC_BLOCK%%",   sjc_block)
        .replace("%%INTL_BLOCK%%",  intl_block)
        .replace("%%CHART_BLOCK%%", chart_block))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true",
                        help="Write email HTML to docs/preview.html instead of sending")
    args = parser.parse_args()

    now = datetime.now(TZ)
    today = now.date()
    data = load_data()
    history = data.get("history", [])

    # Seed missing historical days on first runs so the chart has enough data
    if len(history) < 7:
        history = backfill_history(history)

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

    # Preview mode — write self-contained HTML and exit
    if args.preview:
        html = build_preview_html(sjc, intl, prev_sjc_sell, prev_intl_price, history, now)
        out = Path(__file__).parent.parent / "docs" / "preview.html"
        out.write_text(html, encoding="utf-8")
        logger.info("Preview written to %s", out)
        return

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
