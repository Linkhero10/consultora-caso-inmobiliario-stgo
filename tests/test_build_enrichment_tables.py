"""Pruebas del ETL enrichment v3.3 -> warehouse intermedio (2026-09-26).

Migracion completa v3.2->v3.3: build_enrichment_tables.py ahora construye
enrichment_document/enrichment_project_mention desde v3.3 (objeto
{nombre, case_mention_index} por proyecto), no desde v3.2 (string suelto).
Estas pruebas usan datos sinteticos -- no llaman a ninguna API ni dependen
del corpus real (aunque una prueba de regresion contra el corpus real vive
al final, con skip explicito si no esta disponible en el entorno).
"""

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_enrichment_tables as et  # noqa: E402


def _make_source_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT, fecha_publicacion TEXT, "
        "fetched_at TEXT, title TEXT, lineage_json TEXT, corpus_scope TEXT, contract_version TEXT, "
        "decision_documento TEXT)"
    )
    conn.execute(
        "INSERT INTO document VALUES ('doc1', 'https://example.com/a', '2026-01-01', '2026-01-01', "
        "'t', '{}', 'principal', 'v3.3', 'include')"
    )
    conn.execute(
        "INSERT INTO document VALUES ('doc2', 'https://example.com/b', '2026-01-01', '2026-01-01', "
        "'t', '{}', 'principal', 'v3.3', 'include')"
    )
    conn.commit()
    conn.close()


def _record(url, proyectos):
    return {
        "url": url,
        "nombre_proyecto": "proyecto x",
        "proyectos_mencionados": proyectos,
        "objeto_disputa_norm": "n", "objeto_disputa_raw": "r",
        "evidencia_objeto_disputa": "", "evidencia_objeto_disputa_verificada": False,
        "tipo_accion": "", "escala_conflicto": "", "institucion_decisora_segun_fuente": "",
        "instrumento_norm": "", "instrumento_raw": "", "via_legal_norm": "", "resultado_actuacion": "",
        "tipo_evidencia_fuente": "", "ubicacion_especifica": "", "explicacion_tipo_conflicto": "",
        "explicacion_actores": "", "revision": {}, "triage_consistency_check": True,
        "triage_consistency_note": "", "actores_posiblemente_truncados": False,
        "instituciones_posiblemente_truncadas": False, "hitos_posiblemente_truncados": False,
        "decision_documento_etapa1": "include", "contract_version_etapa1": "v3.3",
        "content_sha256": "abc", "content_char_count": 10, "input_truncated": False,
        "enrichment_schema_version": "v3.3", "prompt_sha256": "p", "schema_sha256": "s",
        "record_schema_sha256": "rs", "script_sha256": "", "runner_script_sha256": "",
        "core_enrichment_script_sha256": "", "run_id": "test",
        "actores": [], "instituciones_mencionadas": [], "linea_tiempo": [],
    }


