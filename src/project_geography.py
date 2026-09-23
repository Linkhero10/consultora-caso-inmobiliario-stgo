#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composición pura proyecto -> case_mention -> comuna (2026-09-23).

Prototipo aislado, NO conectado a `dashboard_data.py` todavía -- ver Fase 2
del diseño en `Auditoria/DISENO_geografia_case_mention_level_2026-09-23/`.
Este módulo solo compone dos relaciones que ya existen por separado:

1. `project_case_mention.build_project_case_mention_links()` (mención de
   proyecto -> case_mention/evidencia que la respalda).
2. La comuna propia de esa misma `case_mention` (`case_mention.comuna` /
   `codigo_comuna_ine`).

La regla dura: un proyecto solo obtiene una atribución directa a una comuna
cuando (a) el enlace es `verified_direct` (una única case_mention incluida
respalda el nombre, sin ambigüedad) Y (b) esa misma case_mention tiene una
comuna propia resuelta contra `territory`. Nunca se hereda la comuna de otra
mención del mismo documento. Todos los demás estados (`ambiguous_direct`,
`excluded_case_mention`, `non_included_case_mention`,
`document_level_candidate`, o `verified_direct` sin comuna resuelta) quedan
marcados explícitamente como no resueltos -- nunca se promueven en silencio.

Funciones puras: reciben listas/diccionarios, no tocan ninguna base de
datos.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

GEOGRAPHY_VERSION = "case_mention_comuna_attribution_v1"

_NOT_ELIGIBLE_STATUS = {
    "ambiguous_direct": "ambiguous_candidate",
    "excluded_case_mention": "excluded_not_eligible",
    "non_included_case_mention": "non_included_not_eligible",
    "document_level_candidate": "unresolved_document_level",
}


def resolve_case_mention_comuna(
    case_mention: dict[str, Any] | None,
    valid_codes: set[str] | None = None,
) -> dict[str, str] | None:
    """Comuna propia de una case_mention, o None si no hay codigo resoluble.

    Nunca cae de vuelta al codigo de otra mencion ni del documento -- si
    `case_mention` es None (no encontrada) o su codigo esta vacio/invalido,
    el resultado es None.
    """
    if not case_mention:
        return None
    code = (case_mention.get("codigo_comuna_ine") or "").strip()
    if not code:
        return None
    if valid_codes is not None and code not in valid_codes:
        return None
    return {"codigo_comuna_ine": code, "comuna": case_mention.get("comuna") or ""}


def attribute_projects_to_comunas(
    links: list[dict[str, Any]],
    case_mentions_by_id: dict[str, dict[str, Any]],
    valid_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Compone cada fila de `links` (salida del linker) con la comuna propia
    de su `case_mention`, cuando corresponde. Devuelve una fila por entrada
    de `links`, cada una con `geography_status` explícito:

    - `direct_attribution`: verified_direct + comuna propia resuelta.
    - `direct_link_no_comuna`: verified_direct pero la case_mention no tiene
      comuna resoluble (codigo vacio o fuera de `territory`).
    - `ambiguous_candidate` / `excluded_not_eligible` /
      `non_included_not_eligible` / `unresolved_document_level`: el enlace
      mismo no es lo bastante fuerte -- nunca se les asigna comuna.
    """
    out: list[dict[str, Any]] = []
    for link in links:
        base = {
            "project_id": link["project_id"],
            "document_id": link["document_id"],
            "case_mention_id": link.get("case_mention_id"),
            "link_status": link["link_status"],
            "geography_version": GEOGRAPHY_VERSION,
        }
        if link["link_status"] != "verified_direct":
            out.append({
                **base,
                "geography_status": _NOT_ELIGIBLE_STATUS.get(link["link_status"], "unresolved"),
                "codigo_comuna_ine": None,
                "comuna": None,
            })
            continue

        cm = case_mentions_by_id.get(link.get("case_mention_id"))
        comuna_info = resolve_case_mention_comuna(cm, valid_codes)
        if comuna_info is None:
            out.append({**base, "geography_status": "direct_link_no_comuna", "codigo_comuna_ine": None, "comuna": None})
            continue

        out.append({**base, "geography_status": "direct_attribution", **comuna_info})
    return out


def count_projects_per_comuna(attributions: list[dict[str, Any]]) -> dict[str, set[str]]:
    """codigo_comuna_ine -> set(project_id), contando cada proyecto UNA vez
    por comuna sin importar cuantas case_mention/evidencia distintas lo
    respalden ahi (ver caso 'proyecto respaldado en varias noticias' del
    diseno). Solo cuenta filas con geography_status='direct_attribution'."""
    by_comuna: dict[str, set[str]] = defaultdict(set)
    for row in attributions:
        if row.get("geography_status") != "direct_attribution":
            continue
        by_comuna[row["codigo_comuna_ine"]].add(row["project_id"])
    return dict(by_comuna)
