"""Test the PNJ JSON parser that extracts SJC gold prices."""
import json
from pathlib import Path
import pytest
from backend.scrapers.sjc import _parse_pnj_json

FIXTURE = Path(__file__).parent / "fixtures" / "pnj_sample.json"


def _payload(gia_mua: str, gia_ban: str, name: str = "SJC") -> dict:
    """Minimal response matching PNJ's shape: locations → gold_type → price strings."""
    return {
        "locations": [
            {"name": "TPHCM", "gold_type": [
                {"name": name, "gia_mua": gia_mua, "gia_ban": gia_ban},
            ]},
        ]
    }


def test_parse_real_fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    buy, sell = _parse_pnj_json(data)
    # Prices should be in a plausible VND-per-tael range (50M–300M VND)
    assert 50_000_000 < buy < 300_000_000, f"buy out of range: {buy}"
    assert 50_000_000 < sell < 300_000_000, f"sell out of range: {sell}"
    assert buy <= sell, "buy price should not exceed sell price"


def test_parse_synthetic():
    """PNJ quotes nghìn/lượng, so "144.000" means 144,000,000 VND per tael."""
    buy, sell = _parse_pnj_json(_payload("144.000", "147.500"))
    assert buy == 144_000_000   # 144.000 × 1000
    assert sell == 147_500_000  # 147.500 × 1000


def test_parse_skips_other_gold_types():
    """Only the SJC entry counts — other products are quoted at different prices."""
    data = {
        "locations": [
            {"name": "TPHCM", "gold_type": [
                {"name": "Nhẫn Trơn PNJ 999.9", "gia_mua": "120.000", "gia_ban": "123.000"},
                {"name": "SJC", "gia_mua": "144.000", "gia_ban": "147.500"},
            ]},
        ]
    }
    buy, sell = _parse_pnj_json(data)
    assert buy == 144_000_000
    assert sell == 147_500_000


def test_parse_missing_sjc_entry_raises():
    with pytest.raises(ValueError, match="SJC gold_type not found"):
        _parse_pnj_json(_payload("120.000", "123.000", name="Nhẫn Trơn PNJ 999.9"))


def test_parse_empty_response_raises():
    with pytest.raises(ValueError, match="SJC gold_type not found"):
        _parse_pnj_json({})


def test_parse_out_of_range_raises():
    """Guards against a unit change on PNJ's side silently producing absurd prices."""
    with pytest.raises(ValueError, match="out of expected range"):
        _parse_pnj_json(_payload("144", "147"))  # missing the nghìn scaling
