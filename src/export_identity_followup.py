"""Exporta la cola abierta de identidad con referencias a sus fuentes originales."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
OUTPUT = PROJECT_ROOT / "audit" / "identity_followup_2026-09-26" / "identity_review_bundle.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    except Exception:
        return None


def _project_sources(conn: sqlite3.Connection, project_id: str) -> dict[str, Any]:
    project = conn.execute(
        """SELECT project_id, canonical_name, case_id, homonym_partition,
                  n_documents, n_mentions
           FROM project WHERE project_id=?""",
        (project_id,),
    ).fetchone()
    if project is None:
        raise ValueError(f"project_id ausente del warehouse: {project_id}")
    n_sources = conn.execute(
        "SELECT COUNT(DISTINCT document_id) FROM project_mention_resolved WHERE project_id=?",
        (project_id,),
    ).fetchone()[0]
    sources = conn.execute(
        """SELECT DISTINCT d.document_id, d.title, d.url, pm.raw_nombre_proyecto,
                  ep.case_mention_id, cm.decision_final_amplio, cm.comuna
           FROM project_mention_resolved pm
           JOIN document d ON d.document_id=pm.document_id
           LEFT JOIN enrichment_project_mention ep
             ON ep.document_id=pm.document_id AND ep.nombre_proyecto=pm.raw_nombre_proyecto
           LEFT JOIN case_mention cm ON cm.case_mention_id=ep.case_mention_id
           WHERE pm.project_id=?
           ORDER BY d.document_id, pm.raw_nombre_proyecto""",
        (project_id,),
    ).fetchall()
    return {
        "project_id": project[0],
        "canonical_name": project[1],
        "case_id": project[2],
        "homonym_partition": project[3],
        "n_documents_in_project_registry": project[4],
        "n_mentions_in_project_registry": project[5],
        "n_source_documents": n_sources,
        "source_examples": [
            {
                "document_id": row[0],
                "title": row[1],
                "url": row[2],
                "raw_project_mention": row[3],
                "linked_case_mention_id": row[4],
                "linked_case_decision": row[5],
                "linked_case_comuna": row[6],
                "link_note": (
                    "El vínculo case_mention_id solo se informa cuando está almacenado "
                    "explícitamente; no se infiere por coexistencia documental."
                ),
            }
            for row in sources
        ],
    }


def build_bundle(
    conn: sqlite3.Connection,
    *,
    warehouse_sha256: str,
    repository_head: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    open_rows = conn.execute(
        """SELECT project_id_a, canonical_name_a, project_id_b, canonical_name_b,
                  reason, decision, decision_reason
           FROM project_review_queue WHERE resolved=0
           ORDER BY canonical_name_a, canonical_name_b, project_id_a, project_id_b"""
    ).fetchall()
    pairs = []
    for row in open_rows:
        a_id, a_name, b_id, b_name, reason, decision, decision_reason = row
        shared = conn.execute(
            """SELECT DISTINCT d.document_id, d.title, d.url
               FROM project_mention_resolved a
               JOIN project_mention_resolved b ON b.document_id=a.document_id
               JOIN document d ON d.document_id=a.document_id
               WHERE a.project_id=? AND b.project_id=?
               ORDER BY d.document_id""",
            (a_id, b_id),
        ).fetchall()
        shared_count = conn.execute(
            """SELECT COUNT(DISTINCT a.document_id)
               FROM project_mention_resolved a
               JOIN project_mention_resolved b ON b.document_id=a.document_id
               WHERE a.project_id=? AND b.project_id=?""",
            (a_id, b_id),
        ).fetchone()[0]
        side_a = _project_sources(conn, a_id)
        side_b = _project_sources(conn, b_id)
        pair_key = "::".join(sorted((a_id, b_id)))
        pairs.append(
            {
                "pair_id": hashlib.sha256(pair_key.encode("utf-8")).hexdigest()[:20],
                "project_a": side_a,
                "project_b": side_b,
                "queue_reason": reason,
                "queue_decision": decision,
                "queue_decision_reason": decision_reason,
                "same_case_id_currently": side_a["case_id"] == side_b["case_id"],
                "shared_source_documents": [
                    {"document_id": item[0], "title": item[1], "url": item[2]}
                    for item in shared
                ],
                "shared_source_documents_count": shared_count,
                "adjudication_status": "pending_source_level_review",
            }
        )

    relation_rows = conn.execute(
        """SELECT r.relation_id, r.subject_project_id, ps.canonical_name,
                  r.relation_type, rt.label_es, r.object_project_id, po.canonical_name,
                  r.evidence_url, r.source_title, r.source_locator, r.evidence_quote,
                  r.source_accessed_at, r.source_sha256, r.verification_status,
                  ps.case_id, po.case_id
           FROM project_relation r
           JOIN project_relation_type rt ON rt.relation_type=r.relation_type
           JOIN project ps ON ps.project_id=r.subject_project_id
           JOIN project po ON po.project_id=r.object_project_id
           ORDER BY r.subject_project_id, r.relation_type, r.object_project_id"""
    ).fetchall()
    return {
        "artifact_id": "project_identity_followup_2026-09-26",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "repository_head": repository_head,
        "warehouse_sha256": warehouse_sha256,
        "scope": "Follow-up to the v3.2-to-v3.3 project identity migration review.",
        "release_boundary": {
            "production_queue_rows_changed": False,
            "unresolved_pair_count": len(pairs),
            "pair_decisions_promoted_by_this_export": 0,
        },
        "review_protocol": [
            "Inspect each pair independently; do not infer identity from name similarity or a shared case_id.",
            "Use the source URLs attached to each project_id and record the exact evidence for both sides.",
            "Distinguish same identity from component, phase, plan/instrument, distinct entity, and unresolved.",
            "Check territory, time, developer, project stage, and homonym contradictions before recommending a merge.",
            "This export is a review aid; it does not change project_review_queue or production case_id values.",
        ],
        "project_relations_current": [
            {
                "relation_id": row[0],
                "subject_project_id": row[1],
                "subject_name": row[2],
                "relation_type": row[3],
                "relation_label": row[4],
                "object_project_id": row[5],
                "object_name": row[6],
                "evidence_url": row[7],
                "source_title": row[8],
                "source_locator": row[9],
                "evidence_quote": row[10],
                "source_accessed_at": row[11],
                "source_sha256": row[12],
                "verification_status": row[13],
                "subject_case_id": row[14],
                "object_case_id": row[15],
                "identity_merged": row[14] == row[15],
            }
            for row in relation_rows
        ],
        "unresolved_pairs": pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta un paquete auditado de parejas de proyecto abiertas.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if not WAREHOUSE.exists():
        raise FileNotFoundError(WAREHOUSE)
    conn = sqlite3.connect(f"file:{WAREHOUSE.as_posix()}?mode=ro", uri=True)
    try:
        bundle = build_bundle(conn, warehouse_sha256=_sha256(WAREHOUSE), repository_head=_repo_head())
    finally:
        conn.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(args.output), "pairs": len(bundle["unresolved_pairs"]), "warehouse_sha256": bundle["warehouse_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
