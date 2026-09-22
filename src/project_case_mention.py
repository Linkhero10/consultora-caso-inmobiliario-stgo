#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construye enlaces conservadores proyecto -> mención -> evidencia.

La tabla histórica ``project_mention_resolved`` solo identifica que un
proyecto apareció en un documento. Este módulo agrega una capa candidata que
exige una cita de objeto verificada y una única ``case_mention`` incluida para
considerar que el enlace es directo **según la regla automática v1**. Los
documentos con varias menciones compatibles se conservan como
``ambiguous_direct`` y nunca se promueven silenciosamente a respaldo. Esta
regla no pretende ser la definición final: una futura v2 podría resolver
varias correspondencias inequívocas dentro de un mismo documento.

El módulo no modifica ningún warehouse: sus funciones son puras y el script
de integración que las consume escribe una copia de auditoría separada.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any


def normalize_for_match(value: str) -> str:
    """Normaliza solo para matching exacto por substring; no hace fuzzy match."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches_project(quote_text: str, terms: set[str]) -> bool:
    quote = normalize_for_match(quote_text)
    if not quote:
        return False
    return any(term and (term in quote or quote in term) for term in terms)


def _is_verified(value: Any) -> bool:
    """Interpreta flags SQLite/JSON sin convertir la cadena ``"0"`` en true."""
    return value is True or value == 1 or str(value).strip().lower() in {"1", "true", "yes"}


def _base_row(project_mention: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {
        "project_id": project_mention["project_id"],
        "document_id": project_mention["document_id"],
        "raw_nombre_proyecto": project_mention.get("raw_nombre_proyecto") or "",
        "case_mention_id": None,
        "evidence_id": None,
        "quote_text": None,
        "decision_final_amplio": None,
        "link_status": status,
        "match_method": "verified_object_quote_exact_substring_v1" if status in {"verified_direct", "ambiguous_direct", "excluded_case_mention"} else "none",
        "reason": reason,
    }


def build_project_case_mention_links(
    project_mentions: list[dict[str, Any]],
    case_mentions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    project_aliases: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Devuelve enlaces directos y estados de ambigüedad deterministas.

    ``verified_direct`` es un estado automático conservador de v1: solo
    aparece cuando exactamente una mención incluida del documento tiene una
    cita de objeto verificada que contiene (o está contenida por) un
    nombre/alias del proyecto. Un match en una mención excluida nunca se
    considera respaldo. Que v1 no resuelva un documento multi-caso no implica
    que la relación sea imposible para una revisión humana o una v2.
    """
    project_aliases = project_aliases or {}
    cms_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cm in case_mentions:
        cms_by_doc[cm["document_id"]].append(cm)

    evidence_by_cm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ev in evidence:
        if ev.get("quote_role") != "objeto" or not _is_verified(ev.get("verified")):
            continue
        evidence_by_cm[ev["case_mention_id"]].append(ev)

    rows: list[dict[str, Any]] = []
    for pm in project_mentions:
        terms = {normalize_for_match(pm.get("raw_nombre_proyecto", ""))}
        terms.update(normalize_for_match(alias) for alias in project_aliases.get(pm["project_id"], []))
        terms.discard("")
        include_matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
        excluded_matches: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for cm in cms_by_doc.get(pm["document_id"], []):
            matches = [
                ev for ev in evidence_by_cm.get(cm["case_mention_id"], [])
                if _matches_project(ev.get("quote_text", ""), terms)
            ]
            if not matches:
                continue
            target = include_matches if cm.get("decision_final_amplio") == "include" else excluded_matches
            target[cm["case_mention_id"]].extend(matches)

        if len(include_matches) == 1:
            for case_mention_id, matches in sorted(include_matches.items()):
                cm = next(cm for cm in cms_by_doc[pm["document_id"]] if cm["case_mention_id"] == case_mention_id)
                for ev in sorted(matches, key=lambda item: item["evidence_id"]):
                    row = _base_row(pm, "verified_direct", "una unica case_mention incluida coincide con una cita de objeto verificada")
                    row.update({
                        "case_mention_id": case_mention_id,
                        "evidence_id": ev["evidence_id"],
                        "quote_text": ev.get("quote_text"),
                        "decision_final_amplio": cm.get("decision_final_amplio"),
                    })
                    rows.append(row)
            continue

        if len(include_matches) > 1:
            for case_mention_id, matches in sorted(include_matches.items()):
                cm = next(cm for cm in cms_by_doc[pm["document_id"]] if cm["case_mention_id"] == case_mention_id)
                for ev in sorted(matches, key=lambda item: item["evidence_id"]):
                    row = _base_row(pm, "ambiguous_direct", "mas de una case_mention incluida coincide con la misma evidencia nominal")
                    row.update({
                        "case_mention_id": case_mention_id,
                        "evidence_id": ev["evidence_id"],
                        "quote_text": ev.get("quote_text"),
                        "decision_final_amplio": cm.get("decision_final_amplio"),
                    })
                    rows.append(row)
            continue

        if excluded_matches:
            for case_mention_id, matches in sorted(excluded_matches.items()):
                cm = next(cm for cm in cms_by_doc[pm["document_id"]] if cm["case_mention_id"] == case_mention_id)
                for ev in sorted(matches, key=lambda item: item["evidence_id"]):
                    row = _base_row(pm, "excluded_case_mention", "la coincidencia nominal solo esta respaldada por una case_mention excluida")
                    row.update({
                        "case_mention_id": case_mention_id,
                        "evidence_id": ev["evidence_id"],
                        "quote_text": ev.get("quote_text"),
                        "decision_final_amplio": cm.get("decision_final_amplio"),
                    })
                    rows.append(row)
            continue

        rows.append(_base_row(pm, "document_level_candidate", "el proyecto aparece en el documento pero no hay cita de objeto verificada atribuible de forma directa"))

    return sorted(rows, key=lambda row: (
        row["document_id"], row["project_id"], row["link_status"],
        row["case_mention_id"] or "", row["evidence_id"] or "",
    ))
