"""La version de la release vive en pyproject.toml y debe coincidir en el manifiesto y en el warehouse."""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import release_info  # noqa: E402


def test_version_is_a_three_part_release():
    assert re.fullmatch(r"\d+\.\d+\.\d+", release_info.release_version())


def test_manifest_and_warehouse_carry_the_same_version():
    manifest = json.loads((PROJECT_ROOT / "audit" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_version"] == release_info.release_version()
    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists() or warehouse.stat().st_size < 10_000:
        pytest.skip("warehouse no disponible")
    conn = sqlite3.connect(warehouse)
    assert conn.execute("SELECT value FROM release_metadata WHERE key='release_version'").fetchone()[0] == release_info.release_version()


def test_release_metadata_is_deterministic():
    a, b = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    release_info.write_release_metadata(a)
    release_info.write_release_metadata(b)
    assert a.execute("SELECT * FROM release_metadata").fetchall() == b.execute("SELECT * FROM release_metadata").fetchall()
