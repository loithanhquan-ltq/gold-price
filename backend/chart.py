import io
import base64
import matplotlib
matplotlib.use("Agg")  # non-interactive — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from sqlalchemy.orm import Session
from backend import repository


def generate_chart_base64(db: Session, days: int = 7) -> str:
    """Return a dual-axis 7-day line chart as a base64-encoded PNG string."""
    rows = repository.history(db, days)
    sjc_rows = [r for r in rows if r.source == "SJC"]
    intl_rows = [r for r in rows if r.source == "INTERNATIONAL"]

    fig, ax1 = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a1a")
    ax1.set_facecolor("#1a1a1a")
    ax2 = ax1.twinx()
    ax2.set_facecolor("#1a1a1a")

    plotted = False
    if sjc_rows:
        dates = [r.price_date for r in sjc_rows]
        prices = [r.sell_price / 1_000_000 for r in sjc_rows]
        ax1.plot(dates, prices, color="#e6a817", linewidth=2, marker="o", markersize=4,
                 label="SJC (triệu VND/lượng)")
        ax1.set_ylabel("SJC (triệu VND/lượng)", color="#e6a817", fontsize=10)
        ax1.tick_params(axis="y", labelcolor="#e6a817")
        plotted = True

    if intl_rows:
        dates = [r.price_date for r in intl_rows]
        prices = [r.buy_price for r in intl_rows]
        ax2.plot(dates, prices, color="#2196F3", linewidth=2, marker="o", markersize=4,
                 label="XAU/USD")
        ax2.set_ylabel("XAU/USD ($/troy oz)", color="#2196F3", fontsize=10)
        ax2.tick_params(axis="y", labelcolor="#2196F3")
        plotted = True

    for ax in (ax1, ax2):
        ax.tick_params(axis="x", colors="#999")
        ax.spines["bottom"].set_color("#444")
        ax.spines["top"].set_color("#444")
        ax.spines["left"].set_color("#444")
        ax.spines["right"].set_color("#444")

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax1.grid(axis="y", color="#2a2a2a", linestyle="--", linewidth=0.8)
    fig.autofmt_xdate()

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    if lines1 or lines2:
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left",
                   facecolor="#2a2a2a", labelcolor="#ccc", fontsize=9)

    if not plotted:
        ax1.text(0.5, 0.5, "Chưa có dữ liệu", transform=ax1.transAxes,
                 ha="center", va="center", color="#888", fontsize=12)

    title = fig.suptitle(f"Giá Vàng — {days} Ngày Gần Nhất", fontsize=12,
                         fontweight="bold", color="#eee")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")
