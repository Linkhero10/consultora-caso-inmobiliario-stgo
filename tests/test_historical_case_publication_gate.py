import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_dashboard as dashboard  # noqa: E402
import historical_case_publication_gate as gate  # noqa: E402


def _warehouse(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE project (project_id TEXT, case_id TEXT);
        INSERT INTO project VALUES ('p1', 'case1');
        CREATE TABLE project_review_queue (
            project_id_a TEXT, canonical_name_a TEXT, project_id_b TEXT,
            canonical_name_b TEXT, resolved INTEGER, decision TEXT
        );
        INSERT INTO project_review_queue VALUES ('p1', 'A', 'p2', 'B', 1, 'kept_separate');
        CREATE TABLE conflict (conflict_id TEXT, label TEXT);
        INSERT INTO conflict VALUES ('conflict1', 'Caso 1');
        CREATE TABLE conflict_case (conflict_id TEXT, case_id TEXT);
        INSERT INTO conflict_case VALUES ('conflict1', 'case1');
        CREATE TABLE conflict_project (conflict_id TEXT, project_id TEXT, case_id TEXT);
        INSERT INTO conflict_project VALUES ('conflict1', 'p1', 'case1');
        CREATE TABLE document_conflict (document_id TEXT, conflict_id TEXT, role TEXT, source TEXT);
        INSERT INTO document_conflict VALUES ('doc1', 'conflict1', 'focal', 'reviewed');
        CREATE TABLE conflict_relation (conflict_id_a TEXT, conflict_id_b TEXT, relation_type TEXT, review_status TEXT, note TEXT);
        CREATE TABLE historical_case_reference (reference_id TEXT, document_id TEXT, historical_case_id TEXT, relation TEXT, project_relation TEXT, impact_scope TEXT, status TEXT);
        INSERT INTO historical_case_reference VALUES ('r1', 'doc1', 'legacy1', 'contextual', 'contextual', 'document_conflict_membership', 'preserved_unresolved_not_projected');
        """
    )
    con.commit()
    con.close()


def _write_report(path: Path, audit: Path, classified: Path, builder: Path, warehouse: Path) -> None:
    audit.write_text("conflict audit", encoding="utf-8")
    con = sqlite3.connect(warehouse)
    try:
        topology_sha = gate.conflict_topology_fingerprint(con)
    finally:
        con.close()
    report = {
        "status": "conflict_build_completed",
        "n_topology_blockers": 0,
        "source_hashes": {
            "classified_63_sha256": hashlib.sha256(classified.read_bytes()).hexdigest(),
            "preflight_script_sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
        },
        "completed_conflict_topology_sha256": topology_sha,
        "completed_audit_report_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(report), encoding="utf-8")


def test_gate_allows_only_matching_completed_build(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _warehouse(warehouse)
    classified = tmp_path / "classified.json"
    classified.write_text("{}", encoding="utf-8")
    builder = tmp_path / "build_conflicts.py"
    builder.write_text("source", encoding="utf-8")
    report = tmp_path / "preflight.json"
    audit = tmp_path / "conflict_audit.json"
    _write_report(report, audit, classified, builder, warehouse)

    result = gate.require_conflict_publication_ready(
        warehouse, report, audit, classified, builder
    )

    con = sqlite3.connect(warehouse)
    try:
        expected_topology_sha = gate.conflict_topology_fingerprint(con)
    finally:
        con.close()
    assert result["status"] == "ready"
    assert result["topology_sha256"] == expected_topology_sha


@pytest.mark.parametrize("status", ["blocked_before_database_write", "topology_preflight_passed"])
def test_gate_rejects_blocked_or_not_completed_build(tmp_path, status):
    warehouse = tmp_path / "warehouse.sqlite"
    _warehouse(warehouse)
    classified = tmp_path / "classified.json"
    classified.write_text("{}", encoding="utf-8")
    builder = tmp_path / "build_conflicts.py"
    builder.write_text("source", encoding="utf-8")
    report = tmp_path / "preflight.json"
    report.write_text(json.dumps({"status": status, "n_topology_blockers": 1}), encoding="utf-8")
    audit = tmp_path / "conflict_audit.json"

    with pytest.raises(RuntimeError, match="build CONFLICT completo"):
        gate.require_conflict_publication_ready(warehouse, report, audit, classified, builder)


def test_gate_rejects_stale_case_topology_and_source_hashes(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _warehouse(warehouse)
    classified = tmp_path / "classified.json"
    classified.write_text("{}", encoding="utf-8")
    builder = tmp_path / "build_conflicts.py"
    builder.write_text("source", encoding="utf-8")
    report = tmp_path / "preflight.json"
    audit = tmp_path / "conflict_audit.json"
    audit.write_text("conflict audit", encoding="utf-8")
    report.write_text(
        json.dumps(
            {
                "status": "conflict_build_completed",
                "n_topology_blockers": 0,
                "source_hashes": {
                    "classified_63_sha256": hashlib.sha256(classified.read_bytes()).hexdigest(),
                    "preflight_script_sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
                },
                "completed_conflict_topology_sha256": "0" * 64,
                "completed_audit_report_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    con = sqlite3.connect(warehouse)
    con.execute("UPDATE project SET case_id = 'case_changed'")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="topología vigente"):
        gate.require_conflict_publication_ready(warehouse, report, audit, classified, builder)

    _write_report(report, audit, classified, builder, warehouse)
    classified.write_text("{\"changed\": true}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="hash de CONFLICT_UNIT_REVIEW"):
        gate.require_conflict_publication_ready(warehouse, report, audit, classified, builder)


def test_gate_rejects_unresolved_project_identity_even_with_completed_report(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    _warehouse(warehouse)
    classified = tmp_path / "classified.json"
    classified.write_text("{}", encoding="utf-8")
    builder = tmp_path / "build_conflicts.py"
    builder.write_text("source", encoding="utf-8")
    report = tmp_path / "preflight.json"
    audit = tmp_path / "conflict_audit.json"
    _write_report(report, audit, classified, builder, warehouse)

    con = sqlite3.connect(warehouse)
    con.execute(
        "UPDATE project_review_queue SET resolved = 0, decision = 'needs_human_review'"
    )
    con.commit()
    con.close()

    with pytest.raises(RuntimeError, match="pares de identidad PROJECT sin resolver"):
        gate.require_conflict_publication_ready(warehouse, report, audit, classified, builder)


def test_gate_rejects_missing_required_topology_tables(tmp_path):
    warehouse = tmp_path / "warehouse.sqlite"
    sqlite3.connect(warehouse).close()
    classified = tmp_path / "classified.json"
    classified.write_text("{}", encoding="utf-8")
    builder = tmp_path / "build_conflicts.py"
    builder.write_text("source", encoding="utf-8")
    report = tmp_path / "preflight.json"
    audit = tmp_path / "conflict_audit.json"
    audit.write_text("conflict audit", encoding="utf-8")
    report.write_text(
        json.dumps(
            {
                "status": "conflict_build_completed",
                "n_topology_blockers": 0,
                "source_hashes": {
                    "classified_63_sha256": hashlib.sha256(classified.read_bytes()).hexdigest(),
                    "preflight_script_sha256": hashlib.sha256(builder.read_bytes()).hexdigest(),
                },
                "completed_conflict_topology_sha256": "0" * 64,
                "completed_audit_report_sha256": hashlib.sha256(audit.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="project_review_queue"):
        gate.require_conflict_publication_ready(warehouse, report, audit, classified, builder)


def test_dashboard_does_not_overwrite_existing_artifact_when_gate_blocks(tmp_path, monkeypatch):
    output = tmp_path / "index.html"
    output.write_text("published-old-version", encoding="utf-8")
    monkeypatch.setattr(dashboard, "OUTPUT_PATH", output)
    monkeypatch.setattr(
        dashboard,
        "require_conflict_publication_ready",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("gate bloqueado")),
    )
    monkeypatch.setattr(dashboard, "build_dashboard_dataset", lambda: pytest.fail("no debe construir dataset"))

    with pytest.raises(RuntimeError, match="gate bloqueado"):
        dashboard.main()

    assert output.read_text(encoding="utf-8") == "published-old-version"
