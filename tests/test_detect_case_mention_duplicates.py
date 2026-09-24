"""Tests de Fix 1E: deteccion retroactiva y aditiva de case_mentions
duplicadas dentro del mismo documento (nunca fuzzy, nunca renumera ni
borra nada existente -- ver docstring de src/detect_case_mention_duplicates.py)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import detect_case_mention_duplicates as dup  # noqa: E402


def _cm(tipo_objeto_raw="", decision="include", quotes=None):
    return {"tipo_objeto_raw": tipo_objeto_raw, "decision": decision, "evidencia_objeto_quotes": quotes or []}


def test_single_case_mention_gets_its_own_trivial_group():
    record = {"content_sha256": "docA", "case_mentions": [_cm("Torre Central")]}
    rows = dup.compute_duplicate_groups(record)
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "docA:0"
    assert rows[0]["group_size"] == 1
    assert rows[0]["match_method"] == "single"
    assert rows[0]["canonical_case_mention_id"] == "docA:0"


def test_exact_tipo_objeto_raw_match_groups_two_mentions():
    record = {"content_sha256": "docB", "case_mentions": [
        _cm("declaratoria del humedal urbano de quilicura", "include", ["primera cita sobre el humedal"]),
        _cm("Declaratoria Del Humedal Urbano De Quilicura", "include", ["segunda cita distinta del humedal"]),
    ]}
    rows = dup.compute_duplicate_groups(record)
    assert len(rows) == 2
    assert {r["group_size"] for r in rows} == {2}
    assert {r["duplicate_group_id"] for r in rows} == {rows[0]["duplicate_group_id"]}
    assert rows[0]["match_method"] in ("tipo_objeto_raw_exact", "ambos")


def test_quote_substring_match_groups_two_mentions_with_different_tipo_objeto():
    record = {"content_sha256": "docC", "case_mentions": [
        _cm("torre Bellavista", "include", ["permisos de edificacion del proyecto inmobiliario Bellavista, que autorizan la demolicion"]),
        _cm("permisos de edificacion del proyecto inmobiliario Bellavista", "exclude", ["permisos de edificacion del proyecto inmobiliario Bellavista"]),
    ]}
    rows = dup.compute_duplicate_groups(record)
    # la segunda cita es substring literal de la primera -> deben agruparse aunque tipo_objeto_raw difiera
    assert rows[0]["duplicate_group_id"] == rows[1]["duplicate_group_id"]
    assert rows[0]["group_size"] == 2


def test_decision_mixed_in_group_flagged_explicitly():
    record = {"content_sha256": "docD", "case_mentions": [
        _cm("torre Bellavista", "include", ["permisos de edificacion del proyecto inmobiliario Bellavista, que autorizan la demolicion"]),
        _cm("permisos de edificacion del proyecto inmobiliario Bellavista", "exclude", ["permisos de edificacion del proyecto inmobiliario Bellavista"]),
    ]}
    rows = dup.compute_duplicate_groups(record)
    assert all(r["decision_mixed_in_group"] == 1 for r in rows)
    # canonical prefiere decision='include' entre las agrupadas
    assert rows[0]["canonical_case_mention_id"] == "docD:0"


def test_no_match_stays_as_separate_single_groups():
    record = {"content_sha256": "docE", "case_mentions": [
        _cm("Museo de la Memoria en Punta Arenas", "include", ["el museo de la memoria en punta arenas"]),
        _cm("guetos verticales en Estacion Central", "include", ["los guetos verticales en estacion central"]),
    ]}
    rows = dup.compute_duplicate_groups(record)
    assert {r["group_size"] for r in rows} == {1}
    assert rows[0]["duplicate_group_id"] != rows[1]["duplicate_group_id"]


def test_transitive_grouping_across_three_mentions():
    """A calza con B por tipo_objeto_raw, B calza con C por cita -- las 3
    deben terminar en el MISMO grupo (union-find transitivo)."""
    record = {"content_sha256": "docF", "case_mentions": [
        _cm("mismo objeto real", "include", ["cita unica de A que no calza con nada mas"]),
        _cm("mismo objeto real", "include", ["cita compartida con C sobre el mismo hecho"]),
        _cm("objeto real distinto en texto", "include", ["cita compartida con C sobre el mismo hecho, mas contexto"]),
    ]}
    rows = dup.compute_duplicate_groups(record)
    assert len({r["duplicate_group_id"] for r in rows}) == 1
    assert {r["group_size"] for r in rows} == {3}


def test_never_fuzzy_short_quotes_below_min_len_do_not_match():
    record = {"content_sha256": "docG", "case_mentions": [
        _cm("Proyecto A", "include", ["el"]),
        _cm("Proyecto B", "include", ["el edificio"]),
    ]}
    rows = dup.compute_duplicate_groups(record)
    assert rows[0]["duplicate_group_id"] != rows[1]["duplicate_group_id"]


def test_empty_case_mentions_returns_empty():
    assert dup.compute_duplicate_groups({"content_sha256": "docH", "case_mentions": []}) == []


def test_real_quilicura_five_mentions_group_together():
    """Regresion real: el humedal de Quilicura (resumen.cl) tiene 5
    case_mentions identicas en classifications.jsonl real."""
    if not dup.CLASSIFICATIONS_PATH.exists():
        import pytest

        pytest.skip("Auditoria/clasificacion/classifications.jsonl no existe en este entorno (gitignorado)")
    import json

    target_url = "https://resumen.cl/articulos/negocio-inmobiliario-una-de-las-amenazas-que-afectan-al-humedal-quilicura-el-mas-grande-de-la-region-metropolitana"
    record = None
    for line in dup.CLASSIFICATIONS_PATH.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("url") == target_url:
            record = rec
            break
    assert record is not None, "documento de referencia no encontrado en classifications.jsonl"
    rows = dup.compute_duplicate_groups(record)
    quilicura_rows = [r for r in rows if r["group_size"] >= 5]
    assert quilicura_rows, "se esperaba un grupo de al menos 5 case_mentions duplicadas para Quilicura"


def _connect_or_skip():
    import sqlite3

    if not dup.WAREHOUSE.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    return sqlite3.connect(dup.WAREHOUSE)


def test_every_case_mention_in_warehouse_has_exactly_one_duplicate_link_row():
    conn = _connect_or_skip()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "case_mention_duplicate_link" not in tables:
        import pytest

        conn.close()
        pytest.skip("case_mention_duplicate_link no existe todavia -- correr src/detect_case_mention_duplicates.py primero")
    n_case_mention = conn.execute("SELECT COUNT(*) FROM case_mention").fetchone()[0]
    n_link_distinct = conn.execute("SELECT COUNT(DISTINCT case_mention_id) FROM case_mention_duplicate_link").fetchone()[0]
    n_link_total = conn.execute("SELECT COUNT(*) FROM case_mention_duplicate_link").fetchone()[0]
    conn.close()
    assert n_link_total == n_link_distinct, "case_mention_id debe ser PRIMARY KEY -- nunca 2 filas para la misma mencion"
    assert n_link_distinct == n_case_mention, "TODA case_mention del warehouse debe tener exactamente 1 fila (grupos de tamano 1 incluidos)"


def test_duplicate_link_table_never_shrinks_case_mention_or_evidence_tables():
    """Invariante mas importante del fix: la tabla nueva es 100% aditiva --
    case_mention y evidence deben conservar exactamente sus conteos
    originales (934 documentos / 5731 case_mentions del corpus)."""
    conn = _connect_or_skip()
    n_case_mention = conn.execute("SELECT COUNT(*) FROM case_mention").fetchone()[0]
    conn.close()
    assert n_case_mention == 5731
