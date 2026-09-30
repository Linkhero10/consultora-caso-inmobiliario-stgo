#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Puntua una validacion ciega de conflictos contra el warehouse y escribe `audit/blind_validation_report.json`.

Entrada: `verdicts.json` del revisor (un veredicto por conflicto, ver `build_conflict_holdout.py`) y el warehouse.
El revisor NO ve el estado de respaldo del sistema; aqui se cruza por primera vez para medir, de extremo a extremo:
- la distribucion de veredictos en la muestra aleatoria (con intervalo de Wilson al 95 %);
- el veredicto segun el sistema marque el conflicto con respaldo de evidencia o sin el (lo que el producto publica
  como universo conservador es el primero);
- el acuerdo entre el respaldo del sistema y el juicio independiente del revisor (`respaldo_correcto`).
La muestra dirigida (stress) se informa aparte y nunca se usa para estimar prevalencia.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import REVIEW_SAMPLES_DIR  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERDICTS = REVIEW_SAMPLES_DIR / "blind_validation" / "verdicts.json"
DEFAULT_MANIFEST = REVIEW_SAMPLES_DIR / "blind_validation" / "validation_sample_manifest.json"
REPORT_PATH = PROJECT_ROOT / "audit" / "blind_validation_report.json"
VEREDICTOS = ("correcto", "error_menor", "error_grave", "no_verificable")


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, center - half), 3), round(min(1.0, center + half), 3)]


def _counts(items: list[dict]) -> dict:
    c = collections.Counter(item["veredicto"] for item in items)
    verifiable = sum(c[v] for v in VEREDICTOS if v != "no_verificable")
    return {
        "n": len(items),
        **{v: c[v] for v in VEREDICTOS},
        "n_verificables": verifiable,
        "error_grave_pct": round(c["error_grave"] / verifiable, 3) if verifiable else None,
        "error_grave_ic95": wilson(c["error_grave"], verifiable),
        "correcto_o_menor_pct": round((c["correcto"] + c["error_menor"]) / verifiable, 3) if verifiable else None,
        "correcto_o_menor_ic95": wilson(c["correcto"] + c["error_menor"], verifiable),
    }


def score(verdicts: list[dict], conn: sqlite3.Connection) -> dict:
    enriched = []
    for item in verdicts:
        row = conn.execute("SELECT respaldo_evidencia FROM conflict WHERE conflict_id = ?", (item["conflict_id"],)).fetchone()
        if row is None:
            raise ValueError(f"conflict_id ausente del warehouse: {item['conflict_id']}")
        n_docs = conn.execute("SELECT COUNT(*) FROM document_conflict WHERE conflict_id = ?", (item["conflict_id"],)).fetchone()[0]
        enriched.append({**item, "sistema_respaldo": row[0].startswith("respaldo"), "n_documentos": n_docs})

    main = [e for e in enriched if e["muestra"] == "main"]
    stress = [e for e in enriched if e["muestra"] == "stress"]
    agreement = collections.Counter(
        (("sistema_con_respaldo" if e["sistema_respaldo"] else "sistema_sin_respaldo"), e["respaldo_correcto"]) for e in enriched
    )
    return {
        "muestra_aleatoria": {
            "todos": _counts(main),
            "con_respaldo_del_sistema": _counts([e for e in main if e["sistema_respaldo"]]),
            "sin_respaldo_del_sistema": _counts([e for e in main if not e["sistema_respaldo"]]),
        },
        "muestra_dirigida_sin_respaldo": {**_counts(stress), "nota": "dirigida; no estima prevalencia"},
        "acuerdo_respaldo": {f"{a}|{b}": n for (a, b), n in sorted(agreement.items())},
        "conflictos_sin_documentos": sum(1 for e in enriched if e["n_documentos"] == 0),
        "categorias_de_error": dict(collections.Counter(e["categoria"] for e in enriched if e["categoria"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verdicts", type=Path, default=DEFAULT_VERDICTS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    payload = json.loads(args.verdicts.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    conn = sqlite3.connect(PROJECT_ROOT / "data" / "warehouse.sqlite")
    report = {
        "revisor": payload.get("revisor"),
        "warehouse_sha256_de_la_muestra": manifest["warehouse_sha256"],
        "semilla": manifest["selection_seed"],
        "ciega": manifest["blind"],
        "limites": [
            "Un solo revisor, de la misma familia de modelos que construyo el pipeline: no es una validacion humana externa.",
            "Criterio estricto: ante la duda se elige el veredicto menos favorable.",
            "Los conflictos sin documentos asociados no se pueden verificar.",
        ],
        **score(payload["verdicts"], conn),
        "veredictos": [
            {k: v.get(k) for k in ("conflict_id", "muestra", "veredicto", "categoria", "respaldo_correcto", "motivo")}
            for v in payload["verdicts"]
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "veredictos"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
