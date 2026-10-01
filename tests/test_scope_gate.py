"""La etapa de alcance aplica decisiones versionadas (sin API) y deja un universo conservador verificable."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import scope_gate as sg  # noqa: E402
import scope_jev as sj  # noqa: E402


def _warehouse():
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE conflict (conflict_id TEXT PRIMARY KEY, label TEXT, respaldo_evidencia TEXT);
        CREATE TABLE document_conflict (document_id TEXT, conflict_id TEXT, role TEXT);
        INSERT INTO conflict VALUES ('a','Torre A','respaldo_exact_quote_detectado'), ('b','Bar B','respaldo_exact_quote_detectado'),
                                    ('c','Torre C','sin_respaldo_exact_quote_detectado'), ('d','Nuevo D','respaldo_exact_quote_detectado');
        INSERT INTO document_conflict VALUES ('d1','a','focal'), ('d2','b','focal'), ('d3','c','focal'), ('d4','d','focal');
        """
    )
    return c


def _entry(conflict_id, label, docs, disputa=0.9, tema="inmobiliario_urbano", foco="principal"):
    return {"conflict_id": conflict_id, "signature": sj.unit_signature(label, docs), "disputa": disputa, "tema": tema, "foco": foco}


def test_gate_approves_rejects_and_marks_unevaluated():
    conn = _warehouse()
    decisions = {
        "a": _entry("a", "Torre A", [("d1", "focal")]),
        "b": _entry("b", "Bar B", [("d2", "focal")], tema="consumo_comercio_servicios"),
        "c": _entry("c", "Torre C", [("d3", "focal")]),
        "d": _entry("d", "Nuevo D", [("OTRO", "focal")]),  # firma que ya no coincide
    }
    counts = sg.build(conn, decisions)
    assert counts == {"aprobado": 2, "rechazado": 1, "sin_evaluar": 1}
    rows = dict(conn.execute("SELECT conflict_id, alcance FROM conflict_scope"))
    assert rows == {"a": "aprobado", "b": "rechazado", "c": "aprobado", "d": "sin_evaluar"}
    assert conn.execute("SELECT motivos FROM conflict_scope WHERE conflict_id='b'").fetchone()[0] == "tema:consumo_comercio_servicios"


def test_conservative_view_requires_both_backing_and_approved_scope():
    conn = _warehouse()
    sg.build(conn, {"a": _entry("a", "Torre A", [("d1", "focal")]), "c": _entry("c", "Torre C", [("d3", "focal")])})
    assert [r[0] for r in conn.execute("SELECT conflict_id FROM conflict_conservative")] == ["a"]


def test_signature_ignores_document_order_and_changes_with_grouping():
    assert sj.unit_signature("x", [("d2", "focal"), ("d1", "focal")]) == sj.unit_signature("x", [("d1", "focal"), ("d2", "focal")])
    assert sj.unit_signature("x", [("d1", "focal")]) != sj.unit_signature("x", [("d1", "contextual_mention")])


def test_decisions_file_validation(tmp_path):
    path = tmp_path / "d.json"
    base = {"schema_version": "conflict_scope_decisions", "decisions": [{"conflict_id": "a", "signature": "s", "disputa": 0.5, "tema": "t", "foco": "f"}]}
    path.write_text(json.dumps(base), encoding="utf-8")
    assert "a" in sg.load_decisions(path)
    for bad in ({**base, "schema_version": "otro"}, {**base, "decisions": base["decisions"] * 2},
                {**base, "decisions": [{**base["decisions"][0], "disputa": 1.5}]}):
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            sg.load_decisions(path)
    assert sg.load_decisions(tmp_path / "no_existe.json") == {}


def test_real_decisions_cover_the_published_conflicts():
    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists() or warehouse.stat().st_size < 10_000:
        pytest.skip("warehouse no disponible")
    conn = sqlite3.connect(warehouse)
    ids = {r[0] for r in conn.execute("SELECT conflict_id FROM conflict")}
    unevaluated = conn.execute("SELECT COUNT(*) FROM conflict_scope WHERE alcance = 'sin_evaluar'").fetchone()[0]
    assert {r[0] for r in conn.execute("SELECT conflict_id FROM conflict_scope")} == ids
    assert unevaluated == 0, "hay conflictos sin decision de alcance vigente: corre scope_jev.py --classify-conflicts"
