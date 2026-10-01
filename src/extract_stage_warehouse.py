#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruye los warehouses de etapa a partir del warehouse PUBLICADO.

El pipeline tiene una raiz que no se versiona: el corpus de terceros, la clasificacion por LLM y la extraccion por
LLM. Sin ellos no se puede construir la capa base desde cero, pero el warehouse publicado (`data/warehouse.sqlite`)
contiene, byte a byte en contenido, las tablas que esas etapas produjeron. Este script las copia a un warehouse de
etapa para que cualquiera pueda re-ejecutar las etapas DERIVADAS (proyectos, casos, conflictos, geografia, tablero)
sin el corpus ni gastar en LLM:

    python src/extract_stage_warehouse.py --stage enrichment
    python src/rebuild.py --from build_projects

Etapas:
- `base`: salida de la clasificacion (documentos, case_mentions, evidencia, entidades, territorio).
- `enrichment`: `base` mas la extraccion por LLM (`enrichment_*`) y la revision de unidad de caso.

Solo se copian esos objetos; nada derivado (proyectos, conflictos, geografia) pasa al warehouse de etapa.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import BASE_WAREHOUSE_PATH, ENRICHMENT_WAREHOUSE_PATH, PROJECT_ROOT  # noqa: E402

PUBLISHED_WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"

BASE_TABLES = ("document", "case_mention", "evidence", "claim", "entity", "entity_role", "event", "territory")
BASE_VIEWS = ("v_actor", "v_institution")
ENRICHMENT_TABLES = (
    "enrichment_document", "enrichment_project_mention", "enrichment_actor", "enrichment_institution",
    "enrichment_event", "enrichment_evidence", "document_case_unit",
)
STAGES = {
    "base": (BASE_TABLES, BASE_VIEWS, BASE_WAREHOUSE_PATH),
    "enrichment": (BASE_TABLES + ENRICHMENT_TABLES, BASE_VIEWS, ENRICHMENT_WAREHOUSE_PATH),
}


def extract(source: Path, output: Path, stage: str) -> dict[str, int]:
    """Copia al `output` las tablas y vistas de la etapa (esquema incluido) y devuelve las filas por tabla."""
    tables, views, _default = STAGES[stage]
    if not source.exists():
        raise FileNotFoundError(source)
    if source.resolve() == output.resolve():
        raise ValueError("output debe ser distinto del warehouse publicado")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    conn = sqlite3.connect(output)
    counts: dict[str, int] = {}
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        available = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT name, type, sql FROM src.sqlite_master")}
        missing = [name for name in tables + views if name not in available]
        if missing:
            raise ValueError(f"el warehouse publicado no contiene: {missing}")
        for name in tables:
            conn.execute(available[name][1])
            conn.execute(f"INSERT INTO main.{name} SELECT * FROM src.{name}")
            counts[name] = conn.execute(f"SELECT COUNT(*) FROM main.{name}").fetchone()[0]
        for name in views:
            conn.execute(available[name][1])
        for name, sql in conn.execute(
            "SELECT name, sql FROM src.sqlite_master WHERE type = 'index' AND sql IS NOT NULL "
            f"AND tbl_name IN ({','.join('?' for _ in tables)})", tables
        ).fetchall():
            conn.execute(sql)
        conn.commit()
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    parser.add_argument("--source", type=Path, default=PUBLISHED_WAREHOUSE)
    parser.add_argument("--output", type=Path, default=None, help="por defecto, el warehouse de etapa de intermediate/integration/")
    args = parser.parse_args()
    output = args.output or STAGES[args.stage][2]
    counts = extract(args.source, output, args.stage)
    print(f"Escrito {output}")
    for name, n in counts.items():
        print(f"  {name}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