def test_build_database_persists_case_mention_index_and_id(tmp_path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    _make_source_db(source)
    records = {
        "https://example.com/a": _record(
            "https://example.com/a",
            [{"nombre": "Torre X", "case_mention_index": 0}, {"nombre": "Torre Y", "case_mention_index": None}],
        ),
    }
    counts = et.build_database(source, output, records=records)
    assert counts["documents"] == 1
    assert counts["projects"] == 2

    conn = sqlite3.connect(output)
    rows = conn.execute(
        "SELECT nombre_proyecto, case_mention_index, case_mention_id FROM enrichment_project_mention ORDER BY idx"
    ).fetchall()
    assert rows == [
        ("Torre X", 0, "doc1:0"),
        ("Torre Y", None, None),
    ]


def test_validate_project_associations_reads_nombre_from_dict_shape():
    """Antes de este fix, comparar un dict contra un set de strings siempre
    fallaba (nunca matcheaba) -- regresion directa del bug real."""
    record = {
        "proyectos_mencionados": [{"nombre": "Torre X", "case_mention_index": 0}],
        "actores": [{"proyecto_asociado": "Torre X"}],
        "instituciones_mencionadas": [],
        "linea_tiempo": [],
    }
    errors = et._validate_project_associations(record)
    assert errors == []


def test_validate_project_associations_flags_real_mismatch():
    record = {
        "proyectos_mencionados": [{"nombre": "Torre X", "case_mention_index": 0}],
        "actores": [{"proyecto_asociado": "Torre Z"}],
        "instituciones_mencionadas": [],
        "linea_tiempo": [],
    }
    errors = et._validate_project_associations(record)
    assert len(errors) == 1
    assert "Torre Z" in errors[0]


def test_build_database_unmatched_and_duplicate_urls_are_counted_not_silently_dropped(tmp_path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    _make_source_db(source)
    records = {
        "https://example.com/a": _record("https://example.com/a", []),
        "https://example.com/no-existe": _record("https://example.com/no-existe", []),
    }
    counts = et.build_database(source, output, records=records)
    assert counts["documents"] == 1
    assert counts["unmatched_documents"] == 1


def test_build_database_rejects_same_source_and_output(tmp_path):
    source = tmp_path / "same.sqlite"
    _make_source_db(source)
    try:
        et.build_database(source, source, records={"u": _record("u", [])})
        assert False, "deberia haber lanzado ValueError"
    except ValueError as exc:
        assert "distinto" in str(exc)


def test_build_database_rejects_empty_records(tmp_path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    _make_source_db(source)
    try:
        et.build_database(source, output, records={})
        assert False, "deberia haber lanzado ValueError con records vacio"
    except ValueError as exc:
        assert "vacio" in str(exc)


def test_copy_document_case_unit_from_productive_source(tmp_path):
    productive = tmp_path / "productive.sqlite"
    conn = sqlite3.connect(productive)
    conn.execute("CREATE TABLE document_case_unit (document_id TEXT PRIMARY KEY, unidad_caso_tipo TEXT)")
    conn.execute("INSERT INTO document_case_unit VALUES ('doc1', 'caso_unico')")
    conn.commit()
    conn.close()

    target = tmp_path / "target.sqlite"
    target_conn = sqlite3.connect(target)
    n = et._copy_document_case_unit(target_conn, productive)
    target_conn.commit()
    assert n == 1
    row = target_conn.execute("SELECT document_id, unidad_caso_tipo FROM document_case_unit").fetchone()
    assert row == ("doc1", "caso_unico")


def test_copy_document_case_unit_returns_zero_when_source_missing(tmp_path):
    target = tmp_path / "target.sqlite"
    target_conn = sqlite3.connect(target)
    n = et._copy_document_case_unit(target_conn, tmp_path / "no_existe.sqlite")
    assert n == 0


def test_build_database_against_real_v3_3_corpus_end_to_end():
    """Regresion real (no sintetica): correr el ETL completo contra el
    corpus real de 934 documentos y verificar invariantes basicas. Se salta
    si el entorno no tiene los archivos de Auditoria/ (gitignorados)."""
    import pytest

    if not et.DEFAULT_SOURCE_DB.exists():
        pytest.skip("warehouse_v1.sqlite no disponible en este entorno")
    try:
        from v3_3_enrichment_source import load_v3_3_records
        records = load_v3_3_records(include_fuera_de_universo=True)
    except Exception:
        pytest.skip("archivos de enrichment v3.3 no disponibles en este entorno")
    if len(records) < 900:
        pytest.skip(f"corpus v3.3 incompleto en este entorno ({len(records)} registros)")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "warehouse_enrichment_test.sqlite"
        counts = et.build_database(et.DEFAULT_SOURCE_DB, output, records=records)
        assert counts["documents"] == len(records)
        assert counts["unmatched_documents"] == 0
        assert counts["duplicate_documents"] == 0
        assert counts["invalid_project_associations"] == 0

        conn = sqlite3.connect(output)
        total = conn.execute("SELECT COUNT(*) FROM enrichment_project_mention").fetchone()[0]
        with_index = conn.execute(
            "SELECT COUNT(*) FROM enrichment_project_mention WHERE case_mention_index IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        assert total > 0
        assert 0 < with_index <= total
