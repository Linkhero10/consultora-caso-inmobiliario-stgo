#!/usr/bin/env python3
"""Genera `audit/run_manifest.json` a partir del `data/warehouse.sqlite` REAL.

## Por qué existe este script

Hasta 2026-09-23, `audit/run_manifest.json` se editaba a mano en cada ronda
de Fix 1A/1B, y quedó desactualizado dos veces seguidas: describía el
warehouse de un commit anterior mientras `main` ya llevaba varios commits
de avance (encontrado por revisión externa). El problema no era que el
warehouse estuviera corrupto -- CI seguía en verde -- sino que un tercero
que clona el repo no podía verificar que el manifiesto describe el
`data/warehouse.sqlite` que está viendo. Esto choca directamente con el
principio de trazabilidad que rige el resto del proyecto.

Este script debe ser el ÚLTIMO paso de cualquier secuencia de reconstrucción
que toque `data/warehouse.sqlite` (build_projects.py, resolve_project_review.py,
build_conflicts.py, build_geography.py, build_geography_manzana.py, ...) --
nunca antes. `tests/test_run_manifest.py::test_manifest_matches_current_warehouse`
falla en CI si el manifiesto committeado no coincide con el warehouse
committeado, para que esta desincronización no pueda volver a colarse sin
que la suite lo note.

## `parent_commit_at_generation` vs. `release_commit` (corregido 2026-09-23)

Una primera versión de este script solo escribía un campo `build_commit` con
`git rev-parse HEAD` al momento de generar el manifiesto -- pero ese HEAD es
el commit PADRE (el estado del repo antes de que este warehouse regenerado
se commitee), cuyo propio `data/warehouse.sqlite` en Git LFS puede tener un
SHA-256 distinto al que este manifiesto registra. Un revisor externo señaló
correctamente que eso deja ambiguo a qué commit describe realmente el
manifiesto. Ahora se registran dos campos separados:
`parent_commit_at_generation` (informativo, el HEAD real al generar) y
`release_commit` (el commit que efectivamente incluye este manifiesto junto
a este warehouse exacto -- necesariamente `null` al generar, porque ese
commit todavía no existe; se completa en un commit de seguimiento inmediato
que cite el hash real ya creado). Ninguno de los dos es lo que CI verifica
-- la garantía fuerte es el SHA-256 del warehouse, no el commit.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"
MANIFEST_PATH = PROJECT_ROOT / "audit" / "run_manifest.json"
BACKING_REPORT_PATH = PROJECT_ROOT / "audit" / "conflict_evidence_backing_report.json"

# Tablas cuyo conteo se registra si existen -- el manifiesto no asume un
# esquema fijo, porque distintas fases agregan tablas nuevas (Fase C agrego
# manzana_censal, por ejemplo).
TRACKED_TABLES = [
    "document", "project", "conflict", "conflict_case", "conflict_project",
    "document_conflict", "conflict_relation", "conflict_evidence_backing",
    "actor_registry", "actor_alias", "actor_event_project_link",
    "manzana_censal", "geocoded_location", "geocoded_location_conflict",
    "case_mention_duplicate_link",
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


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (name,)
    ).fetchone() is not None


def generate(warehouse_path: Path = WAREHOUSE_PATH, manifest_path: Path = MANIFEST_PATH) -> dict[str, Any]:
    if not warehouse_path.exists():
        raise FileNotFoundError(warehouse_path)

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
            # Fix 1D (2026-09-24): mas de un detector coexiste en la misma
            # tabla (ver backing_rows_by_detector en el reporte) -- el campo
            # singular "detector_version" queda como el mas antiguo/original
            # por compatibilidad, pero "all" es la lista real vigente.
            "detector_version": backing_report.get("detector_version"),
            "all_detector_versions": backing_report.get("detector_versions", [backing_report.get("detector_version")]),
            "generated_from_warehouse_sha256": backing_report.get("warehouse_sha256"),
            "report_path": "audit/conflict_evidence_backing_report.json",
        }

    manifest = {
        "schema_version": "2.0",
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
        "tests": {
            "path": "tests/",
            "ci_workflow": ".github/workflows/tests.yml",
            "note": "El conteo exacto de tests cambia con cada commit -- ver el ultimo run de la pestana Actions del repositorio para el resultado vigente, no hardcodear aqui.",
        },
        # Dos campos de commit distintos y deliberadamente separados
        # (hallazgo real de revision externa, 2026-09-23): "parent_commit_at_generation"
        # es el HEAD real en el momento en que este script corrio (el commit
        # SOBRE el que se reconstruyo el warehouse, ya en el repo) -- puede
        # tener un objeto LFS de warehouse.sqlite DISTINTO al sha256 de
        # arriba, precisamente porque este manifiesto describe un warehouse
        # regenerado que todavia no esta committeado en ese momento. No usar
        # este campo para verificar que sha256 corresponde a un commit dado.
        # "release_commit" es el commit que efectivamente incluye ESTE
        # archivo de manifiesto junto a este data/warehouse.sqlite exacto --
        # no puede conocerse antes de crear el commit (no existe todavia), asi
        # que queda null hasta un commit de seguimiento inmediato que lo
        # complete citando el hash real ya creado (mismo patron ya usado en
        # el commit 23339cc). El SHA-256 del warehouse es la unica garantia
        # fuerte; ambos campos de commit son informativos, no verificados por CI.
        "parent_commit_at_generation": _git_head(),
        "release_commit": None,
        "note": (
            "Este manifiesto se regenera con src/generate_run_manifest.py contra el warehouse "
            "vigente en cada ronda de reconstruccion -- nunca se edita a mano. "
            "tests/test_run_manifest.py verifica en CI que el SHA-256 aqui registrado coincide "
            "exactamente con data/warehouse.sqlite tal como esta committeado -- esa es la "
            "garantia fuerte, no los campos de commit (ver comentario junto a parent_commit_at_generation "
            "y release_commit en src/generate_run_manifest.py)."
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    manifest = generate()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
