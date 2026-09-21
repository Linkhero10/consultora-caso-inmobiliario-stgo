#!/usr/bin/env python3
"""Capa de dataset de presentación para el dashboard.

Construye, a partir de `data/warehouse.sqlite`, un objeto agregado y compacto
listo para renderizar: toda la lógica de conteo/agrupación vive aquí (Python +
SQL), no en el HTML/JS. El builder del dashboard (`build_dashboard.py`) solo
presenta lo que esta capa produce.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"

# Evidencia máxima citada por conflicto en el índice compacto -- el detalle
# completo de un conflicto puntual se puede pedir aparte, no se embebe todo.
MAX_EVIDENCE_QUOTES_PER_CONFLICT = 3
MAX_EVENTS_PER_CONFLICT = 8


def _connect(path: Path = WAREHOUSE_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def _rows(con: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def _document_comunas(con: sqlite3.Connection) -> dict[str, list[dict[str, str]]]:
    """document_id -> lista de {comuna, codigo_comuna_ine} de sus case_mentions (sin vacíos)."""
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _rows(
        con,
        "SELECT DISTINCT document_id, comuna, codigo_comuna_ine FROM case_mention "
        "WHERE codigo_comuna_ine != '' AND codigo_comuna_ine IS NOT NULL",
    ):
        out[row["document_id"]].append({"comuna": row["comuna"], "codigo_comuna_ine": row["codigo_comuna_ine"]})
    return out


def build_territories(con: sqlite3.Connection) -> list[dict[str, Any]]:
    territories = _rows(con, "SELECT * FROM territory ORDER BY comuna")
    doc_comunas = _document_comunas(con)

    conflict_docs = _rows(con, "SELECT conflict_id, document_id FROM document_conflict")
    doc_to_conflicts: dict[str, set[str]] = defaultdict(set)
    for row in conflict_docs:
        doc_to_conflicts[row["document_id"]].add(row["conflict_id"])

    project_docs = _rows(con, "SELECT project_id, document_id FROM project_mention_resolved")
    doc_to_projects: dict[str, set[str]] = defaultdict(set)
    for row in project_docs:
        doc_to_projects[row["document_id"]].add(row["project_id"])

    actor_docs = _rows(con, "SELECT DISTINCT document_id, nombre FROM enrichment_actor")
    doc_to_actors: dict[str, set[str]] = defaultdict(set)
    for row in actor_docs:
        doc_to_actors[row["document_id"]].add(row["nombre"])

    by_comuna_conflicts: dict[str, set[str]] = defaultdict(set)
    by_comuna_projects: dict[str, set[str]] = defaultdict(set)
    by_comuna_actors: dict[str, set[str]] = defaultdict(set)
    by_comuna_documents: dict[str, set[str]] = defaultdict(set)

    for document_id, comunas in doc_comunas.items():
        codes = {c["codigo_comuna_ine"] for c in comunas}
        for code in codes:
            by_comuna_documents[code].add(document_id)
            by_comuna_conflicts[code].update(doc_to_conflicts.get(document_id, set()))
            by_comuna_projects[code].update(doc_to_projects.get(document_id, set()))
            by_comuna_actors[code].update(doc_to_actors.get(document_id, set()))

    result = []
    for t in territories:
        code = t["codigo_comuna_ine"]
        n_conflicts = len(by_comuna_conflicts.get(code, ()))
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
                "n_conflicts": n_conflicts,
                "n_projects": len(by_comuna_projects.get(code, ())),
                "n_documents": len(by_comuna_documents.get(code, ())),
                "n_actors": len(by_comuna_actors.get(code, ())),
                "n_conflicts_per_100k": round(n_conflicts / poblacion * 100_000, 2) if poblacion else None,
            }
        )
    return result


def build_conflicts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    conflicts = _rows(con, "SELECT * FROM conflict ORDER BY n_case_ids DESC")
    doc_links = _rows(con, "SELECT conflict_id, document_id, role FROM document_conflict")
    conflict_to_docs: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in doc_links:
        conflict_to_docs[row["conflict_id"]].append({"document_id": row["document_id"], "role": row["role"]})

    conflict_to_projects: dict[str, set[str]] = defaultdict(set)
    for row in _rows(con, "SELECT conflict_id, project_id FROM conflict_project"):
        conflict_to_projects[row["conflict_id"]].add(row["project_id"])

    projects_by_id = {p["project_id"]: p for p in _rows(con, "SELECT * FROM project")}
    documents_by_id = {d["document_id"]: d for d in _rows(con, "SELECT * FROM document")}
    doc_comunas = _document_comunas(con)

    actors_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(con, "SELECT * FROM enrichment_actor"):
        actors_by_doc[row["document_id"]].append(row)

    events_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(con, "SELECT * FROM event"):
        events_by_doc[row["document_id"]].append(row)

    evidence_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _rows(con, "SELECT document_id, quote_role, quote_text FROM evidence WHERE verified = 1"):
        evidence_by_doc[row["document_id"]].append(row)

    result = []
    for c in conflicts:
        conflict_id = c["conflict_id"]
        docs = conflict_to_docs.get(conflict_id, [])
        doc_ids = [d["document_id"] for d in docs]

        comunas_seen: dict[str, str] = {}
        for doc_id in doc_ids:
            for entry in doc_comunas.get(doc_id, []):
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

        actors: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []
        evidence_quotes: list[str] = []
        documents_out = []
        for doc_id in doc_ids:
            doc = documents_by_id.get(doc_id)
            if doc:
                documents_out.append({"document_id": doc_id, "url": doc["url"], "title": doc["title"]})
            for actor in actors_by_doc.get(doc_id, []):
                key = actor["nombre"]
                if key not in actors:
                    actors[key] = {
                        "nombre": actor["nombre"],
                        "tipo": actor["tipo"],
                        "stance": actor["stance"],
                        "nivel_involucramiento": actor["nivel_involucramiento"],
                    }
            for ev in events_by_doc.get(doc_id, []):
                events.append(
                    {
                        "fecha": ev["fecha"],
                        "descripcion": ev["descripcion"],
                        "tipo_hito": ev["tipo_hito"],
                    }
                )
            if len(evidence_quotes) < MAX_EVIDENCE_QUOTES_PER_CONFLICT:
                for ev in evidence_by_doc.get(doc_id, []):
                    if len(evidence_quotes) >= MAX_EVIDENCE_QUOTES_PER_CONFLICT:
                        break
                    evidence_quotes.append(ev["quote_text"])

        result.append(
            {
                "conflict_id": conflict_id,
                "label": c["label"],
                "n_case_ids": c["n_case_ids"],
                "origen": c["origen"],
                "confidence": c["confidence"],
                "comunas": [{"codigo_comuna_ine": k, "comuna": v} for k, v in sorted(comunas_seen.items())],
                "projects": projects,
                "documents": documents_out,
                "actors": list(actors.values()),
                "events": events[:MAX_EVENTS_PER_CONFLICT],
                "n_events_total": len(events),
                "evidence_quotes_sample": evidence_quotes,
            }
        )
    return result


def build_timeline(con: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    rows = _rows(
        con,
        "SELECT fecha, descripcion, tipo_hito, nombre_proyecto, fecha_year_grounded FROM event "
        "WHERE fecha_year_grounded = 1 ORDER BY fecha LIMIT ?",
        (limit,),
    )
    return rows


def build_summary(con: sqlite3.Connection, territories: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    n_documents = con.execute("SELECT COUNT(*) FROM document").fetchone()[0]
    n_case_mentions = con.execute("SELECT COUNT(*) FROM case_mention").fetchone()[0]
    n_projects = con.execute("SELECT COUNT(*) FROM project").fetchone()[0]
    n_actors = con.execute("SELECT COUNT(DISTINCT nombre) FROM enrichment_actor").fetchone()[0]
    n_evidence_verified = con.execute("SELECT COUNT(*) FROM evidence WHERE verified = 1").fetchone()[0]
    return {
        "n_documents": n_documents,
        "n_case_mentions": n_case_mentions,
        "n_conflicts": len(conflicts),
        "n_projects": n_projects,
        "n_actors": n_actors,
        "n_evidence_verified": n_evidence_verified,
        "n_comunas_con_conflictos": sum(1 for t in territories if t["n_conflicts"] > 0),
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
        for actor in conflict["actors"]:
            found["enrichment_actor_tipo"].add(actor["tipo"])
            if actor["stance"]:
                found["stance"].add(actor["stance"])
            if actor["nivel_involucramiento"]:
                found["nivel_involucramiento"].add(actor["nivel_involucramiento"])
        for event in conflict["events"]:
            found["tipo_hito"].add(event["tipo_hito"])
    return found


if __name__ == "__main__":
    data = build_dashboard_dataset()
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
