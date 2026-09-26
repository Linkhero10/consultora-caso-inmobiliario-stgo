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
  nombre de una comuna, casi siempre no es único. La comuna preferida que se
  le pasa al geocoder como contexto SIEMPRE viene de una comuna ya resuelta
  de forma determinista (`case_mention.codigo_comuna_ine` o el backfill de
  `case_mention_geography`), nunca del texto crudo del clasificador (que
  puede ser compuesto, ej. "Ñuñoa y Providencia", y no sirve como filtro de
  una sola comuna).
- `geocoded_location_conflict`: relación (potencialmente muchos-a-muchos)
  entre un lugar geocodificado y los conflictos de los documentos donde
  aparece. Todo lo que produce este script se marca `relation_type =
  'contextual_location'` -- es evidencia geográfica citada en el documento,
  no una determinación curada de "este es el sitio focal del proyecto/
  conflicto"; esa distinción más fina queda para un trabajo posterior.
  El warehouse no tiene hoy una resolución a nivel de case_mention hacia
  project/conflict (`case_mention_document_project_candidates` está marcada
  `relation_status='document_level_only'` en el 100% de sus filas), así que
  el bridge solo se crea cuando el documento tiene un único conflicto
  asociado -- si tiene varios, no hay forma de saber a cuál pertenece la
  mención geográfica específica, y se prefiere no crear el vínculo antes
  que inventar uno.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import COMUNA_INE_CODES, _split_comuna_names, derive_ine_code, _key  # noqa: E402
from geocode_locations import resolve_location  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"
PROJECT_MENTION_GEOGRAPHY_REPORT_PATH = PROJECT_ROOT / "audit" / "project_mention_geography_report.json"

_KNOWN_COMUNA_KEYS = {_key(name) for name in COMUNA_INE_CODES}
_COMUNA_NAME_BY_CODE = {code: name for name, code in COMUNA_INE_CODES.items()}

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

