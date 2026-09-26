#!/usr/bin/env python3
"""Capa de dataset de presentación para el dashboard.

Construye, a partir de `data/warehouse.sqlite`, un objeto agregado y compacto
listo para renderizar: toda la lógica de conteo/agrupación vive aquí (Python +
SQL), no en el HTML/JS. El builder del dashboard (`build_dashboard.py`) solo
presenta lo que esta capa produce.

Reglas de precisión territorial y de rol (revisión externa, ronda 2):
- Un documento solo aporta comuna cuando tiene una única comuna resuelta entre
  sus case_mentions. Si un documento mezcla >1 comuna distinta, no se le
  atribuye ninguna -- es preferible "sin comuna resuelta" que inventar
  precisión por un join a nivel de documento.
- La vista "principal" de cada conflicto (documentos, actores, eventos,
  evidencia) usa solo documentos con rol focal/co_focal sobre un caso único
  (`document_conflict_case_safe`, ya definida en el warehouse), igual que la
  metodología pública documentada en docs/methodology.md. El resto de
  menciones (contextuales, panorámicas, sin revisar) se listan aparte,
  explícitamente marcadas como no verificadas.
- Actores/instituciones/eventos del detalle de conflicto usan
  `actor_event_project_link_conflict_safe` (resolution_status='resolved_explicit'),
  no todo `enrichment_actor` del documento sin filtrar.
- Los nombres de actor se normalizan contra `actor_registry`/`actor_alias`
  cuando existe una entrada validada (ej. "Contraloría" ==
  "Contraloría General de la República"); si no hay entrada, se usa el
  nombre tal cual aparece en el texto.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"

MAX_EVIDENCE_QUOTES_PER_CONFLICT = 3
MAX_EVENTS_PER_CONFLICT = 8


def _connect(path: Path = WAREHOUSE_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def _rows(con: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def _table_or_view_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table','view')", (name,)
    ).fetchone() is not None


def _safe_document_conflicts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """document_id/conflict_id con rol focal/co_focal sobre un caso único.

    Usa la vista `document_conflict_case_safe` si existe en el warehouse
    (fuente de verdad ya validada); si no, aplica el mismo filtro a mano
    para que el módulo siga funcionando contra un warehouse más simple
    (ej. en tests con una base fixture reducida).
    """
    if _table_or_view_exists(con, "document_conflict_case_safe"):
        return _rows(con, "SELECT document_id, conflict_id, role FROM document_conflict_case_safe")
    if not _table_or_view_exists(con, "document_case_unit"):
        return _rows(
            con,
            "SELECT document_id, conflict_id, role FROM document_conflict WHERE role IN ('focal','co_focal')",
        )
    return _rows(
        con,
        """
        SELECT dc.document_id, dc.conflict_id, dc.role
        FROM document_conflict dc
        JOIN document_case_unit u ON u.document_id = dc.document_id
        WHERE dc.role IN ('focal', 'co_focal') AND u.unidad_caso_tipo = 'caso_unico'
        """,
    )


def _all_document_conflicts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(con, "SELECT document_id, conflict_id, role FROM document_conflict")


def _document_single_comuna(con: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """document_id -> {comuna, codigo_comuna_ine} SOLO cuando el documento
    tiene una única comuna resuelta entre sus case_mentions. Si mezcla >1
    comuna distinta, el documento queda fuera (no se adivina cuál corresponde
    a qué mención)."""
    by_doc: dict[str, dict[str, str]] = defaultdict(dict)
    for row in _rows(
        con,
        "SELECT DISTINCT document_id, comuna, codigo_comuna_ine FROM case_mention "
        "WHERE codigo_comuna_ine != '' AND codigo_comuna_ine IS NOT NULL",
    ):
        by_doc[row["document_id"]][row["codigo_comuna_ine"]] = row["comuna"]

    resolved: dict[str, dict[str, str]] = {}
    for document_id, codes in by_doc.items():
        if len(codes) == 1:
            (code, name), = codes.items()
            resolved[document_id] = {"comuna": name, "codigo_comuna_ine": code}
    return resolved


def _actor_identity_map(con: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """nombre_norm (minusculas, tal como en actor_alias) -> identidad canónica."""
    if not _table_or_view_exists(con, "actor_alias"):
        return {}
    out: dict[str, dict[str, str]] = {}
    registry = {r["entity_id"]: r for r in _rows(con, "SELECT * FROM actor_registry")} if _table_or_view_exists(con, "actor_registry") else {}
    for row in _rows(con, "SELECT nombre_norm, entity_id FROM actor_alias"):
        entity = registry.get(row["entity_id"])
        out[row["nombre_norm"]] = {
            "entity_id": row["entity_id"],
            "canonical_label": entity["canonical_label"] if entity else row["nombre_norm"],
        }
    return out


def _resolve_actor_name(raw_name: str, identity_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    key = " ".join(str(raw_name or "").strip().lower().split())
    match = identity_map.get(key)
    if match:
        return {"nombre": match["canonical_label"], "nombre_raw": raw_name, "identity_resolved": True, "entity_id": match["entity_id"]}
    return {"nombre": raw_name, "nombre_raw": raw_name, "identity_resolved": False, "entity_id": None}


def _backed_conflict_ids(con: sqlite3.Connection) -> set[str]:
    """conflict_id con respaldo_evidencia='respaldo_exact_quote_detectado'
    (Fix 1A) -- universo analitico conservador. Si la columna no existe
    (warehouse mas simple, ej. fixtures de test), se trata como si nada
    tuviera respaldo detectado (conservador por default, nunca al reves)."""
    if not _table_or_view_exists(con, "conflict") or not _column_exists(con, "conflict", "respaldo_evidencia"):
        return set()
    return {
        row["conflict_id"]
        for row in _rows(con, "SELECT conflict_id FROM conflict WHERE respaldo_evidencia = 'respaldo_exact_quote_detectado'")
    }


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r["name"] == column for r in con.execute(f"PRAGMA table_info({table})"))


def _projects_verified_by_comuna(con: sqlite3.Connection) -> dict[str, set[str]]:
    """[Fix 1F, 2026-09-26] codigo_comuna_ine -> set(project_id) usando
    SOLO menciones con vinculo verificado proyecto->case_mention->comuna
    (project_mention_geography, match_method directo, fallback de grupo limpio,
    o fallback de grupo mixto adjudicado manualmente solo para geografía -- ver
    src/build_geography.py::build_project_mention_geography()).
    Reemplaza la aproximacion vieja (cualquier mencion del documento
    atribuida a la comuna del documento) por el mismo mecanismo que Fix 1D
    ya uso para el respaldo de CONFLICT. Si la tabla no existe (warehouse
    mas simple, ej. fixtures de test que no corren build_geography.py),
    devuelve vacio -- nunca cae de vuelta al metodo viejo en silencio."""
    if not _table_or_view_exists(con, "project_mention_geography"):
        return {}
    by_comuna: dict[str, set[str]] = defaultdict(set)
    for row in _rows(
        con,
        "SELECT pmg.codigo_comuna_ine AS codigo_comuna_ine, pmr.project_id AS project_id "
        "FROM project_mention_geography pmg "
        "JOIN project_mention_resolved pmr "
        "  ON pmr.document_id = pmg.document_id AND pmr.raw_nombre_proyecto = pmg.nombre_proyecto "
        "WHERE pmg.match_method IN ('direct', 'via_duplicate_group', 'via_reviewed_duplicate_group') "
        "AND pmg.codigo_comuna_ine IS NOT NULL",
    ):
        by_comuna[row["codigo_comuna_ine"]].add(row["project_id"])
    return by_comuna


def build_territories(con: sqlite3.Connection) -> list[dict[str, Any]]:
    territories = _rows(con, "SELECT * FROM territory ORDER BY comuna")
    doc_comuna = _document_single_comuna(con)
    backed_conflict_ids = _backed_conflict_ids(con)

    safe_links = _safe_document_conflicts(con)
    doc_to_conflicts: dict[str, set[str]] = defaultdict(set)
    for row in safe_links:
        doc_to_conflicts[row["document_id"]].add(row["conflict_id"])

    projects_verified_by_comuna = _projects_verified_by_comuna(con)

    actor_docs = _rows(con, "SELECT DISTINCT document_id, nombre FROM enrichment_actor")
    doc_to_actors: dict[str, set[str]] = defaultdict(set)
    for row in actor_docs:
        doc_to_actors[row["document_id"]].add(row["nombre"])

    by_comuna_conflicts: dict[str, set[str]] = defaultdict(set)
    by_comuna_conflicts_backed: dict[str, set[str]] = defaultdict(set)
    by_comuna_actors: dict[str, set[str]] = defaultdict(set)
    by_comuna_documents: dict[str, set[str]] = defaultdict(set)

    for document_id, entry in doc_comuna.items():
        code = entry["codigo_comuna_ine"]
        by_comuna_documents[code].add(document_id)
        conflicts_here = doc_to_conflicts.get(document_id, set())
        by_comuna_conflicts[code].update(conflicts_here)
        by_comuna_conflicts_backed[code].update(conflicts_here & backed_conflict_ids)
        by_comuna_actors[code].update(doc_to_actors.get(document_id, set()))

    # Fix 1A: dos universos explicitos, nunca uno silencioso -- n_conflicts_total
    # (todo lo que document_conflict_case_safe vincula a esta comuna) vs.
    # n_conflicts_backed (el subconjunto con respaldo exacto de evidencia
    # detectado, ver build_conflicts.py). El mapa/resumen nunca deben
    # redefinir "conflictos" para que signifique solo uno de los dos sin
    # decirlo explicitamente.
    result = []
    for t in territories:
        code = t["codigo_comuna_ine"]
        n_conflicts_total = len(by_comuna_conflicts.get(code, ()))
        n_conflicts_backed = len(by_comuna_conflicts_backed.get(code, ()))
        poblacion = t["poblacion"] or 0
        result.append(
            {
                "codigo_comuna_ine": code,
                "comuna": t["comuna"],
                "poblacion": poblacion,
                "inmigrantes": t["inmigrantes"],
                "hogares": t["hogares"],
                "viviendas_hacinadas": t["viviendas_hacinadas"],
                "viviendas_irrecuperables": t["viviendas_irrecuperables"],
                "geometry": json.loads(t["geometry_json"]),
                "n_conflicts_total": n_conflicts_total,
                "n_conflicts_backed": n_conflicts_backed,
                # [Fix 1F, 2026-09-26 -- cierra el hallazgo de 2026-09-24] Antes
                # "n_projects_mentioned": cualquier mencion de proyecto en un documento
                # (project_mention_resolved, sin filtrar relevancia/foco) atribuida a la
                # comuna del documento -- no era territorio validado (mismo problema de
                # raiz que Fix 1D resolvio para el respaldo de conflictos en su momento).
                # Con el 100% del corpus en v3.3 (migracion 2026-09-26), cada mencion de
                # proyecto tiene (o no) un vinculo verificado a un case_mention real con su
                # PROPIA comuna resuelta (ver build_geography.py::build_project_mention_geography(),
                # match_method='direct'/'via_duplicate_group'/'via_reviewed_duplicate_group')
                # -- este conteo usa SOLO esos vinculos verificados, nunca la comuna del
                # documento como proxy. Los grupos mixtos no revisados quedan ambiguos.
                # Renombrado
                # a n_projects_verified porque ya no es una aproximacion.
                "n_projects_verified": len(projects_verified_by_comuna.get(code, ())),
                "n_documents": len(by_comuna_documents.get(code, ())),
                "n_actors": len(by_comuna_actors.get(code, ())),
                "n_conflicts_backed_per_100k": round(n_conflicts_backed / poblacion * 100_000, 2) if poblacion else None,
            }
        )
    return result


def _linked_actors_and_events(con: sqlite3.Connection, conflict_ids: set[str], identity_map: dict) -> tuple[dict[str, list], dict[str, list]]:
    """Actores/instituciones y eventos resueltos (resolved_explicit, foco
    focal/co-focal) por conflicto, vía actor_event_project_link_conflict_safe."""
    actors_by_conflict: dict[str, dict[str, dict]] = defaultdict(dict)
    events_by_conflict: dict[str, list[dict]] = defaultdict(list)

    if not _table_or_view_exists(con, "actor_event_project_link_conflict_safe"):
        return {}, {}

    links = _rows(
        con,
        "SELECT conflict_id, source_table, source_id, nombre FROM actor_event_project_link_conflict_safe "
        "WHERE resolution_status = 'resolved_explicit'",
    )
    actor_ids = [l["source_id"] for l in links if l["source_table"] == "enrichment_actor"]
    institution_ids = [l["source_id"] for l in links if l["source_table"] == "enrichment_institution"]
    event_ids = [l["source_id"] for l in links if l["source_table"] == "enrichment_event"]

    def _fetch_by_ids(table: str, id_col: str, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        return {r[id_col]: r for r in _rows(con, f"SELECT * FROM {table} WHERE {id_col} IN ({placeholders})", tuple(ids))}

    actors_detail = _fetch_by_ids("enrichment_actor", "actor_id", actor_ids)
    institutions_detail = _fetch_by_ids("enrichment_institution", "institucion_id", institution_ids)
    events_detail = _fetch_by_ids("enrichment_event", "event_id", event_ids)

    for link in links:
        conflict_id = link["conflict_id"]
        if conflict_id not in conflict_ids:
            continue
        if link["source_table"] == "enrichment_actor":
            detail = actors_detail.get(link["source_id"])
            if not detail:
                continue
            identity = _resolve_actor_name(detail["nombre"], identity_map)
            key = identity["entity_id"] or identity["nombre"]
            actors_by_conflict[conflict_id][key] = {
                **identity,
                "tipo": detail["tipo"],
                "tipo_categoria": "enrichment_actor_tipo",
                "stance": detail["stance"],
                "nivel_involucramiento": detail["nivel_involucramiento"],
            }
        elif link["source_table"] == "enrichment_institution":
            detail = institutions_detail.get(link["source_id"])
            if not detail:
                continue
            identity = _resolve_actor_name(detail["nombre"], identity_map)
            key = identity["entity_id"] or identity["nombre"]
            actors_by_conflict[conflict_id][key] = {
                **identity,
                "tipo": detail["tipo_norm"],
                "tipo_categoria": "enrichment_institution_tipo",
                "stance": None,
                "nivel_involucramiento": None,
            }
        elif link["source_table"] == "enrichment_event":
            detail = events_detail.get(link["source_id"])
            if not detail:
                continue
            events_by_conflict[conflict_id].append(
                {"fecha": detail["fecha"], "descripcion": detail["descripcion"], "tipo_hito": detail["tipo_hito"]}
            )

    return {cid: list(v.values()) for cid, v in actors_by_conflict.items()}, dict(events_by_conflict)


def build_conflicts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    conflicts = _rows(con, "SELECT * FROM conflict ORDER BY n_case_ids DESC")
    conflict_ids = {c["conflict_id"] for c in conflicts}

    safe_links = _safe_document_conflicts(con)
    all_links = _all_document_conflicts(con)
    conflict_to_safe_docs: dict[str, set[str]] = defaultdict(set)
    for row in safe_links:
        conflict_to_safe_docs[row["conflict_id"]].add(row["document_id"])
    conflict_to_other_docs: dict[str, dict[str, str]] = defaultdict(dict)
    for row in all_links:
        if row["document_id"] not in conflict_to_safe_docs.get(row["conflict_id"], set()):
            conflict_to_other_docs[row["conflict_id"]][row["document_id"]] = row["role"]

    conflict_to_projects: dict[str, set[str]] = defaultdict(set)
    for row in _rows(con, "SELECT conflict_id, project_id FROM conflict_project"):
        conflict_to_projects[row["conflict_id"]].add(row["project_id"])

    projects_by_id = {p["project_id"]: p for p in _rows(con, "SELECT * FROM project")}
    documents_by_id = {d["document_id"]: d for d in _rows(con, "SELECT * FROM document")}
    doc_comuna = _document_single_comuna(con)

    identity_map = _actor_identity_map(con)
    actors_by_conflict, events_by_conflict = _linked_actors_and_events(con, conflict_ids, identity_map)

    evidence_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(con, "SELECT document_id, quote_role, quote_text FROM evidence WHERE verified = 1"):
        evidence_by_doc[row["document_id"]].append(row)

    # Fix 1A seguimiento (2026-09-23): el detector de respaldo busca evidencia
    # en CUALQUIER documento que mencione el proyecto (nunca solo los
    # focales de este conflicto -- ver docstring de build_conflicts.py). Sin
    # este fallback, ~1/3 de los conflictos "con respaldo detectado" mostraban
    # el sello sin ninguna cita visible, porque su respaldo real vivia en un
    # documento no-focal. Se muestra explicitamente rotulada como tal --
    # nunca se mezcla con evidence_quotes_sample (que exige documento focal),
    # nunca se presenta como si fuera evidencia focal verificada.
    backing_quotes_by_conflict: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if _table_or_view_exists(con, "conflict_evidence_backing"):
        for row in _rows(
            con,
            "SELECT conflict_id, document_id, quote_text FROM conflict_evidence_backing ORDER BY conflict_id, document_id, evidence_id",
        ):
            entries = backing_quotes_by_conflict[row["conflict_id"]]
            if len(entries) < MAX_EVIDENCE_QUOTES_PER_CONFLICT and not any(e["quote_text"] == row["quote_text"] for e in entries):
                entries.append({"quote_text": row["quote_text"], "document_id": row["document_id"]})

    result = []
    for c in conflicts:
        conflict_id = c["conflict_id"]
        safe_doc_ids = sorted(conflict_to_safe_docs.get(conflict_id, ()))

        comunas_seen: dict[str, str] = {}
        for doc_id in safe_doc_ids:
            entry = doc_comuna.get(doc_id)
            if entry:
                comunas_seen[entry["codigo_comuna_ine"]] = entry["comuna"]

        projects = [
            {
                "project_id": pid,
                "nombre": projects_by_id[pid]["canonical_name"],
                "n_documents": projects_by_id[pid]["n_documents"],
            }
            for pid in sorted(conflict_to_projects.get(conflict_id, ()))
            if pid in projects_by_id
        ]

        documents_out = [
            {"document_id": doc_id, "url": documents_by_id[doc_id]["url"], "title": documents_by_id[doc_id]["title"]}
            for doc_id in safe_doc_ids
            if doc_id in documents_by_id
        ]
        other_mentions = [
            {"document_id": doc_id, "url": documents_by_id[doc_id]["url"], "title": documents_by_id[doc_id]["title"], "role": role}
            for doc_id, role in conflict_to_other_docs.get(conflict_id, {}).items()
            if doc_id in documents_by_id
        ]

        evidence_quotes: list[str] = []
        for doc_id in safe_doc_ids:
            if len(evidence_quotes) >= MAX_EVIDENCE_QUOTES_PER_CONFLICT:
                break
            for ev in evidence_by_doc.get(doc_id, []):
                if len(evidence_quotes) >= MAX_EVIDENCE_QUOTES_PER_CONFLICT:
                    break
                evidence_quotes.append(ev["quote_text"])

        events = events_by_conflict.get(conflict_id, [])

        fallback_backed = c.get("respaldo_evidencia") == "respaldo_exact_quote_detectado"
        backing_quotes_non_focal: list[dict[str, Any]] = []
        if not evidence_quotes and fallback_backed:
            backing_quotes_non_focal = [
                {
                    "quote_text": bq["quote_text"],
                    "document_url": documents_by_id.get(bq["document_id"], {}).get("url"),
                    "document_title": documents_by_id.get(bq["document_id"], {}).get("title"),
                }
                for bq in backing_quotes_by_conflict.get(conflict_id, [])
            ]
        result.append(
            {
                "conflict_id": conflict_id,
                "label": c["label"],
                "n_case_ids": c["n_case_ids"],
                "origen": c["origen"],
                "confidence": c["confidence"],
                "respaldo_evidencia": c.get("respaldo_evidencia", "sin_respaldo_exact_quote_detectado"),
                "n_projects_backed": c.get("n_projects_backed", len(projects) if fallback_backed else 0),
                "n_projects_unbacked": c.get("n_projects_unbacked", 0 if fallback_backed else len(projects)),
                "coverage_backing": c.get("coverage_backing", "total" if fallback_backed else "ninguna"),
                "label_source_project_id": c.get("label_source_project_id"),
                "n_documents_ambiguous_backing": c.get("n_documents_ambiguous_backing", 0),
                "comunas": [{"codigo_comuna_ine": k, "comuna": v} for k, v in sorted(comunas_seen.items())],
                "projects": projects,
                "documents": documents_out,
                "other_mentions": other_mentions,
                "actors": actors_by_conflict.get(conflict_id, []),
                "events": events[:MAX_EVENTS_PER_CONFLICT],
                "n_events_total": len(events),
                "evidence_quotes_sample": evidence_quotes,
                "backing_quotes_non_focal": backing_quotes_non_focal,
            }
        )
    return result


def build_timeline(con: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    return _rows(
        con,
        "SELECT fecha, descripcion, tipo_hito, nombre_proyecto, fecha_year_grounded FROM event "
        "WHERE fecha_year_grounded = 1 ORDER BY fecha LIMIT ?",
        (limit,),
    )


def build_summary(con: sqlite3.Connection, territories: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    n_documents = con.execute("SELECT COUNT(*) FROM document").fetchone()[0]
    n_case_mentions = con.execute("SELECT COUNT(*) FROM case_mention").fetchone()[0]
    n_projects = con.execute("SELECT COUNT(*) FROM project").fetchone()[0]
    n_evidence_verified = con.execute("SELECT COUNT(*) FROM evidence WHERE verified = 1").fetchone()[0]

    # "Actores" cuenta identidades resueltas y verificadas (focal/co-focal,
    # resolution_status='resolved_explicit'), no todo nombre crudo extraído
    # por el LLM sin importar el rol del documento que lo menciona.
    actor_keys: set[str] = set()
    for conflict in conflicts:
        for actor in conflict["actors"]:
            actor_keys.add(actor["entity_id"] or actor["nombre"])

    n_conflicts_evidence_backed = sum(1 for c in conflicts if c["respaldo_evidencia"] == "respaldo_exact_quote_detectado")

    # Fase C: capa de contexto social fino por manzana censal (Censo 2024).
    # Opcional a proposito -- fixtures de test y warehouses mas simples no
    # la tienen, y el resto del dashboard debe seguir funcionando igual.
    n_manzanas_censales = 0
    if _table_or_view_exists(con, "manzana_censal"):
        n_manzanas_censales = con.execute("SELECT COUNT(*) FROM manzana_censal").fetchone()[0]

    return {
        "n_documents": n_documents,
        "n_case_mentions": n_case_mentions,
        # Fix 1A: dos universos explicitos -- nunca redefinir "n_conflicts"
        # para que signifique solo el subconjunto respaldado sin decirlo.
        "n_conflicts_total": len(conflicts),
        "n_conflicts_evidence_backed": n_conflicts_evidence_backed,
        "n_conflicts_without_exact_backing": len(conflicts) - n_conflicts_evidence_backed,
        "n_projects": n_projects,
        "n_actors": len(actor_keys),
        "n_evidence_verified": n_evidence_verified,
        "n_comunas_con_conflictos": sum(1 for t in territories if t["n_conflicts_total"] > 0),
        "n_manzanas_censales": n_manzanas_censales,
        # [Fix 1F, 2026-09-26] n_projects (arriba, total del corpus) es un conteo
        # directo del registro de proyectos -- valido. territories[].n_projects_verified
        # (por comuna) ahora TAMBIEN es territorio validado: usa el vinculo verificado
        # proyecto->case_mention->comuna (build_geography.py::build_project_mention_geography(),
        # mismo mecanismo que Fix 1D uso para el respaldo de CONFLICT), no la comuna del
        # documento como proxy. Ver nota completa en el codigo de build_territories().
        "nota_metodologica_geografia_proyectos": "n_projects_verified por comuna usa menciones enlazadas a un case_mention con comuna resuelta: indice del modelo, grupo duplicado no mixto o adjudicacion manual explícita limitada a identidad geografica. Los grupos con decisiones mixtas sin adjudicacion, indices nulos y menciones sin comuna resuelta se excluyen; no se usa la comuna del documento como proxy. Ver audit/project_mention_geography_report.json.",
    }


def build_dashboard_dataset(warehouse_path: Path = WAREHOUSE_PATH) -> dict[str, Any]:
    con = _connect(warehouse_path)
    try:
        territories = build_territories(con)
        conflicts = build_conflicts(con)
        timeline = build_timeline(con)
        summary = build_summary(con, territories, conflicts)
        return {
            "summary": summary,
            "territories": territories,
            "conflicts": conflicts,
            "timeline": timeline,
        }
    finally:
        con.close()


def enum_values_present(dataset: dict[str, Any]) -> dict[str, set[str]]:
    """Recolecta, por categoría de label conocida, los valores que efectivamente
    aparecen en el dataset -- usado por el test de exhaustividad de labels."""
    found: dict[str, set[str]] = defaultdict(set)
    for conflict in dataset["conflicts"]:
        found["conflict_origen"].add(conflict["origen"])
        found["conflict_confidence"].add(conflict["confidence"])
        found["respaldo_evidencia"].add(conflict["respaldo_evidencia"])
        for actor in conflict["actors"]:
            if actor["tipo"]:
                found[actor["tipo_categoria"]].add(actor["tipo"])
            if actor["stance"]:
                found["stance"].add(actor["stance"])
            if actor["nivel_involucramiento"]:
                found["nivel_involucramiento"].add(actor["nivel_involucramiento"])
        for other in conflict["other_mentions"]:
            found["document_conflict_role"].add(other["role"])
        for event in conflict["events"]:
            found["tipo_hito"].add(event["tipo_hito"])
    return found


if __name__ == "__main__":
    data = build_dashboard_dataset()
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
