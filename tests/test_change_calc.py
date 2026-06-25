"""Test the price change calculation helper in email_service."""
from backend.email_service import _change_info, _fmt_vnd, _fmt_usd


def test_price_up():
    s, css = _change_info(150_000_000, 145_000_000, _fmt_vnd)
    assert css == "up"
    assert "+" in s
    assert "3.45%" in s


def test_price_down():
    s, css = _change_info(2900.0, 3000.0, _fmt_usd)
    assert css == "down"
    assert "-" in s


def test_price_unchanged():
    s, css = _change_info(100.0, 100.0, _fmt_usd)
    assert css == "neutral"
    assert "0.00%" in s


def test_missing_previous():
    s, css = _change_info(100.0, None, _fmt_usd)
    assert s == "N/A"
    assert css == "neutral"


def test_missing_current():
    s, css = _change_info(None, 100.0, _fmt_usd)
    assert s == "N/A"
