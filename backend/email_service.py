import logging
import smtplib
import ssl
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from backend import repository
from backend.config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL, TZ
from backend.scrapers.base import PriceResult

logger = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).parent / "templates"


def _fmt_vnd(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.0f} ₫"


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"${v:,.2f}"


def _change_info(current: float | None, previous: float | None, fmt_fn) -> tuple[str, str]:
    if current is None or previous is None or previous == 0:
        return "N/A", "neutral"
    diff = current - previous
    pct = (diff / previous) * 100
    sign = "+" if diff >= 0 else ""
    css = "up" if diff > 0 else ("down" if diff < 0 else "neutral")
    return f"{sign}{fmt_fn(diff)} ({sign}{pct:.2f}%)", css


def send_daily_email(
    db: Session,
    today: date,
    sjc: PriceResult | None,
    intl: PriceResult | None,
    sjc_stale: bool = False,
    intl_stale: bool = False,
):
    prev_sjc = repository.latest_before(db, "SJC", today)
    prev_intl = repository.latest_before(db, "INTERNATIONAL", today)

    sjc_change_str, sjc_change_class = _change_info(
        sjc.sell_price if sjc else None,
        prev_sjc.sell_price if prev_sjc else None,
        _fmt_vnd,
    )
    intl_change_str, intl_change_class = _change_info(
        intl.buy_price if intl else None,
        prev_intl.buy_price if prev_intl else None,
        _fmt_usd,
    )

    now_local = datetime.now(TZ)
    ctx_vars = dict(
        date_str=now_local.strftime("%d/%m/%Y"),
        send_time=now_local.strftime("%H:%M"),
        sjc_stale=sjc_stale,
        intl_stale=intl_stale,
        sjc=dict(
            buy_fmt=_fmt_vnd(sjc.buy_price if sjc else None),
            sell_fmt=_fmt_vnd(sjc.sell_price if sjc else None),
            change_str=sjc_change_str,
            change_class=sjc_change_class,
        ) if sjc else None,
        intl=dict(
            price_fmt=_fmt_usd(intl.buy_price if intl else None),
            high_fmt=_fmt_usd(intl.high if intl else None),
            low_fmt=_fmt_usd(intl.low if intl else None),
            change_str=intl_change_str,
            change_class=intl_change_class,
        ) if intl else None,
    )

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)
    html_body = env.get_template("email.html").render(**ctx_vars)
    text_body = env.get_template("email.txt").render(**ctx_vars)

    recipients = [addr.strip() for addr in RECIPIENT_EMAIL.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Giá Vàng Hôm Nay — {now_local.strftime('%d/%m/%Y')}"
    msg["From"] = GMAIL_USER
    msg["To"] = GMAIL_USER
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ssl_ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl_ctx) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, recipients, msg.as_string())

    logger.info("Email sent to %d recipient(s) for %s", len(recipients), today)
