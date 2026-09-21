#!/usr/bin/env python3
"""Backfill de geografía derivada: comuna determinista + geocodificación de
lugares mencionados contra el gazetteer BCN (Fase B).

No toca `case_mention` (salida cruda del clasificador). Crea/llena tres
tablas derivadas:

- `case_mention_geography`: código INE de comuna derivado deterministamente
  del texto de comuna ya extraído por el clasificador, cuando
  `case_mention.codigo_comuna_ine` viene vacío. Usa `derive_ine_code`
  (ya existente en `src/classify.py`, exacto, sin heurística) -- nunca se
  mezcla con el valor original del LLM en la misma columna.
- `geocoded_location`: resolución de textos de evidencia geográfica más
  específicos que una comuna (calles, barrios, lugares puntuales) contra el
  gazetteer BCN (`src/geocode_locations.py`, sin fuzzy matching, nunca
  fabrica coordenadas). Los textos que ya son literalmente el nombre de una
  de las 32 comunas del área de estudio se omiten aquí a propósito -- ese
  caso ya lo resuelve `case_mention_geography` de forma determinista; pedirle
  lo mismo al gazetteer nacional es redundante y, por la duplicación de
  filas admin_comuna/Comuna/Ciudad que tiene el propio gazetteer para el
  nombre de una comuna, casi siempre no es único.
- `geocoded_location_conflict`: relación (potencialmente muchos-a-muchos)
  entre un lugar geocodificado y los conflictos de los documentos donde
  aparece. Todo lo que produce este script se marca `relation_type =
  'contextual_location'` -- es evidencia geográfica citada en el documento,
  no una determinación curada de "este es el sitio focal del proyecto/
  conflicto"; esa distinción más fina queda para un trabajo posterior.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import COMUNA_INE_CODES, _split_comuna_names, derive_ine_code, _key  # noqa: E402
from geocode_locations import resolve_location  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"

_KNOWN_COMUNA_KEYS = {_key(name) for name in COMUNA_INE_CODES}

SCHEMA = """
CREATE TABLE IF NOT EXISTS case_mention_geography (
    case_mention_id TEXT PRIMARY KEY,
    codigo_comuna_ine TEXT NOT NULL,
    resolution_method TEXT NOT NULL,
    source_field TEXT NOT NULL,
    confidence TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geocoded_location (
    geocode_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    case_mention_id TEXT,
    evidence_id TEXT,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    matched_name TEXT NOT NULL,
    comuna TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    match_method TEXT NOT NULL,
    n_candidates_before_context INTEGER NOT NULL,
    n_candidates_after_context INTEGER NOT NULL,
    spatial_precision TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geocoded_location_conflict (
    geocode_id TEXT NOT NULL,
    conflict_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    PRIMARY KEY (geocode_id, conflict_id)
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def backfill_case_mention_geography(con: sqlite3.Connection) -> dict[str, int]:
    con.execute("DELETE FROM case_mention_geography")
    rows = con.execute(
        "SELECT case_mention_id, comuna FROM case_mention "
        "WHERE (codigo_comuna_ine = '' OR codigo_comuna_ine IS NULL) AND comuna != '' AND comuna IS NOT NULL"
    ).fetchall()
    resolved = 0
    for row in rows:
        # El texto puede ser compuesto ("Quinta Normal y Maipú"): se resuelve
        # solo cuando exactamente UNA de las partes cae dentro de las 32
        # comunas del área de estudio -- si el texto describe genuinamente
        # más de una comuna, no se elige una arbitrariamente.
        codes = {derive_ine_code(part) for part in _split_comuna_names(row["comuna"])}
        codes.discard("")
        if len(codes) != 1:
            continue
        (code,) = codes
        con.execute(
            "INSERT INTO case_mention_geography (case_mention_id, codigo_comuna_ine, resolution_method, source_field, confidence) "
            "VALUES (?, ?, 'exact_comuna_lookup', 'comuna', 'alta_determinista')",
            (row["case_mention_id"], code),
        )
        resolved += 1
    con.commit()
    return {"n_candidatos": len(rows), "n_resueltos": resolved}


def _document_conflicts(con: sqlite3.Connection) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for row in con.execute("SELECT document_id, conflict_id FROM document_conflict"):
        out.setdefault(row["document_id"], set()).add(row["conflict_id"])
    return out


def geocode_evidence_locations(con: sqlite3.Connection) -> dict[str, Any]:
    con.execute("DELETE FROM geocoded_location")
    con.execute("DELETE FROM geocoded_location_conflict")

    case_mention_comuna = {
        row["case_mention_id"]: row["comuna"]
        for row in con.execute("SELECT case_mention_id, comuna FROM case_mention")
    }
    doc_conflicts = _document_conflicts(con)

    rows = con.execute(
        "SELECT evidence_id, document_id, case_mention_id, quote_text FROM evidence "
        "WHERE quote_role = 'geografica' AND verified = 1"
    ).fetchall()

    n_attempted = 0
    n_skipped_bare_comuna = 0
    n_resolved = 0
    n_fuera_de_area = 0
    by_precision: dict[str, int] = {}

    for row in rows:
        text = str(row["quote_text"] or "").strip()
        if not text:
            continue
        if _key(text) in _KNOWN_COMUNA_KEYS:
            n_skipped_bare_comuna += 1
            continue
        n_attempted += 1
        prefer_comuna = case_mention_comuna.get(row["case_mention_id"], "")
        result = resolve_location(text, prefer_comuna=prefer_comuna, skip_exact_names=_KNOWN_COMUNA_KEYS)
        if result is None:
            continue
        # El gazetteer BCN es nacional y tiene homonimos reales entre comunas
        # de Chile y lugares de otros paises citados de pasada en el corpus
        # (ej. "Monterrey, Nuevo Leon" calzando con un "Monterrey" en Santa
        # Juana; "Lima" en un articulo sobre Peru calzando con una localidad
        # chilena homonima). Este proyecto solo cubre las 32 comunas de la
        # Provincia de Santiago -- si el match cae fuera de esa lista, se
        # descarta: unicidad nacional no es lo mismo que pertenencia al area
        # de estudio, y aceptar el homonimo fabricaria una relacion falsa
        # entre un lugar de otro pais/region y un conflicto de Santiago.
        if _key(result.comuna or "") not in _KNOWN_COMUNA_KEYS:
            n_fuera_de_area += 1
            continue
        n_resolved += 1
        by_precision[result.spatial_precision] = by_precision.get(result.spatial_precision, 0) + 1
        geocode_id = f"geo:{row['evidence_id']}"
        con.execute(
            "INSERT INTO geocoded_location (geocode_id, document_id, case_mention_id, evidence_id, raw_text, "
            "normalized_text, matched_name, comuna, lat, lon, match_method, n_candidates_before_context, "
            "n_candidates_after_context, spatial_precision, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                geocode_id,
                row["document_id"],
                row["case_mention_id"],
                row["evidence_id"],
                result.raw_text,
                result.normalized_text,
                result.matched_name,
                result.comuna,
                result.lat,
                result.lon,
                result.match_method,
                result.n_candidates_before_context,
                result.n_candidates_after_context,
                result.spatial_precision,
                result.source,
            ),
        )
        for conflict_id in doc_conflicts.get(row["document_id"], ()):
            con.execute(
                "INSERT OR IGNORE INTO geocoded_location_conflict (geocode_id, conflict_id, relation_type) VALUES (?, ?, 'contextual_location')",
                (geocode_id, conflict_id),
            )

    con.commit()
    return {
        "n_evidencia_geografica_total": len(rows),
        "n_omitidas_por_ser_comuna_pura": n_skipped_bare_comuna,
        "n_intentadas": n_attempted,
        "n_descartadas_fuera_del_area_de_estudio": n_fuera_de_area,
        "n_resueltas": n_resolved,
        "tasa_resolucion": round(n_resolved / n_attempted, 3) if n_attempted else 0.0,
        "por_precision": by_precision,
    }


def main(warehouse_path: Path = WAREHOUSE_PATH) -> int:
    con = _connect(warehouse_path)
    try:
        ensure_schema(con)
        comuna_report = backfill_case_mention_geography(con)
        geocode_report = geocode_evidence_locations(con)
    finally:
        con.close()

    print("case_mention_geography:", comuna_report)
    print("geocoded_location:", geocode_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
