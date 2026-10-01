"""Version de la release: una sola fuente (`pyproject.toml`), copiada a cada artefacto que la necesita.

La version vive en tres lugares que deben coincidir: `pyproject.toml` (fuente), `audit/run_manifest.json`
(`release_version`) y la tabla `release_metadata` de `data/warehouse.sqlite`. `tests/test_release_metadata.py`
lo verifica. Ningun otro archivo del repositorio debe nombrar versiones internas ni rondas de correccion
(`tests/test_release_hygiene.py`).
"""

from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


def release_version() -> str:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]["version"]


def write_release_metadata(conn: sqlite3.Connection) -> None:
    """Crea `release_metadata(key, value)` con la version de la release. Es determinista (sin fechas): dos
    construcciones con los mismos datos producen el mismo contenido."""
    conn.execute("DROP TABLE IF EXISTS release_metadata")
    conn.execute("CREATE TABLE release_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO release_metadata (key, value) VALUES ('release_version', ?)", (release_version(),))
