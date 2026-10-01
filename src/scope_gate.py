#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Etapa de construccion: aplica el filtro de alcance a cada conflicto y crea `conflict_scope`.

Las respuestas del modelo de decision (Jev) viven versionadas en `config/conflict_scope_decisions.json` (se producen con
`python src/scope_jev.py --classify-conflicts`, que usa la API y el corpus). Esta etapa NO llama a ninguna API: lee ese archivo,
aplica la regla explicita de `scope_jev.RULE` y escribe, por conflicto, `aprobado` / `rechazado` / `sin_evaluar`:

- `aprobado`: disputa concreta, tema inmobiliario/urbano y proyecto que no es solo una mencion de paso;
- `rechazado`: incumple alguna condicion (los motivos quedan registrados);
- `sin_evaluar`: no hay decision vigente (conflicto nuevo, o cambio su agrupacion/documentos: la firma ya no coincide).

La vista `conflict_conservative` reune los conflictos con respaldo de evidencia Y alcance aprobado: es el universo que las dos
validaciones ciegas midieron como el de mayor proporcion de conflictos correctos. Nada se borra: los conflictos rechazados siguen
en `conflict`, solo quedan fuera de esa vista.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scope_jev import DECISIONS_PATH, MODEL, RULE, answers_from_decision, decide, unit_signature  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"


def load_decisions(path: Path = DECISIONS_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "conflict_scope_decisions":
        raise ValueError("schema_version de conflict_scope_decisions no reconocido")
    decisions = {}
    for entry in payload["decisions"]:
        if entry["conflict_id"] in decisions:
            raise ValueError(f"decision duplicada: {entry['conflict_id']}")
        if not 0.0 <= float(entry["disputa"]) <= 1.0 or not entry.get("tema") or not entry.get("foco"):
            raise ValueError(f"decision de alcance invalida: {entry['conflict_id']}")
        decisions[entry["conflict_id"]] = entry
    return decisions


def build(conn: sqlite3.Connection, decisions: dict[str, dict], model: str = MODEL) -> dict[str, int]:
    conn.executescript(
        """
        DROP VIEW IF EXISTS conflict_conservative;
        DROP TABLE IF EXISTS conflict_scope;
        CREATE TABLE conflict_scope (
            conflict_id TEXT PRIMARY KEY REFERENCES conflict(conflict_id),
            alcance TEXT NOT NULL CHECK (alcance IN ('aprobado', 'rechazado', 'sin_evaluar')),
            motivos TEXT,
            disputa REAL,
            tema TEXT,
            foco TEXT,
            unit_signature TEXT NOT NULL,
            model TEXT
        );
        """
    )
    counts = {"aprobado": 0, "rechazado": 0, "sin_evaluar": 0}
    for (conflict_id, label) in conn.execute("SELECT conflict_id, label FROM conflict").fetchall():
        docs = conn.execute("SELECT document_id, role FROM document_conflict WHERE conflict_id = ?", (conflict_id,)).fetchall()
        signature = unit_signature(label, [(d, r) for d, r in docs])
        entry = decisions.get(conflict_id)
        if entry is None or entry["signature"] != signature:
            row = (conflict_id, "sin_evaluar", None, None, None, None, signature, None)
        else:
            verdict = decide(answers_from_decision(entry), RULE)
            row = (conflict_id, "aprobado" if verdict["pasa"] else "rechazado", ",".join(verdict["motivos"]) or None,
                   entry["disputa"], entry["tema"], entry["foco"], signature, model)
        counts[row[1]] += 1
        conn.execute("INSERT INTO conflict_scope VALUES (?,?,?,?,?,?,?,?)", row)
    conn.executescript(
        """
        CREATE VIEW conflict_conservative AS
        SELECT c.* FROM conflict c JOIN conflict_scope s USING(conflict_id)
        WHERE c.respaldo_evidencia = 'respaldo_exact_quote_detectado' AND s.alcance = 'aprobado';
        """
    )
    return counts


def main() -> int:
    conn = sqlite3.connect(WAREHOUSE)
    try:
        counts = build(conn, load_decisions())
        conn.commit()
        conservative = conn.execute("SELECT COUNT(*) FROM conflict_conservative").fetchone()[0]
    finally:
        conn.close()
    print(json.dumps({"alcance": counts, "conflictos_con_respaldo_y_alcance_aprobado": conservative}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
