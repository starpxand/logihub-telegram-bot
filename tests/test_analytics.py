from pathlib import Path

from logihub_bot.analytics import Analytics

CSV = Path(__file__).resolve().parents[1] / "data" / "logistics_orders.csv"


def test_summary_contains_kpis():
    text = Analytics(CSV).summary("Q")
    assert "OTIF" in text and "Выручка" in text and "квартал" in text


def test_chart_is_png():
    assert Analytics(CSV).otif_chart("M")[:8] == b"\x89PNG\r\n\x1a\n"


def test_last_period_bounds():
    a = Analytics(CSV)
    year = a.last_period("Y")
    assert year["order_date"].dt.year.nunique() == 1
