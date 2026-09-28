#!/usr/bin/env python3
"""Simulate PROJECT identity adjudications without changing the source warehouse.

The resolver runs against an in-memory SQLite backup. The only optional write
is a JSON audit report under ``audit/``; the input database is opened read-only
and its SHA-256 is checked again before the report is emitted.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import build_conflicts
import resolve_project_review

DEFAULT_OUTPUT = ROOT / "audit" / "project_identity_resolution_simulation_2026-09-28.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri_path = quote(path.resolve().as_posix(), safe="/:")
    return sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)


def atomic_write_json(path: Path, payload: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def unresolved_queue_rows(conn: sqlite3.Connection) -> list[dict]:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(project_review_queue)")}
    optional = {
        name: (name if name in columns else f"NULL AS {name}")
        for name in ("decision", "decision_reason", "decision_source", "decision_provenance_ref")
    }
    rows = conn.execute(
        "SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b, "
        f"{optional['decision']}, {optional['decision_reason']}, {optional['decision_source']}, "
        f"{optional['decision_provenance_ref']} FROM project_review_queue "
        "WHERE COALESCE(resolved, 0) = 0 OR decision = 'needs_human_review' ORDER BY rowid"
    )
    return [
        {
            "queue_rowid": row[0],
            "project_id_a": row[1],
            "project_name_a": row[2],
            "project_id_b": row[3],
            "project_name_b": row[4],
            "decision": row[5],
            "decision_reason": row[6],
            "decision_source": row[7],
            "decision_provenance_ref": row[8],
        }
        for row in rows
    ]


def all_queue_rows(conn: sqlite3.Connection) -> list[dict]:
    return [
        {
            "queue_rowid": row[0],
            "project_id_a": row[1],
            "project_name_a": row[2],
            "project_id_b": row[3],
            "project_name_b": row[4],
            "resolved": bool(row[5]),
            "decision": row[6],
            "decision_reason": row[7],
            "decision_source": row[8],
        }
        for row in conn.execute(
            "SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b, "
            "resolved, decision, decision_reason, decision_source "
            "FROM project_review_queue ORDER BY rowid"
        )
    ]


def queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "total": conn.execute("SELECT COUNT(*) FROM project_review_queue").fetchone()[0],
        "merged": conn.execute(
            "SELECT COUNT(*) FROM project_review_queue WHERE decision = 'merged'"
        ).fetchone()[0],
        "kept_separate": conn.execute(
            "SELECT COUNT(*) FROM project_review_queue WHERE decision = 'kept_separate'"
        ).fetchone()[0],
        "needs_human_review": len(unresolved_queue_rows(conn)),
    }


def source_hashes(args: argparse.Namespace) -> dict[str, str | None]:
    paths = {
        "warehouse_sha256": args.warehouse,
        "classified_63_sha256": args.classified_63,
        "resolver_sha256": ROOT / "src" / "resolve_project_review.py",
        "conflict_builder_sha256": ROOT / "src" / "build_conflicts.py",
        "simulation_script_sha256": Path(__file__).resolve(),
        "base_identity_adjudications_sha256": ROOT / "audit" / "identity_followup_2026-09-27" / "identity_adjudications_v1.json",
        "base_identity_bundle_sha256": ROOT / "audit" / "identity_followup_2026-09-26" / "identity_review_bundle.json",
        "historical_pair_adjudications_sha256": ROOT / "audit" / "historical_project_pair_adjudications_v1.json",
        "identity_overrides_sha256": ROOT / "audit" / "project_identity_adjudication_overrides_2026-09-28_v2.json",
        "historical_resolutions_sha256": ROOT / "config" / "historical_case_id_resolutions_v1.json",
    }
    manifest = args.evidence_root.parent / "fulltext_manifest.jsonl"
    paths["fulltext_manifest_sha256"] = manifest if manifest.is_file() else None
    return {
        name: sha256_file(path) if path is not None and path.is_file() else None
        for name, path in paths.items()
    }


def simulate(args: argparse.Namespace) -> dict:
    for label, path in (
        ("warehouse", args.warehouse),
        ("classified_63", args.classified_63),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    if not args.evidence_root.is_dir():
        raise FileNotFoundError(f"fulltext evidence root does not exist: {args.evidence_root}")
    output = args.output.resolve()
    if output == args.warehouse.resolve() or ROOT / "data" in output.parents:
        raise ValueError("simulation output cannot overwrite the warehouse or any file under data/")

    input_warehouse_sha = sha256_file(args.warehouse)
    input_hashes = source_hashes(args)
    source = connect_readonly(args.warehouse)
    memory = sqlite3.connect(":memory:")
    try:
        source.backup(memory)
    finally:
        source.close()
    memory.execute("PRAGMA foreign_keys = ON")

    queue_rows_before = all_queue_rows(memory)
    queue_before = [row for row in queue_rows_before if not row["resolved"] or row["decision"] == "needs_human_review"]
    counts_before = queue_counts(memory)
    adjudications = resolve_project_review.load_effective_project_identity_adjudications()
    identity_evidence = resolve_project_review.validate_project_identity_adjudication_evidence(
        adjudications, ROOT, content_root=args.evidence_root
    )
    resolver_output = io.StringIO()
    with contextlib.redirect_stdout(resolver_output):
        resolver_status = resolve_project_review._resolve_database(
            memory, evidence_content_root=args.evidence_root
        )
    if resolver_status != 0:
        raise RuntimeError(f"resolver simulation returned status {resolver_status}")
    resolver_summary = json.loads(resolver_output.getvalue())
    resolver_summary = {
        key: resolver_summary[key]
        for key in (
            "n_pairs_reviewed", "decisions", "n_projects_before", "n_cases_after_merge",
            "n_projects_merged_away", "project_relations", "n_homonym_partition_vetoes",
        )
    }
    queue_after = unresolved_queue_rows(memory)
    queue_rows_after = {row["queue_rowid"]: row for row in all_queue_rows(memory)}
    counts_after = queue_counts(memory)
    unresolved_by_rowid = {row["queue_rowid"]: row for row in queue_after}
    changed_open_pairs = []
    for original in queue_before:
        rowid = original["queue_rowid"]
        current = memory.execute(
            "SELECT resolved, decision, decision_reason, decision_source, decision_provenance_ref "
            "FROM project_review_queue WHERE rowid = ?",
            (rowid,),
        ).fetchone()
        changed_open_pairs.append(
            {
                **original,
                "final_resolved": bool(current[0]),
                "final_decision": current[1],
                "final_decision_reason": current[2],
                "final_decision_source": current[3],
                "final_decision_provenance_ref": current[4],
                "still_open": rowid in unresolved_by_rowid,
            }
        )

    preexisting_decisions_changed = []
    final_decisions_for_previously_closed = []
    for original in queue_rows_before:
        if not original["resolved"]:
            continue
        final = queue_rows_after[original["queue_rowid"]]
        if original["decision"] != final["decision"] or original["resolved"] != final["resolved"]:
            final_decisions_for_previously_closed.append({
                **original,
                "final_resolved": final["resolved"],
                "final_decision": final["decision"],
                "final_decision_reason": final["decision_reason"],
                "final_decision_source": final["decision_source"],
            })
    preexisting_decisions_changed = final_decisions_for_previously_closed

    build_conflicts.CLASSIFIED_63 = args.classified_63
    documents = build_conflicts.load_classified_63()
    all_case_ids = {
        row[0]
        for row in memory.execute("SELECT DISTINCT case_id FROM project WHERE case_id IS NOT NULL")
    }
    aliases, non_resolvable = build_conflicts.load_historical_case_id_resolutions(
        build_conflicts.HISTORICAL_CASE_ID_RESOLUTIONS_PATH
    )
    alias_table_exists = memory.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_id_alias'"
    ).fetchone()
    case_id_alias = (
        dict(memory.execute("SELECT old_case_id, canonical_case_id FROM case_id_alias"))
        if alias_table_exists
        else {case_id: case_id for case_id in all_case_ids}
    )
    case_id_alias.update(aliases)
    historical_analysis = build_conflicts.analyze_historical_case_references(
        documents, all_case_ids, case_id_alias, non_resolvable
    )
    project_blockers = build_conflicts.load_unresolved_project_identity_blockers(memory)
    combined_blockers = [*historical_analysis["topology_blockers"], *project_blockers]
    preflight = build_conflicts.build_historical_case_preflight_report(
        {**historical_analysis, "topology_blockers": combined_blockers},
        classified_path=args.classified_63,
        warehouse_path=args.warehouse,
    )
    preflight["n_confirmed_non_resolvable_historical_references"] = len(non_resolvable)
    preflight["historical_reference_gate"] = {
        "status": "blocked" if historical_analysis["topology_blockers"] else "clear",
        "n_topology_blockers": len(historical_analysis["topology_blockers"]),
        "topology_blockers": historical_analysis["topology_blockers"],
    }
    preflight["n_project_identity_blockers"] = len(project_blockers)
    preflight["project_identity_review_gate"] = {
        "status": "blocked" if project_blockers else "clear",
        "policy": "cada par PROJECT sin decision final bloquea la reconstruccion integral de CONFLICT",
        "n_unresolved_pairs": len(project_blockers),
        "unresolved_pairs": project_blockers,
    }

    integrity = memory.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_violations = memory.execute("PRAGMA foreign_key_check").fetchall()
    output_counts = {
        "projects": memory.execute("SELECT COUNT(*) FROM project").fetchone()[0],
        "case_ids": len(all_case_ids),
    }
    current_preflight_path = ROOT / "audit" / "historical_case_reference_preflight.json"
    current_preflight = json.loads(current_preflight_path.read_text(encoding="utf-8")) if current_preflight_path.is_file() else {}
    old_preflight_sha = (current_preflight.get("source_hashes") or {}).get("warehouse_file_sha256")
    source_warehouse_sha_after = sha256_file(args.warehouse)
    if source_warehouse_sha_after != input_warehouse_sha:
        raise RuntimeError("source warehouse SHA changed during memory-only simulation")

    return {
        "schema_version": "project_identity_resolution_simulation_v1",
        "run_id": datetime.now(timezone.utc).isoformat(),
        "simulation_only": True,
        "production_promoted": False,
        "source_warehouse_mutated": False,
        "source_hashes": input_hashes,
        "source_warehouse_sha256_after": source_warehouse_sha_after,
        "initial_open_project_pairs": counts_before["needs_human_review"],
        "project_identity_review": {
            "queue_counts_before": counts_before,
            "queue_counts_after": counts_after,
            "resolver_summary": resolver_summary,
            "identity_evidence_validation": identity_evidence,
            "previously_open_pairs_and_simulated_decisions": changed_open_pairs,
            "previously_closed_pairs_reclassified": preexisting_decisions_changed,
            "still_unresolved_pairs": queue_after,
        },
        "historical_case_preflight_after_simulated_project_resolution": preflight,
        "preexisting_historical_preflight_artifact": {
            "path": "audit/historical_case_reference_preflight.json",
            "recorded_warehouse_sha256": old_preflight_sha,
            "current_source_warehouse_sha256": input_warehouse_sha,
            "stale_for_current_snapshot": bool(old_preflight_sha and old_preflight_sha != input_warehouse_sha),
            "use_as_current_release_evidence": False,
        },
        "simulation_integrity": {
            "sqlite_integrity_check": integrity,
            "foreign_key_violations": len(foreign_key_violations),
            "project_count_after_resolution": output_counts["projects"],
            "case_id_count_after_resolution": output_counts["case_ids"],
            "full_conflict_rebuild_executed": False,
            "dashboard_or_manifest_published": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warehouse", type=Path, default=ROOT / "data" / "warehouse.sqlite")
    parser.add_argument("--evidence-root", type=Path, required=True, help="directorio Fuentes/fulltext/content")
    parser.add_argument("--classified-63", type=Path, required=True, help="paquete CLASSIFIED_63 usado por el preflight")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true", help="imprime JSON sin crear el reporte")
    args = parser.parse_args()
    payload = simulate(args)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.stdout:
        print(rendered, end="")
    else:
        atomic_write_json(args.output, payload)
        print(json.dumps({
            "output": str(args.output.resolve()),
            "report_sha256": sha256_file(args.output),
            "initial_open_pairs": payload["initial_open_project_pairs"],
            "final_unresolved_project_pairs": payload["project_identity_review"]["queue_counts_after"]["needs_human_review"],
            "historical_topology_blockers": payload["historical_case_preflight_after_simulated_project_resolution"]["historical_reference_gate"]["n_topology_blockers"],
            "project_topology_blockers": payload["project_identity_review"]["queue_counts_after"]["needs_human_review"],
            "publication_status": payload["historical_case_preflight_after_simulated_project_resolution"]["status"],
            "source_warehouse_sha256": payload["source_warehouse_sha256_after"],
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
