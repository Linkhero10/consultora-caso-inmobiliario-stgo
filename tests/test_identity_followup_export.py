import hashlib
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from export_identity_followup import build_bundle  # noqa: E402


def test_bundle_exports_open_pair_sources_without_promoting_a_decision():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE project (
            project_id TEXT PRIMARY KEY, canonical_name TEXT, case_id TEXT,
            homonym_partition TEXT, n_documents INTEGER, n_mentions INTEGER
        );
        CREATE TABLE project_review_queue (
            project_id_a TEXT, canonical_name_a TEXT, project_id_b TEXT,
            canonical_name_b TEXT, reason TEXT, resolved INTEGER,
            decision TEXT, decision_reason TEXT
        );
        CREATE TABLE document (document_id TEXT PRIMARY KEY, title TEXT, url TEXT);
        CREATE TABLE project_mention_resolved (
            document_id TEXT, raw_nombre_proyecto TEXT, project_id TEXT
        );
        CREATE TABLE enrichment_project_mention (
            document_id TEXT, nombre_proyecto TEXT, case_mention_id TEXT
        );
        CREATE TABLE case_mention (
            case_mention_id TEXT PRIMARY KEY, decision_final_amplio TEXT, comuna TEXT
        );
        CREATE TABLE project_relation_type (
            relation_type TEXT PRIMARY KEY, label_es TEXT, description TEXT
        );
        CREATE TABLE project_relation (
            relation_id TEXT PRIMARY KEY, subject_project_id TEXT, relation_type TEXT,
            object_project_id TEXT, evidence_url TEXT, source_title TEXT,
            source_locator TEXT, evidence_quote TEXT, source_accessed_at TEXT,
            source_sha256 TEXT, verification_status TEXT
        );
        INSERT INTO project VALUES ('a','Proyecto A','case-a',NULL,1,1);
        INSERT INTO project VALUES ('b','Proyecto B','case-b',NULL,1,1);
        INSERT INTO project_review_queue VALUES ('a','Proyecto A','b','Proyecto B',
          'substring_match_not_auto_merged',0,'needs_human_review','falta fuente individual');
        INSERT INTO document VALUES ('doc-1','Nota de prueba','https://example.org/nota');
        INSERT INTO project_mention_resolved VALUES ('doc-1','Proyecto A','a');
        INSERT INTO project_mention_resolved VALUES ('doc-1','Proyecto B','b');
        INSERT INTO document VALUES ('doc-2','Nota 2','https://example.org/2');
        INSERT INTO document VALUES ('doc-3','Nota 3','https://example.org/3');
        INSERT INTO document VALUES ('doc-4','Nota 4','https://example.org/4');
        INSERT INTO document VALUES ('doc-5','Nota 5','https://example.org/5');
        INSERT INTO document VALUES ('doc-6','Nota 6','https://example.org/6');
        INSERT INTO project_mention_resolved VALUES ('doc-2','Proyecto A','a');
        INSERT INTO project_mention_resolved VALUES ('doc-3','Proyecto A','a');
        INSERT INTO project_mention_resolved VALUES ('doc-4','Proyecto A','a');
        INSERT INTO project_mention_resolved VALUES ('doc-5','Proyecto A','a');
        INSERT INTO project_mention_resolved VALUES ('doc-6','Proyecto A','a');
        INSERT INTO enrichment_project_mention VALUES ('doc-1','Proyecto A','cm-a');
        INSERT INTO enrichment_project_mention VALUES ('doc-1','Proyecto B',NULL);
        INSERT INTO case_mention VALUES ('cm-a','include','Cerrillos');
        """
    )

    bundle = build_bundle(conn, warehouse_sha256="a" * 64, repository_head="b" * 40)
    pair = bundle["unresolved_pairs"][0]

    assert bundle["release_boundary"]["production_queue_rows_changed"] is False
    assert bundle["release_boundary"]["pair_decisions_promoted_by_this_export"] == 0
    assert pair["same_case_id_currently"] is False
    assert pair["shared_source_documents_count"] == 1
    assert pair["project_a"]["n_source_documents"] == 6
    assert len(pair["project_a"]["source_examples"]) == 6
    assert pair["project_a"]["source_examples"][0]["linked_case_mention_id"] == "cm-a"
    assert pair["project_b"]["source_examples"][0]["linked_case_mention_id"] is None
    assert "no se infiere por coexistencia documental" in pair["project_a"]["source_examples"][0]["link_note"]
    conn.close()


def test_migration_drift_dossier_reconciles_the_69_labeled_adjudications():
    package = PROJECT_ROOT / "audit" / "identity_followup_2026-09-26"
    original = json.loads((package / "migration_review_original.json").read_text(encoding="utf-8"))
    drift = json.loads((package / "migration_drift_cases.json").read_text(encoding="utf-8"))

    labeled = []
    for group in ("focal_priority_89", "nonfocal_frozen_30"):
        for document in original["drift_review"][group]:
            labeled.extend(
                (document["document_id"], document["url"], row["version"], row["name"])
                for row in document["adjudications"]
                if row.get("classification") == "omisión respaldada"
            )

    assert len(labeled) == 69
    assert sum(row[2] == "v3.3" for row in labeled) == 65
    assert sum(row[2] == "v3.2" for row in labeled) == 4

    reconstructed = {
        (row["document_id"], row["url"], "v3.2", row["v3_2_project_mention"])
        for row in drift["cases"]
    }
    source_side = {row for row in labeled if row[2] == "v3.2"}
    assert reconstructed == source_side


def test_review_package_manifest_pins_every_deliverable():
    package = PROJECT_ROOT / "audit" / "identity_followup_2026-09-26"
    manifest = json.loads((package / "package_manifest.json").read_text(encoding="utf-8"))

    for name, expected in manifest["contents"].items():
        artifact = package / name
        assert artifact.stat().st_size == expected["bytes"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected["sha256"]

    assert manifest["counts"]["open_project_pairs"] == 68
    assert manifest["counts"]["migration_drift_rows_to_review"] == 69
