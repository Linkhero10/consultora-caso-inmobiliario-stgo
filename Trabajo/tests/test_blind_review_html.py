from pathlib import Path


HTML = Path(__file__).parents[2] / "Productos" / "revision_humana_blind_v5_2_1_50.html"


def test_blind_review_html_has_file_safe_storage_and_zero_fp_rule():
    text = HTML.read_text(encoding="utf-8")
    assert "faro_storage_fallback" in text
    assert "0 falsos positivos" in text
    assert "Estrato" in text

