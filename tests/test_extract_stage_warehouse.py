"""El warehouse de etapa se puede reconstruir desde el publicado, sin el corpus ni gasto en LLM."""

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import extract_stage_warehouse as ex  # noqa: E402


def _synthetic_published(path):
    conn = sqlite3.connect(path)
    for table in ex.BASE_TABLES + ex.ENRICHMENT_TABLES:
        conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, valor TEXT)")
        conn.execute(f"INSERT INTO {table} VALUES ('1', ?)", (table,))
    conn.execute("CREATE VIEW v_actor AS SELECT id FROM entity")
    conn.execute("CREATE VIEW v_institution AS SELECT id FROM entity")
    conn.execute("CREATE TABLE project (project_id TEXT)")  # derivada: no debe pasar a la etapa
    conn.execute("INSERT INTO project VALUES ('p')")
    conn.commit()
    conn.close()


def test_stage_warehouse_contains_only_the_stage_objects(tmp_path):
    published = tmp_path / "published.sqlite"
    _synthetic_published(published)
    out = tmp_path / "base.sqlite"
    counts = ex.extract(published, out, "base")
    assert set(counts) == set(ex.BASE_TABLES)
    conn = sqlite3.connect(out)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert names == set(ex.BASE_TABLES) | set(ex.BASE_VIEWS)
    assert "project" not in names and "enrichment_document" not in names

    enrichment = tmp_path / "enrichment.sqlite"
    ex.extract(published, enrichment, "enrichment")
    conn = sqlite3.connect(enrichment)
    assert {"enrichment_document", "document_case_unit"} <= {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}


def test_extract_refuses_to_overwrite_the_published_warehouse_and_reports_missing_objects(tmp_path):
    published = tmp_path / "published.sqlite"
    _synthetic_published(published)
    with pytest.raises(ValueError, match="distinto"):
        ex.extract(published, published, "base")
    incomplete = tmp_path / "incomplete.sqlite"
    sqlite3.connect(incomplete).execute("CREATE TABLE document (id TEXT)").connection.commit()
    with pytest.raises(ValueError, match="no contiene"):
        ex.extract(incomplete, tmp_path / "out.sqlite", "base")


def test_real_stage_warehouse_matches_the_intermediate_base_when_available(tmp_path):
    from paths import BASE_WAREHOUSE_PATH
    published = ex.PUBLISHED_WAREHOUSE
    if not published.exists() or not BASE_WAREHOUSE_PATH.exists():
        pytest.skip("warehouse publicado o base intermedio no disponible en este entorno")
    out = tmp_path / "base.sqlite"
    ex.extract(published, out, "base")
    a, b = sqlite3.connect(out), sqlite3.connect(BASE_WAREHOUSE_PATH)
    for table in ex.BASE_TABLES:
        rows_a = sorted(map(repr, a.execute(f"SELECT * FROM {table}")))
        rows_b = sorted(map(repr, b.execute(f"SELECT * FROM {table}")))
        assert rows_a == rows_b, table