CREATE TABLE IF NOT EXISTS project_mention_geography (
    document_id TEXT NOT NULL,
    project_mention_id TEXT NOT NULL,
    nombre_proyecto TEXT NOT NULL,
    case_mention_id TEXT,
    comuna TEXT,
    codigo_comuna_ine TEXT,
    match_method TEXT NOT NULL CHECK (match_method IN (
        'direct', 'via_duplicate_group', 'no_case_mention_index',
        'case_mention_no_incluido', 'case_mention_sin_comuna'
    )),
    PRIMARY KEY (document_id, project_mention_id)
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
        # cuando existe EXACTAMENTE UNA comuna perteneciente al área de
        # estudio entre las partes (las demás partes pueden estar fuera del
        # área sin afectar la resolución -- no se exige que el texto entero
        # sea una sola comuna, solo que dentro del área de estudio no haya
        # ambigüedad).
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


def _resolved_comuna_name_by_case_mention(con: sqlite3.Connection) -> dict[str, str]:
    """case_mention_id -> nombre de comuna, SOLO cuando hay una comuna ya
    resuelta de forma determinista (codigo_comuna_ine directo del case_mention,
    o el backfill de case_mention_geography). Nunca el texto crudo del
    clasificador (que puede ser compuesto, ej. "Ñuñoa y Providencia", y no
    sirve como filtro de una sola comuna)."""
    resolved: dict[str, str] = {}
    for row in con.execute("SELECT case_mention_id, codigo_comuna_ine FROM case_mention"):
        code = row["codigo_comuna_ine"]
        if code and code in _COMUNA_NAME_BY_CODE:
            resolved[row["case_mention_id"]] = _COMUNA_NAME_BY_CODE[code]
    if _table_exists(con, "case_mention_geography"):
        for row in con.execute("SELECT case_mention_id, codigo_comuna_ine FROM case_mention_geography"):
            resolved.setdefault(row["case_mention_id"], _COMUNA_NAME_BY_CODE.get(row["codigo_comuna_ine"], ""))
    return {k: v for k, v in resolved.items() if v}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name = ? AND type = 'table'", (name,)).fetchone() is not None


def _resolved_comuna_code_by_case_mention(con: sqlite3.Connection) -> dict[str, str]:
    """Igual que _resolved_comuna_name_by_case_mention() pero devuelve el
    codigo_comuna_ine (no el nombre) -- lo que necesita project_mention_geography
    para ser consistente con la columna que ya usa build_territories() en
    dashboard_data.py."""
    resolved: dict[str, str] = {}
    for row in con.execute("SELECT case_mention_id, codigo_comuna_ine FROM case_mention"):
        if row["codigo_comuna_ine"]:
            resolved[row["case_mention_id"]] = row["codigo_comuna_ine"]
    if _table_exists(con, "case_mention_geography"):
        for row in con.execute("SELECT case_mention_id, codigo_comuna_ine FROM case_mention_geography"):
            resolved.setdefault(row["case_mention_id"], row["codigo_comuna_ine"])
    return resolved


def _duplicate_group_members(con: sqlite3.Connection) -> dict[str, list[str]]:
    """Mismo patron que build_conflicts.py::main() (Fix 1E) -- reusado aqui
    tal cual, no reimplementado con logica distinta."""
    groups: dict[str, list[str]] = {}
    if not _table_exists(con, "case_mention_duplicate_link"):
        return groups
    groups_raw: dict[str, list[str]] = {}
    for row in con.execute("SELECT case_mention_id, duplicate_group_id FROM case_mention_duplicate_link"):
        groups_raw.setdefault(row["duplicate_group_id"], []).append(row["case_mention_id"])
    for members in groups_raw.values():
        if len(members) > 1:
            for cm_id in members:
                groups[cm_id] = members
    return groups


def build_project_mention_geography(con: sqlite3.Connection) -> dict[str, int]:
    """Fix 1F (2026-09-26): geografia real de proyectos por case_mention,
    mismo mecanismo que Fix 1D uso para el respaldo de CONFLICT -- ahora que
    enrichment_project_mention.case_mention_index esta materializado
    (migracion v3.2->v3.3), resolver que comuna corresponde a cada mencion
    de proyecto es un JOIN directo contra case_mention/case_mention_geography,
    no una heuristica documental. Reemplaza la aproximacion vieja de
    dashboard_data.py (cualquier mencion del documento -> comuna del
    documento) por un vinculo verificado a nivel de mencion."""
    con.execute("DROP TABLE IF EXISTS project_mention_geography")
    con.executescript(SCHEMA)  # idempotente (CREATE TABLE IF NOT EXISTS)

    comuna_code_by_cm = _resolved_comuna_code_by_case_mention(con)
    included_cms = {
        row[0] for row in con.execute("SELECT case_mention_id FROM case_mention WHERE decision_final_amplio = 'include'")
    }
    duplicate_group_members = _duplicate_group_members(con)

    counts = {"direct": 0, "via_duplicate_group": 0, "no_case_mention_index": 0, "case_mention_no_incluido": 0, "case_mention_sin_comuna": 0}
    rows_to_insert: list[tuple] = []
    for pm_id, document_id, nombre, case_mention_id in con.execute(
        "SELECT project_mention_id, document_id, nombre_proyecto, case_mention_id FROM enrichment_project_mention"
    ):
        if case_mention_id is None:
            counts["no_case_mention_index"] += 1
            rows_to_insert.append((document_id, pm_id, nombre, None, None, None, "no_case_mention_index"))
            continue
        if case_mention_id in included_cms and case_mention_id in comuna_code_by_cm:
            code = comuna_code_by_cm[case_mention_id]
            counts["direct"] += 1
            rows_to_insert.append((document_id, pm_id, nombre, case_mention_id, _COMUNA_NAME_BY_CODE.get(code, ""), code, "direct"))
            continue
        # Fix 1E: el case_mention que v3.3 indico puede no ser el que quedo
        # con comuna resuelta -- un hermano de su grupo de duplicados si.
        resolved_via_sibling = False
        for sibling_id in duplicate_group_members.get(case_mention_id, []):
            if sibling_id == case_mention_id or sibling_id not in included_cms:
                continue
            if sibling_id in comuna_code_by_cm:
                code = comuna_code_by_cm[sibling_id]
                counts["via_duplicate_group"] += 1
                rows_to_insert.append((document_id, pm_id, nombre, sibling_id, _COMUNA_NAME_BY_CODE.get(code, ""), code, "via_duplicate_group"))
                resolved_via_sibling = True
                break
        if resolved_via_sibling:
            continue
        if case_mention_id not in included_cms:
            counts["case_mention_no_incluido"] += 1
            rows_to_insert.append((document_id, pm_id, nombre, case_mention_id, None, None, "case_mention_no_incluido"))
        else:
            counts["case_mention_sin_comuna"] += 1
            rows_to_insert.append((document_id, pm_id, nombre, case_mention_id, None, None, "case_mention_sin_comuna"))

    con.executemany(
        "INSERT INTO project_mention_geography "
        "(document_id, project_mention_id, nombre_proyecto, case_mention_id, comuna, codigo_comuna_ine, match_method) "
        "VALUES (?,?,?,?,?,?,?)",
        rows_to_insert,
    )
    con.commit()
    return {"n_menciones_total": len(rows_to_insert), **counts}


def geocode_evidence_locations(con: sqlite3.Connection) -> dict[str, Any]:
    con.execute("DELETE FROM geocoded_location")
    con.execute("DELETE FROM geocoded_location_conflict")

    case_mention_comuna = _resolved_comuna_name_by_case_mention(con)
    doc_conflicts = _document_conflicts(con)

    rows = con.execute(
        "SELECT evidence_id, document_id, case_mention_id, quote_text FROM evidence "
        "WHERE quote_role = 'geografica' AND verified = 1"
    ).fetchall()

    n_attempted = 0
    n_skipped_bare_comuna = 0
    n_resolved = 0
    n_fuera_de_area = 0
    n_bridge_omitido_multiconflicto = 0
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
        # El warehouse no tiene hoy una resolucion a nivel de case_mention
        # hacia project/conflict (case_mention_document_project_candidates
        # esta marcada 'document_level_only' en el 100% de sus filas -- ver
        # docstring del modulo). Vincular por document_id cuando el documento
        # toca VARIOS conflictos reintroduciria el mismo producto cartesiano
        # ya corregido en dashboard_data.py: un lugar de la mencion A podria
        # quedar ligado tambien al conflicto B solo por compartir documento.
        # Se crea el bridge unicamente cuando el documento tiene un unico
        # conflicto asociado (ahi no hay ambiguedad posible); en cualquier
        # otro caso se prefiere no crear el vinculo antes que inventar uno.
        conflicts_for_doc = doc_conflicts.get(row["document_id"], set())
        if len(conflicts_for_doc) == 1:
            (conflict_id,) = conflicts_for_doc
            con.execute(
                "INSERT OR IGNORE INTO geocoded_location_conflict (geocode_id, conflict_id, relation_type) VALUES (?, ?, 'contextual_location')",
                (geocode_id, conflict_id),
            )
        else:
            n_bridge_omitido_multiconflicto += 1 if conflicts_for_doc else 0

    con.commit()
    return {
        "n_evidencia_geografica_total": len(rows),
        "n_omitidas_por_ser_comuna_pura": n_skipped_bare_comuna,
        "n_intentadas": n_attempted,
        "n_descartadas_fuera_del_area_de_estudio": n_fuera_de_area,
        "n_resueltas": n_resolved,
        "n_bridge_omitido_multiconflicto": n_bridge_omitido_multiconflicto,
        "tasa_resolucion": round(n_resolved / n_attempted, 3) if n_attempted else 0.0,
        "por_precision": by_precision,
    }


def main(warehouse_path: Path = WAREHOUSE_PATH) -> int:
    con = _connect(warehouse_path)
    try:
        ensure_schema(con)
        comuna_report = backfill_case_mention_geography(con)
        geocode_report = geocode_evidence_locations(con)
        project_geography_report = build_project_mention_geography(con)
    finally:
        con.close()

    print("case_mention_geography:", comuna_report)
    print("geocoded_location:", geocode_report)
    print("project_mention_geography:", project_geography_report)

    PROJECT_MENTION_GEOGRAPHY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROJECT_MENTION_GEOGRAPHY_REPORT_PATH.write_text(
        json.dumps(
            {
                "fix": "fix_1f_geografia_case_mention_level_2026-09-26",
                "descripcion": (
                    "Vinculo verificado proyecto->case_mention->comuna, mismo mecanismo que Fix 1D "
                    "uso para el respaldo de CONFLICT. Reemplaza la aproximacion vieja de "
                    "dashboard_data.py (cualquier mencion del documento -> comuna del documento)."
                ),
                **project_geography_report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
