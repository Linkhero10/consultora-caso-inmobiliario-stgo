"""Guardia de trazabilidad: `audit/run_manifest.json` nunca debe quedar
desactualizado respecto de `data/warehouse.sqlite` (hallazgo real de
revisión externa, 2026-09-23 -- el manifiesto llevaba dos rondas de commits
de atraso mientras CI seguia en verde, porque nada verificaba la
correspondencia). Este test corre en CI con `lfs: true` (ver
.github/workflows/tests.yml), asi que compara contra el SQLite real, no
solo contra el puntero de Git LFS."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import generate_run_manifest as manifest_generator  # noqa: E402

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"
MANIFEST_PATH = PROJECT_ROOT / "audit" / "run_manifest.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_matches_current_warehouse():
    if not WAREHOUSE_PATH.exists():
        pytest.skip("data/warehouse.sqlite no disponible")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    real_sha = _sha256_file(WAREHOUSE_PATH)
    assert manifest["warehouse"]["sha256"] == real_sha, (
        "audit/run_manifest.json esta desactualizado respecto de data/warehouse.sqlite -- "
        "correr `python src/generate_run_manifest.py` como ultimo paso antes de commitear "
        "cualquier cambio que toque el warehouse."
    )


def test_manifest_integrity_check_is_ok():
    if not WAREHOUSE_PATH.exists():
        pytest.skip("data/warehouse.sqlite no disponible")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["warehouse"]["integrity_check"] == "ok"
    assert manifest["warehouse"]["foreign_key_check_violations"] == 0


def test_manifest_counts_match_real_warehouse_where_present():
    if not WAREHOUSE_PATH.exists():
        pytest.skip("data/warehouse.sqlite no disponible")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    con = sqlite3.connect(str(WAREHOUSE_PATH))
    try:
        for table, expected in manifest["warehouse"]["counts"].items():
            real = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert real == expected, f"conteo desactualizado para {table}: manifest={expected} real={real}"
    finally:
        con.close()


def test_generate_manifest_can_finalize_release_commit_and_tracks_project_geography(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE project_mention_geography "
        "(document_id TEXT, project_mention_id TEXT, codigo_comuna_ine TEXT)"
    )
    con.execute("INSERT INTO project_mention_geography VALUES ('doc1','doc1:project:0','13114')")
    con.commit()
    con.close()

    manifest_path = tmp_path / "run_manifest.json"
    manifest = manifest_generator.generate(
        warehouse_path=db_path,
        manifest_path=manifest_path,
        release_commit=manifest_generator._git_head(),
    )

    assert manifest["release_commit"] == manifest_generator._git_head()
    assert manifest["warehouse"]["counts"]["project_mention_geography"] == 1
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["release_commit"] == manifest_generator._git_head()


def test_generate_manifest_rejects_unknown_release_commit(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    sqlite3.connect(str(db_path)).close()
    with pytest.raises(ValueError, match="no existe como commit"):
        manifest_generator.generate(
            warehouse_path=db_path,
            manifest_path=tmp_path / "run_manifest.json",
            release_commit="a" * 40,
        )
