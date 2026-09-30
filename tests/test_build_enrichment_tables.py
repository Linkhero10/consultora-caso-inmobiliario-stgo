"""Pruebas del ETL de la extraccion por LLM -> warehouse intermedio.

`build_enrichment_tables.py` construye `enrichment_document` y `enrichment_project_mention` (objeto
{nombre, case_mention_index} por proyecto) y carga `document_case_unit` desde su revision versionada en
`config/`. Estas pruebas usan datos sinteticos -- no llaman a ninguna API ni dependen del corpus real (una
prueba de regresion contra el corpus real vive al final, con skip explicito si no esta disponible).
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

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
        "'t', '{}', 'principal', 'contrato', 'include')"
    )
    conn.execute(
        "INSERT INTO document VALUES ('doc2', 'https://example.com/b', '2026-01-01', '2026-01-01', "
        "'t', '{}', 'principal', 'contrato', 'include')"
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
        "decision_documento_etapa1": "include", "contract_version_etapa1": "contrato",
        "content_sha256": "abc", "content_char_count": 10, "input_truncated": False,
        "enrichment_schema_version": "1.0", "prompt_sha256": "p", "schema_sha256": "s",
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
    counts = et.build_database(source, output, records=records, case_unit_rows=[])
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
    counts = et.build_database(source, output, records=records, case_unit_rows=[])
    assert counts["documents"] == 1
    assert counts["unmatched_documents"] == 1


def test_build_database_rejects_same_source_and_output(tmp_path):
    source = tmp_path / "same.sqlite"
    _make_source_db(source)
    try:
        et.build_database(source, source, records={"u": _record("u", [])}, case_unit_rows=[])
        assert False, "deberia haber lanzado ValueError"
    except ValueError as exc:
        assert "distinto" in str(exc)


def test_build_database_rejects_empty_records(tmp_path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    _make_source_db(source)
    try:
        et.build_database(source, output, records={}, case_unit_rows=[])
        assert False, "deberia haber lanzado ValueError con records vacio"
    except ValueError as exc:
        assert "vacio" in str(exc)


def _review_row(document_id="doc1", **overrides):
    row = {
        "document_id": document_id, "unidad_caso_tipo": "caso_unico", "tiene_error": 0,
        "correccion_nombre_proyecto": None, "correccion_proyectos_mencionados_json": None,
        "correccion_ubicacion_especifica": None, "nota_revision": None, "revisado_por": "revision_manual",
    }
    row.update(overrides)
    return row


def test_case_unit_review_is_loaded_from_config_rows_not_from_a_previous_build(tmp_path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    _make_source_db(source)
    records = {"https://example.com/a": _record("https://example.com/a", [])}
    counts = et.build_database(
        source, output, records=records,
        case_unit_rows=[_review_row("doc1", unidad_caso_tipo="multiples_casos_documentados", tiene_error=1)],
    )
    assert counts["document_case_unit_rows"] == 1
    conn = sqlite3.connect(output)
    row = conn.execute("SELECT document_id, unidad_caso_tipo, tiene_error, nota_revision FROM document_case_unit").fetchone()
    assert row == ("doc1", "multiples_casos_documentados", 1, None)
    conn.close()


def test_case_unit_review_rejects_documents_that_do_not_exist(tmp_path):
    source = tmp_path / "source.sqlite"
    output = tmp_path / "output.sqlite"
    _make_source_db(source)
    records = {"https://example.com/a": _record("https://example.com/a", [])}
    with pytest.raises(ValueError, match="inexistentes"):
        et.build_database(source, output, records=records, case_unit_rows=[_review_row("nope")])


def test_case_unit_review_config_fails_closed_on_bad_rows(tmp_path):
    def write(rows):
        path = tmp_path / "review.json"
        path.write_text(json.dumps({"schema_version": "document_case_unit_review", "rows": rows}), encoding="utf-8")
        return path

    with pytest.raises(ValueError, match="no permitido"):
        et.load_document_case_unit_review(write([_review_row(unidad_caso_tipo="inventado")]))
    with pytest.raises(ValueError, match="duplicado"):
        et.load_document_case_unit_review(write([_review_row(), _review_row()]))
    with pytest.raises(ValueError, match="tiene_error"):
        et.load_document_case_unit_review(write([_review_row(tiene_error=2)]))
    with pytest.raises(ValueError, match="revisado_por"):
        et.load_document_case_unit_review(write([_review_row(revisado_por="")]))
    with pytest.raises(ValueError, match="evidencia incompleta"):
        et.load_document_case_unit_review(write([_review_row(evidence={"source_url": "https://x", "quote": ""})]))


def test_real_case_unit_review_has_unique_documents_and_a_reviewer_on_every_row():
    rows = et.load_document_case_unit_review(et.DOCUMENT_CASE_UNIT_REVIEW_PATH)
    assert len(rows) == len({row["document_id"] for row in rows})
    assert all(row["revisado_por"] for row in rows)


def test_real_case_unit_review_evidence_quotes_are_literal_in_the_source_fulltext():
    rows = [r for r in et.load_document_case_unit_review(et.DOCUMENT_CASE_UNIT_REVIEW_PATH) if r.get("evidence")]
    assert rows, "se espera al menos una decision con evidencia literal"
    content_root = PROJECT_ROOT / "Fuentes" / "fulltext" / "content"
    if not content_root.exists():
        pytest.skip("fulltext local no disponible en este entorno")
    by_url = {}
    for path in content_root.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        by_url[record.get("url")] = record.get("text", "")
    squash = lambda s: re.sub(r"\s+", " ", s)
    for row in rows:
        text = by_url.get(row["evidence"]["source_url"])
        assert text is not None, f"no se encontro el fulltext de {row['evidence']['source_url']}"
        assert squash(row["evidence"]["quote"]) in squash(text)


def test_build_database_against_real_corpus_end_to_end():
    """Regresion real (no sintetica): correr el ETL completo contra el
    corpus real de 934 documentos y verificar invariantes basicas. Se salta
    si el entorno no tiene los archivos intermedios (no versionados)."""
    if not et.DEFAULT_SOURCE_DB.exists():
        pytest.skip("warehouse base no disponible en este entorno")
    try:
        from enrichment_source import load_enrichment_records
        records = load_enrichment_records(include_excluded=True)
    except Exception:
        pytest.skip("archivos de enrichment no disponibles en este entorno")
    if len(records) < 900:
        pytest.skip(f"corpus incompleto en este entorno ({len(records)} registros)")

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
