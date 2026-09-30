#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escribe en README.md y START_HERE.md el bloque de cifras del producto, calculado desde el warehouse real.

Las cifras escritas a mano en la documentacion se desactualizaron en cada ronda (conteos viejos junto a un warehouse
nuevo, y nadie lo notaba). Aqui no hay ninguna cifra a mano: el bloque entre `<!-- stats:begin -->` y
`<!-- stats:end -->` se genera SIEMPRE desde `data/warehouse.sqlite` y `audit/run_manifest.json`, y
`tests/test_docs_stats_in_sync.py` falla si el archivo versionado difiere de lo que este script produciria.

    python src/render_docs_stats.py          # actualiza los archivos
    python src/render_docs_stats.py --check  # solo verifica (codigo 1 si estan desactualizados)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"
MANIFEST_PATH = PROJECT_ROOT / "audit" / "run_manifest.json"
TARGETS = (PROJECT_ROOT / "README.md", PROJECT_ROOT / "START_HERE.md")
BEGIN, END = "<!-- stats:begin -->", "<!-- stats:end -->"
BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def collect(conn: sqlite3.Connection) -> dict:
    one = lambda sql: conn.execute(sql).fetchone()[0]
    queue = dict(conn.execute("SELECT decision, COUNT(*) FROM project_review_queue GROUP BY decision").fetchall())
    return {
        "documents": one("SELECT COUNT(*) FROM document"),
        "documents_extracted": one("SELECT COUNT(*) FROM enrichment_document"),
        "projects": one("SELECT COUNT(*) FROM project"),
        "cases": one("SELECT COUNT(DISTINCT case_id) FROM project"),
        "conflicts": one("SELECT COUNT(*) FROM conflict"),
        "conflicts_backed": one("SELECT COUNT(*) FROM conflict WHERE respaldo_evidencia = 'respaldo_exact_quote_detectado'"),
        "queue_total": one("SELECT COUNT(*) FROM project_review_queue"),
        "queue_merged": queue.get("merged", 0),
        "queue_separate": queue.get("kept_separate", 0),
        "queue_open": one("SELECT COUNT(*) FROM project_review_queue WHERE resolved = 0"),
        "mentions_without_link": one("SELECT COUNT(*) FROM enrichment_project_mention WHERE case_mention_index IS NULL"),
        "historical_refs": one("SELECT COUNT(*) FROM historical_case_reference"),
        "historical_refs_non_resolvable": one(
            "SELECT COUNT(*) FROM historical_case_reference WHERE impact_scope = 'confirmed_non_resolvable_historical_reference'"
        ),
    }


def render(stats: dict, manifest: dict) -> str:
    warehouse = manifest["warehouse"]
    lines = [
        BEGIN,
        "| Dato | Valor |",
        "|---|---|",
        f"| Versión de la release | {manifest['release_version']} |",
        f"| SHA-256 de `data/warehouse.sqlite` | `{warehouse['sha256']}` |",
        f"| Integridad | `integrity_check={warehouse['integrity_check']}`, {fmt(warehouse['foreign_key_check_violations'])} violaciones de FK |",
        f"| Documentos del corpus | {fmt(stats['documents'])} ({fmt(stats['documents_extracted'])} con extracción estructurada) |",
        f"| Proyectos · casos · conflictos | {fmt(stats['projects'])} · {fmt(stats['cases'])} · {fmt(stats['conflicts'])} |",
        f"| Cola de identidad de proyectos | {fmt(stats['queue_total'])} pares: {fmt(stats['queue_merged'])} fusionados, "
        f"{fmt(stats['queue_separate'])} separados, {fmt(stats['queue_open'])} abiertos |",
        f"| Conflictos con respaldo de evidencia | {fmt(stats['conflicts_backed'])} de {fmt(stats['conflicts'])} "
        f"({fmt(stats['conflicts'] - stats['conflicts_backed'])} sin respaldo detectado) |",
        f"| Menciones de proyecto sin vínculo a una `case_mention` | {fmt(stats['mentions_without_link'])} |",
        f"| Referencias históricas preservadas | {fmt(stats['historical_refs'])} "
        f"({fmt(stats['historical_refs_non_resolvable'])} confirmadas como no resolubles) |",
        END,
    ]
    return "\n".join(lines)


def rendered_block(warehouse_path: Path = WAREHOUSE_PATH, manifest_path: Path = MANIFEST_PATH) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{warehouse_path.as_posix()}?mode=ro", uri=True)
    try:
        return render(collect(conn), manifest)
    finally:
        conn.close()


def update_text(text: str, block: str) -> str:
    if not BLOCK_RE.search(text):
        raise ValueError("el archivo no contiene los marcadores <!-- stats:begin --> / <!-- stats:end -->")
    return BLOCK_RE.sub(lambda _m: block, text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="solo verifica; codigo 1 si algun archivo esta desactualizado")
    args = parser.parse_args()
    block = rendered_block()
    stale = []
    for target in TARGETS:
        current = target.read_bytes().decode("utf-8")
        updated = update_text(current.replace("\r\n", "\n"), block)
        if current.replace("\r\n", "\n") != updated:
            stale.append(target.name)
            if not args.check:
                target.write_bytes(updated.encode("utf-8"))
                print(f"actualizado {target.name}")
    if args.check and stale:
        print(f"desactualizados: {', '.join(stale)} -- corre `python src/render_docs_stats.py`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
