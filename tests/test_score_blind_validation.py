import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import score_blind_validation as sbv  # noqa: E402


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE conflict (conflict_id TEXT, respaldo_evidencia TEXT)")
    c.execute("CREATE TABLE document_conflict (conflict_id TEXT)")
    c.executemany("INSERT INTO conflict VALUES (?,?)", [("a", "respaldo_exact_quote_detectado"), ("b", "sin_respaldo_exact_quote_detectado"), ("c", "sin_respaldo_exact_quote_detectado")])
    c.execute("INSERT INTO document_conflict VALUES ('a')")
    return c


def _v(cid, muestra, veredicto, resp="no"):
    return {"conflict_id": cid, "muestra": muestra, "veredicto": veredicto, "categoria": None if veredicto == "correcto" else "otro", "respaldo_correcto": resp}


def test_score_splits_by_system_backing_and_keeps_stress_apart():
    out = sbv.score([_v("a", "main", "correcto", "si"), _v("b", "main", "error_grave"), _v("c", "stress", "no_verificable", "no_evaluable")], _conn())
    assert out["muestra_aleatoria"]["con_respaldo_del_sistema"]["correcto"] == 1
    assert out["muestra_aleatoria"]["sin_respaldo_del_sistema"]["error_grave"] == 1
    assert out["muestra_dirigida_sin_respaldo"]["n"] == 1 and out["muestra_dirigida_sin_respaldo"]["error_grave_pct"] is None
    assert out["conflictos_sin_documentos"] == 2
    assert out["acuerdo_respaldo"]["sistema_con_respaldo|si"] == 1


def test_wilson_interval_and_unknown_conflict():
    assert sbv.wilson(0, 0) is None
    low, high = sbv.wilson(5, 10)
    assert low < 0.5 < high
    with pytest.raises(ValueError):
        sbv.score([_v("zzz", "main", "correcto")], _conn())
