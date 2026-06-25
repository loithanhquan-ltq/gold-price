import io
import base64
import matplotlib
matplotlib.use("Agg")  # non-interactive — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sqlalchemy.orm import Session
from backend import repository

_BG = "#0f0f0f"
_PANEL = "#161616"
_GRID = "#2c2c2c"
_BORDER = "#333333"
_SJC_COLOR = "#f0b429"
_INTL_COLOR = "#4d9de0"
_TEXT_DIM = "#888888"
_TEXT_BRIGHT = "#e8e8e8"


def _set_zoomed_ylim(ax, values, pad_ratio=0.3):
    """Zoom y-axis into the data range with padding so fills look correct."""
    lo, hi = min(values), max(values)
    spread = hi - lo or hi * 0.01
    ax.set_ylim(lo - spread * pad_ratio, hi + spread * pad_ratio)


def generate_chart_base64(db: Session, days: int = 7) -> str:
    """Return a dual-axis line chart as a base64-encoded PNG string."""
    rows = repository.history(db, days)
    sjc_rows = [r for r in rows if r.source == "SJC"]
    intl_rows = [r for r in rows if r.source == "INTERNATIONAL"]

    fig, ax1 = plt.subplots(figsize=(11, 4.2))
    fig.patch.set_facecolor(_BG)
    ax1.set_facecolor(_PANEL)
    ax2 = ax1.twinx()
    ax2.set_facecolor(_PANEL)

    plotted = False

    if sjc_rows:
        dates = [r.price_date for r in sjc_rows]
        prices = [r.sell_price / 1_000_000 for r in sjc_rows]
        _set_zoomed_ylim(ax1, prices)
        ax1.plot(dates, prices, color=_SJC_COLOR, linewidth=1.8, zorder=3)
        ax1.fill_between(dates, prices, ax1.get_ylim()[0],
                         color=_SJC_COLOR, alpha=0.08, linewidth=0, zorder=2)
        ax1.annotate(
            f"{prices[-1]:.1f}",
            xy=(dates[-1], prices[-1]),
            xytext=(6, 4), textcoords="offset points",
            color=_SJC_COLOR, fontsize=8.5, va="bottom", fontweight="bold",
        )
        ax1.tick_params(axis="y", labelcolor=_SJC_COLOR, labelsize=8.5)
        plotted = True

    if intl_rows:
        dates = [r.price_date for r in intl_rows]
        prices = [r.buy_price for r in intl_rows]
        _set_zoomed_ylim(ax2, prices)
        ax2.plot(dates, prices, color=_INTL_COLOR, linewidth=1.8, zorder=3)
        ax2.fill_between(dates, prices, ax2.get_ylim()[0],
                         color=_INTL_COLOR, alpha=0.08, linewidth=0, zorder=2)
        ax2.annotate(
            f"{prices[-1]:,.0f}",
            xy=(dates[-1], prices[-1]),
            xytext=(6, -4), textcoords="offset points",
            color=_INTL_COLOR, fontsize=8.5, va="top", ha="left", fontweight="bold",
        )
        ax2.tick_params(axis="y", labelcolor=_INTL_COLOR, labelsize=8.5)
        plotted = True

    # Spines and tick styling
    for ax in (ax1, ax2):
        for spine in ax.spines.values():
            spine.set_color(_BORDER)
            spine.set_linewidth(0.8)
        ax.tick_params(axis="x", colors=_TEXT_DIM, labelsize=8.5)

    # Grid on ax1 only so lines don't double-render
    ax1.grid(axis="y", color=_GRID, linestyle="-", linewidth=0.7, zorder=0)
    ax1.grid(axis="x", color=_GRID, linestyle="-", linewidth=0.5, zorder=0)
    ax2.grid(False)

    # X-axis: evenly spaced ticks, dd/mm labels, no rotation
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=10))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate(rotation=0, ha="center")

    # Horizontal axis-label chips above each y-axis (no rotated ylabel)
    ax1.set_ylabel("")
    ax2.set_ylabel("")
    ax1.annotate("SJC (tr. VND)", xy=(0, 1.01), xycoords="axes fraction",
                 color=_SJC_COLOR, fontsize=8.5, va="bottom")
    ax2.annotate("XAU/USD ($)", xy=(1, 1.01), xycoords="axes fraction",
                 color=_INTL_COLOR, fontsize=8.5, va="bottom", ha="right")

    if not plotted:
        ax1.text(0.5, 0.5, "Chưa có dữ liệu", transform=ax1.transAxes,
                 ha="center", va="center", color=_TEXT_DIM, fontsize=12)

    ax1.legend(
        handles=[
            plt.Line2D([0], [0], color=_SJC_COLOR, linewidth=2, label="SJC Sell"),
            plt.Line2D([0], [0], color=_INTL_COLOR, linewidth=2, label="XAU/USD"),
        ],
        loc="upper left", framealpha=0.15, facecolor="#222222",
        edgecolor=_BORDER, fontsize=8.5, labelcolor=_TEXT_BRIGHT,
    )

    fig.suptitle(
        f"Giá Vàng  ·  {days} Ngày Gần Nhất",
        fontsize=11, fontweight="bold", color=_TEXT_BRIGHT,
        x=0.5, y=1.0,
    )
    plt.tight_layout(pad=1.2)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
