"""Ninguna cifra de la documentacion se escribe a mano: se genera desde el warehouse y esta prueba lo exige."""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import render_docs_stats as stats  # noqa: E402


def _synthetic_warehouse(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE document (document_id TEXT);
        CREATE TABLE enrichment_document (document_id TEXT);
        CREATE TABLE project (project_id TEXT, case_id TEXT);
        CREATE TABLE conflict (conflict_id TEXT, respaldo_evidencia TEXT);
        CREATE VIEW conflict_conservative AS SELECT * FROM conflict WHERE conflict_id = 'x1';
        CREATE TABLE project_review_queue (resolved INTEGER, decision TEXT);
        CREATE TABLE enrichment_project_mention (case_mention_index INTEGER);
        CREATE TABLE historical_case_reference (impact_scope TEXT);
        INSERT INTO document VALUES ('d1'), ('d2');
        INSERT INTO enrichment_document VALUES ('d1');
        INSERT INTO project VALUES ('p1','c1'), ('p2','c1'), ('p3','c3');
        INSERT INTO conflict VALUES ('x1','respaldo_exact_quote_detectado'), ('x2','sin_respaldo_exact_quote_detectado');
        INSERT INTO project_review_queue VALUES (1,'merged'), (1,'kept_separate'), (1,'kept_separate');
        INSERT INTO enrichment_project_mention VALUES (0), (NULL), (NULL);
        INSERT INTO historical_case_reference VALUES ('confirmed_non_resolvable_historical_reference'), ('document_conflict_membership');
        """
    )
    conn.commit()
    conn.close()


MANIFEST = {"release_version": "1.0.0", "warehouse": {"sha256": "a" * 64, "integrity_check": "ok", "foreign_key_check_violations": 0}}


def test_stats_are_computed_from_the_warehouse_not_typed_by_hand(tmp_path):
    db = tmp_path / "w.sqlite"
    _synthetic_warehouse(db)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    block = stats.rendered_block(db, manifest)
    assert "2 · 3" not in block  # 3 proyectos, 2 casos: se muestra "3 · 2 · 2"
    assert "3 · 2 · 2" in block
    assert "3 pares: 1 fusionados, 2 separados, 0 abiertos" in block
    assert "1 de 2" in block and "(1 sin respaldo detectado)" in block
    assert "| Menciones de proyecto sin vínculo a una `case_mention` | 2 |" in block
    assert "2 (1 confirmadas como no resolubles)" in block
    assert "`" + "a" * 64 + "`" in block


def test_update_text_replaces_only_the_marked_block_and_requires_markers():
    text = "antes\n" + stats.BEGIN + "\nviejo\n" + stats.END + "\ndespues"
    assert stats.update_text(text, stats.BEGIN + "\nnuevo\n" + stats.END) == "antes\n" + stats.BEGIN + "\nnuevo\n" + stats.END + "\ndespues"
    with pytest.raises(ValueError, match="marcadores"):
        stats.update_text("sin marcadores", "x")


@pytest.mark.parametrize("target", stats.TARGETS, ids=lambda p: p.name)
def test_committed_docs_match_the_real_warehouse(target):
    if not stats.WAREHOUSE_PATH.exists() or stats.WAREHOUSE_PATH.stat().st_size < 10_000:
        pytest.skip("data/warehouse.sqlite no disponible (¿falta git lfs pull?)")
    text = target.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = stats.BLOCK_RE.search(text)
    assert match, f"{target.name} no contiene el bloque de cifras"
    assert match.group(0) == stats.rendered_block(), (
        f"{target.name} tiene cifras desactualizadas respecto del warehouse: corre `python src/render_docs_stats.py`"
    )


def test_no_hand_typed_headline_numbers_outside_the_generated_block():
    """Los conteos de titulares (proyectos, conflictos, hash) viven solo en el bloque generado."""
    for target in stats.TARGETS:
        text = stats.BLOCK_RE.sub("", target.read_text(encoding="utf-8"))
        assert not re.search(r"\b\d{3}\s+(proyectos|conflictos)\b", text), (
            f"{target.name} escribe a mano un conteo de proyectos o conflictos fuera del bloque generado"
        )
        assert not re.search(r"\b[0-9a-f]{64}\b", text), f"{target.name} escribe a mano un SHA-256 fuera del bloque generado"
