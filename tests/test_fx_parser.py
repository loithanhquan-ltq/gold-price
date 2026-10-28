"""Test the EUR/VND parsers and the ER-API → jsDelivr fallback."""
import json
from pathlib import Path

import pytest

from backend.scrapers import fx

FIXTURES = Path(__file__).parent / "fixtures"


# --- ER-API ---------------------------------------------------------------

def test_parse_er_api_fixture():
    data = json.loads((FIXTURES / "er_api_sample.json").read_text(encoding="utf-8"))
    rate = fx._parse_er_api(data)
    assert fx.SANE_MIN_VND_PER_EUR < rate < fx.SANE_MAX_VND_PER_EUR


def test_parse_er_api_synthetic():
    assert fx._parse_er_api({"result": "success", "rates": {"VND": 26000.0}}) == 26000.0


def test_parse_er_api_non_success_raises():
    with pytest.raises(ValueError, match="non-success"):
        fx._parse_er_api({"result": "error", "rates": {"VND": 26000.0}})


def test_parse_er_api_missing_vnd_raises():
    with pytest.raises(ValueError, match="VND missing"):
        fx._parse_er_api({"result": "success", "rates": {}})


@pytest.mark.parametrize("rate", [10_000, 50_000, 0, -1])
def test_parse_er_api_out_of_range_raises(rate):
    with pytest.raises(ValueError, match="out of expected range"):
        fx._parse_er_api({"result": "success", "rates": {"VND": rate}})


# --- jsDelivr -------------------------------------------------------------

def test_parse_jsdelivr_fixture():
    data = json.loads((FIXTURES / "jsdelivr_eur_sample.json").read_text(encoding="utf-8"))
    rate = fx._parse_jsdelivr(data)
    assert fx.SANE_MIN_VND_PER_EUR < rate < fx.SANE_MAX_VND_PER_EUR


def test_parse_jsdelivr_synthetic():
    assert fx._parse_jsdelivr({"date": "2026-10-27", "eur": {"vnd": 26500.0}}) == 26500.0


def test_parse_jsdelivr_missing_vnd_raises():
    with pytest.raises(ValueError, match="VND missing"):
        fx._parse_jsdelivr({"date": "2026-10-27", "eur": {}})


@pytest.mark.parametrize("rate", [10_000, 50_000, 0, -1])
def test_parse_jsdelivr_out_of_range_raises(rate):
    with pytest.raises(ValueError, match="out of expected range"):
        fx._parse_jsdelivr({"eur": {"vnd": rate}})


# --- source fallback ------------------------------------------------------

def test_fetch_prefers_er_api(monkeypatch):
    expected = fx.PriceResult("EURVND", "VND", "EUR",
                              buy_price=26000.0, sell_price=26000.0)
    monkeypatch.setattr(fx, "_fetch_er_api", lambda: expected)
    monkeypatch.setattr(fx, "_fetch_jsdelivr", lambda: pytest.fail("fallback should not run"))
    assert fx.fetch_eur_vnd_rate() is expected


def test_fetch_falls_back_to_jsdelivr(monkeypatch):
    expected = fx.PriceResult("EURVND", "VND", "EUR",
                              buy_price=26500.0, sell_price=26500.0)

    def boom():
        raise RuntimeError("primary down")

    monkeypatch.setattr(fx, "_fetch_er_api", boom)
    monkeypatch.setattr(fx, "_fetch_jsdelivr", lambda: expected)
    assert fx.fetch_eur_vnd_rate() is expected


def test_fetch_both_fail_propagates(monkeypatch):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(fx, "_fetch_er_api", boom)
    monkeypatch.setattr(fx, "_fetch_jsdelivr", boom)
    with pytest.raises(RuntimeError, match="down"):
        fx.fetch_eur_vnd_rate()
