"""Regresión del vínculo tipado proyecto ↔ instrumento de planificación."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_project_relations import _validate_config, rebuild_project_relations  # noqa: E402


def test_city_parque_has_a_plan_relation_without_identity_merge():
    config = json.loads((PROJECT_ROOT / "config" / "project_relations.json").read_text(encoding="utf-8"))
    relation = next(
        item for item in config["relations"]
        if item["subject_project_id"] == "3ce6d0d030381374a3c026f7"
        and item["object_project_id"] == "7805069a696198e3d8e2b964"
    )
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE project (project_id TEXT PRIMARY KEY, case_id TEXT NOT NULL)")
    for pid in {relation["subject_project_id"], relation["object_project_id"]}:
        conn.execute("INSERT INTO project VALUES (?, ?)", (pid, f"case:{pid}"))

    rebuild_project_relations(conn, config_path=PROJECT_ROOT / "config" / "project_relations.json")

    row = conn.execute(
        """SELECT subject_project_id, relation_type, object_project_id,
                  evidence_url, source_locator, evidence_quote
           FROM project_relation"""
    ).fetchone()
    assert row[:3] == (
        "3ce6d0d030381374a3c026f7",
        "has_plan",
        "7805069a696198e3d8e2b964",
    )
    assert row[3] == relation["evidence_url"]
    assert row[4] == relation["source_locator"]
    assert row[5] == relation["evidence_quote"]
    assert conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(DISTINCT case_id) FROM project"
    ).fetchone()[0] == 2
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_relation_builder_rejects_missing_project_ids():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE project (project_id TEXT PRIMARY KEY, case_id TEXT NOT NULL)")
    with pytest.raises(ValueError, match="project_id"):
        rebuild_project_relations(conn, config_path=PROJECT_ROOT / "config" / "project_relations.json")


def test_relation_builder_rejects_quotes_over_25_words():
    config = {
        "schema_version": "1.0",
        "relation_types": [{"relation_type": "has_plan", "label_es": "tiene plan", "description": "x"}],
        "relations": [{
            "subject_project_id": "a", "object_project_id": "b", "relation_type": "has_plan",
            "evidence_url": "https://example.org/source", "source_title": "Fuente", "source_locator": "p. 1",
            "evidence_quote": "palabra " * 26, "source_accessed_at": "2026-09-26"
        }]
    }
    with pytest.raises(ValueError, match="25 palabras"):
        _validate_config(config)


def test_current_warehouse_keeps_city_and_plan_as_distinct_related_entities():
    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "project_relation" in tables
    row = conn.execute(
        """SELECT r.relation_type, r.subject_project_id, r.object_project_id,
                  p1.case_id, p2.case_id, r.verification_status
           FROM project_relation r
           JOIN project p1 ON p1.project_id = r.subject_project_id
           JOIN project p2 ON p2.project_id = r.object_project_id
           WHERE r.subject_project_id = ? AND r.object_project_id = ?""",
        ("3ce6d0d030381374a3c026f7", "7805069a696198e3d8e2b964"),
    ).fetchone()
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    assert row is not None
    assert row[0] == "has_plan"
    assert row[3] != row[4]
    assert row[5] == "source_verified"
    assert fk_errors == []
