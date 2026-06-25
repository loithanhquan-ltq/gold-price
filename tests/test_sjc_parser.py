"""Test the DOJI HTML parser that extracts SJC gold prices."""
from pathlib import Path
import pytest
from backend.scrapers.sjc import _parse_doji_html

FIXTURE = Path(__file__).parent / "fixtures" / "doji_sample.html"


def test_parse_real_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    buy, sell = _parse_doji_html(html)
    # Prices should be in a plausible VND-per-tael range (50M–300M VND)
    assert 50_000_000 < buy < 300_000_000, f"buy out of range: {buy}"
    assert 50_000_000 < sell < 300_000_000, f"sell out of range: {sell}"
    assert buy <= sell, "buy price should not exceed sell price"


def test_parse_synthetic():
    """Minimal HTML that matches the expected DOJI table structure."""
    html = """
    <html><body><table>
      <tr><th>Loại</th><th>Mua vào</th><th>Bán ra</th></tr>
      <tr><td>SJC - Bán Lẻ</td><td>14300</td><td>14600</td></tr>
    </table></body></html>
    """
    buy, sell = _parse_doji_html(html)
    assert buy == 143_000_000   # 14300 × 10000
    assert sell == 146_000_000  # 14600 × 10000


def test_parse_missing_sjc_row_raises():
    html = """
    <html><body><table>
      <tr><th>Loại</th><th>Mua vào</th><th>Bán ra</th></tr>
      <tr><td>NHẪN TRÒN 9999</td><td>13700</td><td>14200</td></tr>
    </table></body></html>
    """
    with pytest.raises(ValueError, match="SJC row not found"):
        _parse_doji_html(html)


def test_parse_empty_html_raises():
    with pytest.raises((ValueError, Exception)):
        _parse_doji_html("<html><body></body></html>")
