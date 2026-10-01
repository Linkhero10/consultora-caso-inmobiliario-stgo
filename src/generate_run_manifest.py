#!/usr/bin/env python3
"""Genera `audit/run_manifest.json` a partir del `data/warehouse.sqlite` REAL.

Un manifiesto escrito a mano se desactualiza sin que nada lo note (CI sigue en verde mientras describe el warehouse
de un commit anterior). Este script lo genera SIEMPRE desde el warehouse vigente y debe ser el ULTIMO paso de toda
reconstruccion que toque `data/warehouse.sqlite` (`src/rebuild.py` lo garantiza).
`tests/test_run_manifest.py` falla si el SHA-256 registrado no coincide con el archivo versionado: esa es la garantia
fuerte de que el manifiesto describe el warehouse que se esta viendo.

`parent_commit_at_generation` (HEAD al generar) y `release_commit` (el commit que publico estos artefactos; se completa
en un commit de seguimiento para evitar una referencia autorreferencial) son informativos: ninguno lo verifica CI.
La version de la release (`release_version`) sale de `pyproject.toml`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from historical_case_publication_gate import require_conflict_publication_ready
from release_info import release_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"
MANIFEST_PATH = PROJECT_ROOT / "audit" / "run_manifest.json"
BACKING_REPORT_PATH = PROJECT_ROOT / "audit" / "conflict_evidence_backing_report.json"
HISTORICAL_CASE_PREFLIGHT_PATH = PROJECT_ROOT / "audit" / "historical_case_reference_preflight.json"
CONFLICT_AUDIT_REPORT_PATH = BACKING_REPORT_PATH
CONFLICT_UNIT_REVIEW_PATH = PROJECT_ROOT / "config" / "conflict_unit_review.json"
CONFLICT_BUILDER_PATH = PROJECT_ROOT / "src" / "build_conflicts.py"

# Tablas cuyo conteo se registra si existen -- el manifiesto no asume un
# esquema fijo, porque distintas fases agregan tablas nuevas (Fase C agrego
# manzana_censal, por ejemplo).
TRACKED_TABLES = [
    "conflict_scope",
    "document", "project", "conflict", "conflict_case", "conflict_project",
    "document_conflict", "conflict_relation", "conflict_evidence_backing",
    "actor_registry", "actor_alias", "actor_event_project_link",
    "manzana_censal", "geocoded_location", "geocoded_location_conflict",
    "case_mention_duplicate_link", "project_mention_geography", "project_relation",
]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    except Exception:
        return None


def _validate_release_commit(release_commit: str | None) -> str | None:
    if release_commit is None:
        return None
    candidate = release_commit.lower()
    if len(candidate) != 40 or any(char not in "0123456789abcdef" for char in candidate):
        raise ValueError("release_commit debe ser un SHA-1 completo de 40 caracteres hexadecimales")
    try:
        subprocess.check_output(
            ["git", "cat-file", "-e", f"{candidate}^{{commit}}"],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        raise ValueError(f"release_commit no existe como commit en este repositorio: {release_commit}") from exc
    return candidate


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone() is not None


def generate(
    warehouse_path: Path = WAREHOUSE_PATH,
    manifest_path: Path = MANIFEST_PATH,
    release_commit: str | None = None,
    enforce_publication_gate: bool = True,
) -> dict[str, Any]:
    if not warehouse_path.exists():
        raise FileNotFoundError(warehouse_path)
    release_commit = _validate_release_commit(release_commit)
    publication_gate = None
    if enforce_publication_gate:
        publication_gate = require_conflict_publication_ready(
            warehouse_path,
            HISTORICAL_CASE_PREFLIGHT_PATH,
            CONFLICT_AUDIT_REPORT_PATH,
            CONFLICT_UNIT_REVIEW_PATH,
            CONFLICT_BUILDER_PATH,
        )

    con = sqlite3.connect(str(warehouse_path))
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_issues = len(con.execute("PRAGMA foreign_key_check").fetchall())
        counts = {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TRACKED_TABLES
            if _table_exists(con, table)
        }
    finally:
        con.close()

    detector_versions: dict[str, Any] = {}
    if BACKING_REPORT_PATH.exists():
        backing_report = json.loads(BACKING_REPORT_PATH.read_text(encoding="utf-8"))
        detector_versions["conflict_evidence_backing"] = {
            "detector_version": backing_report.get("detector_version"),
            "all_detector_versions": backing_report.get("detector_versions", [backing_report.get("detector_version")]),
            "generated_from_warehouse_sha256": backing_report.get("warehouse_sha256"),
            "report_path": "audit/conflict_evidence_backing_report.json",
        }

    manifest = {
        "schema_version": "2.0",
        "release_version": release_version(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generator": "src/generate_run_manifest.py",
        "warehouse": {
            "path": "data/warehouse.sqlite",
            "sha256": _sha256_file(warehouse_path),
            "integrity_check": integrity,
            "foreign_key_check_violations": fk_issues,
            "counts": counts,
        },
        "detector_versions": detector_versions,
        "conflict_publication_gate": publication_gate,
        "tests": {
            "path": "tests/",
            "ci_workflow": ".github/workflows/tests.yml",
            "note": "El conteo exacto de tests cambia con cada commit -- ver el ultimo run de la pestana Actions del repositorio para el resultado vigente, no hardcodear aqui.",
        },
        # Informativos (ver docstring del modulo); la garantia fuerte es el SHA-256 del warehouse.
        "parent_commit_at_generation": _git_head(),
        "release_commit": release_commit,
        "note": (
            "Manifiesto generado por src/generate_run_manifest.py contra el warehouse vigente; nunca se edita a mano. "
            "tests/test_run_manifest.py verifica en CI que el SHA-256 registrado coincide con data/warehouse.sqlite."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera audit/run_manifest.json desde el warehouse actual.")
    parser.add_argument(
        "--release-commit",
        help="SHA completo del commit que publico los artefactos; usar en el commit de seguimiento.",
    )
    args = parser.parse_args()
    manifest = generate(release_commit=args.release_commit)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
