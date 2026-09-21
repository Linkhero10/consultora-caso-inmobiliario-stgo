#!/usr/bin/env python3
"""Gate v5.2.2: normalización geográfica conservadora y auditable.

No cambia las respuestas del modelo. Corrige dos fallas deterministas de
v5.2.1: comunas compuestas de Santiago y citas geográficas cortas pero
literales. La decisión conserva la separación entre `decision_modelo` y
`decision_final`; toda salida de producción sigue bloqueada por revisión
humana.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify_v5_2_1 as previous  # noqa: E402
import classify_v5_1 as v51  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "Trabajo" / "config" / "classification_schema_v5_2_3.json"
PROMPT_PATH = PROJECT_ROOT / "Trabajo" / "prompts" / "classifier_system_v5_2_3.md"
CONTRACT_VERSION = "v5.2.2"


def _split_comuna_names(value: str) -> list[str]:
    """Separa una etiqueta compuesta sin convertir barrios en comunas."""
    text = str(value or "").strip()
    if not text:
        return []
    text = re.sub(r"\s+(?:y|e)\s+", ";", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[;,/]\s*", ";", text)
    return [part.strip() for part in text.split(";") if part.strip()]


def _location_names_and_codes(parsed: dict[str, Any]) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    codes: set[str] = set()
    for location in parsed.get("lugares_mencionados", []) or []:
        if not isinstance(location, dict) or location.get("tipo") != "comuna":
            continue
        name = str(location.get("nombre", "")).strip()
        code = str(location.get("codigo_comuna_ine", "")).strip()
        if name:
            names.add(v51._key(name))
            derived = v51.derive_ine_code(name)
            if derived:
                codes.add(derived)
        if code in set(v51.COMUNA_INE_CODES.values()):
            codes.add(code)
    for name in _split_comuna_names(str(parsed.get("comuna", ""))):
        code = v51.derive_ine_code(name)
        if code:
            names.add(v51._key(name))
            codes.add(code)
    return names, codes


def _geography_is_in_area(parsed: dict[str, Any]) -> bool:
    precision = str(parsed.get("precision_geografica", "")).strip().lower()
    if precision == "fuera_de_area":
        return False
    names, codes = _location_names_and_codes(parsed)
    explicit_comuna = _split_comuna_names(str(parsed.get("comuna", "")))
    if explicit_comuna:
        known = [v51.derive_ine_code(name) for name in explicit_comuna]
        if any(code for code in known):
            # Al menos una comuna explícita es del área; las etiquetas
            # compuestas ("Santiago y Recoleta") son una sola mención.
            return True
        return bool(codes)
    return bool(codes or names)


def _short_geography_quote_flags(parsed: dict[str, Any], source_text: str) -> tuple[list[bool], bool]:
    """Acepta solo citas cortas literales vinculadas a lugares declarados."""
    quotes = parsed.get("evidencia_geografica_quotes")
    values = quotes if isinstance(quotes, list) else []
    normalized_source = v51.normalize_text(source_text)
    place_names = set()
    for location in parsed.get("lugares_mencionados", []) or []:
        if isinstance(location, dict):
            name = str(location.get("nombre", "")).strip()
            if name:
                place_names.add(v51._key(name))
    place_names.update(v51._key(name) for name in _split_comuna_names(str(parsed.get("comuna", ""))))
    # Una publicación extremadamente breve puede contener el nombre de una
    # comuna pero no documentar el caso. El fallback de citas cortas solo se
    # permite con una fuente sustantiva; las citas geográficas largas siguen
    # funcionando con el contrato v5.2.1 sin este umbral.
    if len(str(source_text or "")) < 500:
        return [False for _ in values], False
    area_anchor = _geography_is_in_area(parsed)
    flags: list[bool] = []
    for raw in values:
        quote = str(raw).strip()
        literal = bool(quote) and v51.normalize_text(quote) in normalized_source
        anchored = v51._key(quote) in place_names
        flags.append(bool(literal and anchored and area_anchor))
    return flags, bool(flags) and any(flags)


def _quote_quality(parsed: dict[str, Any], source_text: str) -> dict[str, dict[str, Any]]:
    quality = previous._quote_quality(parsed, source_text)
    geo_flags, geo_short_ok = _short_geography_quote_flags(parsed, source_text)
    if geo_short_ok:
        quality["geografica"] = {
            "flags": geo_flags,
            "sufficient": True,
            "fully_clean": all(geo_flags),
            "invalid_count": sum(not flag for flag in geo_flags),
        }
        quality["short_geography_quote_accepted"] = True
    else:
        quality["short_geography_quote_accepted"] = False
    quality["all_sufficient"] = all(quality[label]["sufficient"] for label in ("accion", "objeto", "geografica"))
    quality["all_fully_clean"] = all(quality[label]["fully_clean"] for label in ("accion", "objeto", "geografica"))
    return quality


def _reconcile_reasons(result: dict[str, Any], parsed: dict[str, Any], quality: dict[str, Any], scope: str) -> dict[str, Any]:
    reasons = list(result.get("gate_reasons", []))
    if _geography_is_in_area(parsed) and str(parsed.get("precision_geografica", "")).lower() != "fuera_de_area":
        reasons = [reason for reason in reasons if reason != "fuera_del_area_geografica"]
    if quality["geografica"]["sufficient"]:
        reasons = [reason for reason in reasons if reason != "evidencia_geografica_no_verificada"]

    if str(parsed.get("decision", "uncertain")) == "include":
        object_exception = scope == "inmobiliaria_urbana_amplia" and previous._broad_unknown_object_is_admissible(parsed, quality)
        if object_exception:
            reasons = [reason for reason in reasons if reason != "objeto_no_determinado"]
            result["object_gate_exception"] = "broad_explicit_project_without_subtype"
        hard_exclude = {
            "sin_accion_contenciosa",
            "objeto_fuera_de_alcance_residencial",
            "objeto_no_admisible",
            "objeto_existente_sin_vinculo_urbano",
            "fuera_del_area_geografica",
            "mencion_tangencial",
        }
        result["decision_final"] = "exclude" if hard_exclude.intersection(reasons) else ("uncertain" if reasons else "include")
        evaluation = dict(result.get("gate_evaluation", {}))
        evaluation["geography"] = _geography_is_in_area(parsed)
        evaluation["evidence_geo_sufficient"] = quality["geografica"]["sufficient"]
        if object_exception:
            evaluation["object"] = True
        result["gate_evaluation"] = evaluation
    result["gate_reasons"] = reasons
    return result


def apply_scope_gate(parsed: dict[str, Any], source_text: str, scope: str) -> dict[str, Any]:
    result = previous.apply_scope_gate(parsed, source_text, scope)
    quality = _quote_quality(parsed, source_text)
    result["evidence_geo_quotes_verified"] = quality["geografica"]["flags"]
    result["evidence_geo_verified"] = quality["geografica"]["sufficient"]
    result["short_geography_quote_accepted"] = quality["short_geography_quote_accepted"]
    result["case_evidence_sufficient"] = dict(result.get("case_evidence_sufficient", {}))
    result["case_evidence_sufficient"]["geography"] = quality["geografica"]["sufficient"]
    result["case_evidence_sufficient"]["all"] = quality["all_sufficient"]
    result["quote_set_fully_clean"] = dict(result.get("quote_set_fully_clean", {}))
    result["quote_set_fully_clean"]["geography"] = quality["geografica"]["fully_clean"]
    result["quote_set_fully_clean"]["all"] = quality["all_fully_clean"]
    result["invalid_quote_counts"] = dict(result.get("invalid_quote_counts", {}))
    result["invalid_quote_counts"]["geografica"] = quality["geografica"]["invalid_count"]
    result["quality_flags"] = [
        flag for flag in result.get("quality_flags", [])
        if not flag.startswith("geografica_quote_set_not_fully_clean")
    ]
    if quality["geografica"]["sufficient"] and not quality["geografica"]["fully_clean"]:
        result["quality_flags"].append("geografica_quote_set_not_fully_clean")
    return _reconcile_reasons(result, parsed, quality, scope)


def derive_document_decisions(mentions: list[dict[str, Any]], source_text: str) -> dict[str, Any]:
    processed, residential, broad = [], [], []
    for mention in mentions:
        res = apply_scope_gate(mention, source_text, "residencial")
        wide = apply_scope_gate(mention, source_text, "inmobiliaria_urbana_amplia")
        item = deepcopy(mention)
        item["gate_residencial"] = res
        item["gate_inmobiliaria_urbana_amplia"] = wide
        processed.append(item)
        residential.append(res)
        broad.append(wide)
    return {
        "case_mentions": processed,
        "decision_residencial": v51._decision_for_scope(residential),
        "decision_inmobiliaria_urbana_amplia": v51._decision_for_scope(broad),
        "decision_documento": v51._decision_for_scope(broad),
    }


def postprocess_result(doc: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parsed = deepcopy(result["parsed"])
    for mention in parsed.get("case_mentions", []):
        v51._enrich_locations(mention)
    derived = derive_document_decisions(parsed.get("case_mentions", []), str(doc.get("text", "")))
    record = {
        "url": doc.get("url"),
        "lineage": doc.get("lineage", {}),
        "corpus_scope": "temporal_v2",
        "contract_version": CONTRACT_VERSION,
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "model": previous.MODEL,
        "reasoning_effort": previous.REASONING_EFFORT,
        "reasoning": result.get("reasoning"),
        "reasoning_details": result.get("reasoning_details"),
        "usage": result.get("usage", {}),
        "decision_modelo": parsed.get("decision"),
        **parsed,
        **derived,
    }
    return str(record["decision_documento"]), record


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificación v5.2.2 con gate geográfico corregido")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    # Reutiliza el ejecutor probado de v5.2.1, pero cambia prompt/schema,
    # postprocesamiento y lock en este proceso aislado.
    previous.PROMPT_PATH = PROMPT_PATH
    previous.SCHEMA_PATH = SCHEMA_PATH
    previous.postprocess_result = postprocess_result
    previous.CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5_2_2" / "classifications.jsonl"
    detail = {
        "output_path": str(Path(args.output_file) if args.output_file else previous.CLASSIFICATIONS_PATH),
        "es_produccion": not bool(args.output_file or args.urls_file or args.dry_run),
        "schema_version": "v5.2.3",
        "gate_version": CONTRACT_VERSION,
    }
    try:
        with previous.acquire_lock("classify_v5_2_2", detail=detail):
            return previous._run(args)
    except previous.LockBusyError as exc:
        previous.logger.info(str(exc))
        return 2
    except previous.StageSkipped as exc:
        previous.logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
