"""Fail-closed gate for public artifacts derived from CONFLICT.

The conflict builder records a successful, source-pinned topology fingerprint
only after its database transaction and audit report have completed. Dashboard
and release-manifest generation must match that fingerprint before publishing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


TOPOLOGY_TABLES = (
    "project",
    "conflict",
    "conflict_case",
    "conflict_project",
    "document_conflict",
    "conflict_relation",
    "historical_case_reference",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def conflict_topology_fingerprint(conn: sqlite3.Connection) -> str:
    """Hash all rows/columns in the tables that define published conflict topology."""
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    missing = sorted(set(TOPOLOGY_TABLES) - existing)
    if missing:
        raise ValueError(f"faltan tablas requeridas para la topología CONFLICT: {missing}")

    snapshot: dict[str, Any] = {}
    for table in TOPOLOGY_TABLES:
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        rows = [list(row) for row in conn.execute(f'SELECT * FROM "{table}"')]
        serialized_rows = sorted(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str)
            for row in rows
        )
        snapshot[table] = {"columns": columns, "rows": serialized_rows}
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_conflict_publication_ready(
    warehouse_path: Path,
    preflight_report_path: Path,
    conflict_audit_report_path: Path,
    classified_path: Path,
    conflict_builder_path: Path,
) -> dict[str, Any]:
    """Refuse public output unless a completed build still matches its inputs/topology."""
    if not Path(preflight_report_path).is_file():
        raise RuntimeError(f"gate de publicación bloqueado: falta reporte preflight: {preflight_report_path}")
    try:
        report = json.loads(Path(preflight_report_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("gate de publicación bloqueado: reporte preflight ilegible") from exc

    if report.get("status") != "conflict_build_completed":
        raise RuntimeError(
            "gate de publicación bloqueado: se requiere un build CONFLICT completo y exitoso; "
            f"status={report.get('status')!r}"
        )
    if report.get("n_topology_blockers") != 0:
        raise RuntimeError("gate de publicación bloqueado: el reporte conserva bloqueos topológicos")

    for path, label in (
        (conflict_audit_report_path, "reporte de build CONFLICT"),
        (classified_path, "CLASSIFIED_63"),
        (conflict_builder_path, "script build_conflicts.py"),
        (warehouse_path, "warehouse"),
    ):
        if not Path(path).is_file():
            raise RuntimeError(f"gate de publicación bloqueado: falta {label}: {path}")

    source_hashes = report.get("source_hashes") or {}
    if source_hashes.get("classified_63_sha256") != _sha256_file(Path(classified_path)):
        raise RuntimeError("gate de publicación bloqueado: cambió el hash de CLASSIFIED_63")
    if source_hashes.get("preflight_script_sha256") != _sha256_file(Path(conflict_builder_path)):
        raise RuntimeError("gate de publicación bloqueado: cambió el hash de build_conflicts.py")
    expected_audit_sha256 = report.get("completed_audit_report_sha256")
    if not expected_audit_sha256 or expected_audit_sha256 != _sha256_file(Path(conflict_audit_report_path)):
        raise RuntimeError("gate de publicación bloqueado: el reporte de build CONFLICT no coincide")

    try:
        conn = sqlite3.connect(f"file:{Path(warehouse_path).resolve().as_posix()}?mode=ro", uri=True)
        try:
            current_topology_sha256 = conflict_topology_fingerprint(conn)
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as exc:
        raise RuntimeError(f"gate de publicación bloqueado: {exc}") from exc

    if report.get("completed_conflict_topology_sha256") != current_topology_sha256:
        raise RuntimeError(
            "gate de publicación bloqueado: el fingerprint de la topología vigente no coincide "
            "con el build CONFLICT completado"
        )
    return {
        "status": "ready",
        "preflight_status": report["status"],
        "topology_sha256": current_topology_sha256,
        "preflight_report": str(preflight_report_path),
    }
