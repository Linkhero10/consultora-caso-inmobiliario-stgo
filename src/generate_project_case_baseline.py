#!/usr/bin/env python3
"""Regenera config/project_case_baseline.json justo despues de build_projects.py.

El baseline fija que cada project_id parte como su propio case_id y ata el mapeo a la huella de CONTENIDO
(proyectos y menciones) del warehouse recien construido, no a los bytes del archivo. Solo debe correrse cuando cambia el conjunto de project_id (por
ejemplo, tras corregir la normalizacion de nombres); nunca despues de resolve_project_review.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from warehouse_digest import project_source_content_sha256  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
BASELINE = PROJECT_ROOT / "config" / "project_case_baseline.json"


def build_baseline(warehouse: Path, description: str) -> dict:
    conn = sqlite3.connect(f"file:{warehouse}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(project)")}
        if "case_id" in columns:
            raise SystemExit("project.case_id ya existe: el warehouse es posterior a resolve_project_review.py")
        ids = sorted(row[0] for row in conn.execute("SELECT project_id FROM project"))
        source_content_sha256 = project_source_content_sha256(conn)
    finally:
        conn.close()
    rows = [{"project_id": pid, "case_id": pid} for pid in ids]
    mapping_bytes = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "project_case_baseline",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_content_sha256": source_content_sha256,
        "description": description,
        "project_id_set_sha256": hashlib.sha256(("\n".join(ids) + "\n").encode("utf-8")).hexdigest(),
        "mapping_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
        "projects": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--description", required=True)
    args = parser.parse_args()
    payload = build_baseline(WAREHOUSE, args.description)
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "projects"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
