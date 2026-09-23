#!/usr/bin/env python3
"""Clasificación LLM de documentos (gate determinista + evidencia verificada).

El gate determinista se aplica en capas: cada capa reutiliza el resultado de la
anterior y agrega una restricción adicional (evidencia literal citada, veto de
inmueble existente sin intervención urbana, suficiencia de evidencia y limpieza
de citas, normalización geográfica conservadora). La frontera de actos
simbólicos/conmemorativos/de nomenclatura excluye explícitamente casos como un
cambio de nombre de calle que no constituye una intervención física real.

Las capas se encadenan por llamada directa de función (cada función pública
llama a la interna que construye sobre ella), no por reescritura de atributos
de módulo en tiempo de ejecución.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_lock import (  # noqa: E402
    LockBusyError,
    StageSkipped,
    acquire_lock,
    read_jsonl_tolerant,
    upstream_stage_is_running,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("classify")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "config" / "classification_schema.json"
PROMPT_PATH = PROJECT_ROOT / "config" / "classifier_prompt.md"
ENV_PATH = PROJECT_ROOT / ".env"
CONTRACT_VERSION = "v5.2.3"

# ---------------------------------------------------------------------------
# Carga del corpus
# ---------------------------------------------------------------------------

CONTENT_DIR = PROJECT_ROOT / "Fuentes" / "fulltext" / "content"
DEDUPE_MANIFEST_PATH = PROJECT_ROOT / "Fuentes" / "fulltext" / "dedupe_manifest.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "clasificacion"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "classifications.jsonl"
REVIEW_ARTIFACT_PATH = PROJECT_ROOT / "Auditoria" / "muestras_control" / "review_sample_classify.json"
DOCUMENTOS_LARGOS_PATH = OUTPUT_DIR / "documentos_largos_apartados.jsonl"
SOCIAL_TRUNCADO_PATH = PROJECT_ROOT / "Fuentes" / "fulltext" / "social_truncado_apartados.jsonl"

MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS_FOR_PROMPT = 30000
MAX_RETRIES = 5
MIN_EVIDENCE_QUOTE_CHARS = 15
MAX_TEST_URLS_WITHOUT_GATE = 100

MODEL = "openai/gpt-5.6-luna"
REASONING_EFFORT = "xhigh"

SOCIAL_TRUNCATION_DOMAINS = {"x.com", "twitter.com", "t.co", "mobile.twitter.com"}
SOCIAL_LOGIN_WALL_MARKERS = (
    "post iniciar sesion registrate",
    "javascript no esta disponible",
)
SOCIAL_SENTENCE_ENDERS = tuple(".!?…\"'”’)]")


def _strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def _is_incomplete_social_post(url: str, text: str) -> str:
    from urllib.parse import urlparse

    domain = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    if domain not in SOCIAL_TRUNCATION_DOMAINS:
        return ""
    stripped = str(text or "").strip()
    if not stripped:
        return "sin_texto"
    normalized = _strip_accents(stripped.lower())
    for marker in SOCIAL_LOGIN_WALL_MARKERS:
        if marker in normalized:
            return "muro_login_capturado_en_vez_del_tuit"
    if stripped[-1] not in SOCIAL_SENTENCE_ENDERS:
        return "texto_cortado_a_mitad_de_frase"
    return ""


def already_set_aside_social_truncated_urls() -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(SOCIAL_TRUNCADO_PATH)}


def set_aside_social_truncated_document(data: dict[str, Any], reason: str) -> None:
    SOCIAL_TRUNCADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "url": data.get("url", ""),
        "char_count": data.get("char_count", 0),
        "motivo": reason,
        "lineage": data.get("lineage"),
        "content_path": data.get("_content_path", ""),
        "text_preview": str(data.get("text", ""))[:200],
        "apartado_at": datetime.now(timezone.utc).isoformat(),
    }
    with SOCIAL_TRUNCADO_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def load_excluded_duplicate_urls() -> set[str]:
    excluded: set[str] = set()
    for rec in read_jsonl_tolerant(DEDUPE_MANIFEST_PATH):
        if rec.get("tipo") == "duplicado_exacto":
            excluded.add(rec.get("url", ""))
    return excluded


def already_set_aside_long_urls() -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(DOCUMENTOS_LARGOS_PATH)}


def set_aside_long_document(data: dict[str, Any]) -> None:
    DOCUMENTOS_LARGOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "url": data.get("url", ""),
        "char_count": data.get("char_count", 0),
        "title": data.get("discovery_title", "") or data.get("title", ""),
        "lineage": data.get("lineage"),
        "content_path": data.get("_content_path", ""),
        "apartado_at": datetime.now(timezone.utc).isoformat(),
        "motivo": f"char_count {data.get('char_count', 0)} > limite {MAX_TEXT_CHARS_FOR_PROMPT}",
    }
    with DOCUMENTOS_LARGOS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def corpus_scope_for_lineage(lineage: dict[str, Any] | None) -> str:
    lineage = lineage or {}
    origins = lineage.get("origins")
    candidates = origins if isinstance(origins, list) and origins else [lineage]
    has_legacy = any(not str(o.get("periodo", "")).strip() or not str(o.get("nivel", "")).strip() for o in candidates)
    has_v2 = any(str(o.get("periodo", "")).strip() and str(o.get("nivel", "")).strip() for o in candidates)
    if has_v2 and has_legacy:
        return "temporal_v2_mixed_legacy"
    if has_v2:
        return "temporal_v2"
    if has_legacy:
        return "legacy_sin_ventana"
    return "unknown"


def load_classifiable_documents(urls_filter: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = load_excluded_duplicate_urls()
    ya_apartados = already_set_aside_long_urls()
    ya_apartados_social = already_set_aside_social_truncated_urls()
    docs = []
    apartados_nuevos = 0
    apartados_sociales_nuevos = 0
    for path in sorted(CONTENT_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Contenido invalido omitido de clasificacion: %s (%s)", path, exc)
            continue
        if not isinstance(data, dict):
            logger.warning("Contenido no-objeto omitido de clasificacion: %s", path)
            continue
        if data.get("char_count", 0) < MIN_TEXT_CHARS:
            continue
        if corpus_scope_for_lineage(data.get("lineage")) == "legacy_sin_ventana":
            continue
        if data.get("url") in excluded:
            continue
        if urls_filter is not None and data.get("url") not in urls_filter:
            continue
        data["_content_path"] = str(path)
        social_reason = _is_incomplete_social_post(data.get("url", ""), data.get("text", ""))
        if social_reason:
            if data.get("url") not in ya_apartados_social:
                set_aside_social_truncated_document(data, social_reason)
                apartados_sociales_nuevos += 1
            continue
        if data.get("char_count", 0) > MAX_TEXT_CHARS_FOR_PROMPT:
            if data.get("url") not in ya_apartados:
                set_aside_long_document(data)
                apartados_nuevos += 1
            continue
        docs.append(data)
    if apartados_nuevos:
        logger.info("Documentos apartados por exceder %d caracteres: %d", MAX_TEXT_CHARS_FOR_PROMPT, apartados_nuevos)
    if apartados_sociales_nuevos:
        logger.info("Posts de X/Twitter apartados por muro de login o truncamiento: %d", apartados_sociales_nuevos)
    return docs


def already_classified_urls(output_path: Path) -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(output_path)}


# ---------------------------------------------------------------------------
# Normalización geográfica: 32 comunas del área de estudio.
# ---------------------------------------------------------------------------

COMUNA_INE_CODES = {
    "Santiago": "13101", "Cerrillos": "13102", "Cerro Navia": "13103", "Conchalí": "13104",
    "El Bosque": "13105", "Estación Central": "13106", "Huechuraba": "13107", "Independencia": "13108",
    "La Cisterna": "13109", "La Florida": "13110", "La Granja": "13111", "La Pintana": "13112",
    "La Reina": "13113", "Las Condes": "13114", "Lo Barnechea": "13115", "Lo Espejo": "13116",
    "Lo Prado": "13117", "Macul": "13118", "Maipú": "13119", "Ñuñoa": "13120",
    "Pedro Aguirre Cerda": "13121", "Peñalolén": "13122", "Providencia": "13123", "Pudahuel": "13124",
    "Quilicura": "13125", "Quinta Normal": "13126", "Recoleta": "13127", "Renca": "13128",
    "San Joaquín": "13129", "San Miguel": "13130", "San Ramón": "13131", "Vitacura": "13132",
}


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.lower().split())


_COMUNA_BY_KEY = {_key(name): code for name, code in COMUNA_INE_CODES.items()}


def derive_ine_code(comuna: str) -> str:
    return _COMUNA_BY_KEY.get(_key(comuna), "")


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _enrich_locations(mention: dict[str, Any]) -> None:
    for location in mention.get("lugares_mencionados", []):
        name = str(location.get("nombre", ""))
        code = derive_ine_code(name) if location.get("tipo") == "comuna" else ""
        location["codigo_comuna_ine"] = code
        location["en_area_estudio"] = "si" if code else ("incierto" if location.get("tipo") in {"comuna", "ciudad", "region"} else "incierto")
    mention["codigo_comuna_ine"] = derive_ine_code(str(mention.get("comuna", "")))


# ---------------------------------------------------------------------------
# Validación de evidencia: verificación de citas literales por arreglos y
# doble alcance (residencial / inmobiliaria urbana amplia).
# ---------------------------------------------------------------------------

RESIDENTIAL_OBJECTS = {
    "edificio_residencial", "ds19", "condominio", "loteo_residencial",
    "uso_mixto_residencial", "instrumento_urbano_residencial",
}
BROAD_OBJECTS = RESIDENTIAL_OBJECTS | {
    "centro_comercial", "edificio_oficinas", "hotel", "proyecto_industrial",
    "equipamiento_urbano", "infraestructura_no_residencial",
    "inmobiliario_privado_no_residencial", "instrumento_urbano_general",
}
BROAD_NON_REAL_ESTATE_OBJECTS = {
    "instrumento_urbano_general", "equipamiento_urbano", "infraestructura_no_residencial",
}
SCOPES = {"residencial", "inmobiliaria_urbana_amplia"}


def quote_flags(quotes: Any, source_text: str) -> tuple[list[bool], bool, bool]:
    values = quotes if isinstance(quotes, list) else []
    cleaned = [str(q).strip() for q in values]
    flags = [bool(q) and len(q) >= MIN_EVIDENCE_QUOTE_CHARS and normalize_text(q) in normalize_text(source_text) for q in cleaned]
    sufficient = bool(flags) and any(flags)
    contract_valid = sufficient and all(flags)
    return flags, sufficient, contract_valid


def _decision_for_scope(results: list[dict[str, Any]]) -> str:
    if not results:
        return "insufficient_content"
    decisions = {str(result.get("decision_final", "uncertain")) for result in results}
    if "include" in decisions:
        return "include"
    if "uncertain" in decisions:
        return "uncertain"
    if "exclude" in decisions:
        return "exclude"
    return "insufficient_content"


def _apply_scope_gate_base(parsed: dict[str, Any], source_text: str, scope: str) -> dict[str, Any]:
    """Verifica evidencia literal citada y aplica el gate de alcance base."""
    if scope not in SCOPES:
        raise ValueError(f"scope no soportado: {scope}")
    result = deepcopy(parsed)
    reasons: list[str] = []
    model_decision = str(parsed.get("decision", "uncertain"))
    action = str(parsed.get("accion_contenciosa", "")).strip().lower()
    action_type = str(parsed.get("tipo_accion_contenciosa", "")).strip().lower()
    object_type = str(parsed.get("tipo_objeto_norm", "")).strip().lower()
    real_estate = str(parsed.get("es_proyecto_inmobiliario", "")).strip().lower()
    residential = str(parsed.get("es_proyecto_vivienda_inmobiliario", "")).strip().lower()
    relation = str(parsed.get("relacion_inmobiliaria_urbana", "")).strip().lower()
    geography = str(parsed.get("precision_geografica", "")).strip().lower()
    depth = str(parsed.get("profundidad_documentacion_caso", "")).strip().lower()
    comuna = str(parsed.get("comuna", "")).strip()

    action_flags, action_ok, action_contract = quote_flags(parsed.get("evidencia_accion_quotes"), source_text)
    object_flags, object_ok_evidence, object_contract = quote_flags(parsed.get("evidencia_objeto_quotes"), source_text)
    geo_flags, geo_ok_evidence, geo_contract = quote_flags(parsed.get("evidencia_geografica_quotes"), source_text)
    result["decision_modelo"] = model_decision
    result["scope"] = scope
    result["evidence_action_quotes_verified"] = action_flags
    result["evidence_object_quotes_verified"] = object_flags
    result["evidence_geo_quotes_verified"] = geo_flags
    result["evidence_action_verified"] = action_ok
    result["evidence_object_verified"] = object_ok_evidence
    result["evidence_geo_verified"] = geo_ok_evidence

    if model_decision != "include":
        result["decision_final"] = model_decision
        result["gate_reasons"] = reasons
        return result

    if action != "confirmada" or action_type in {"", "ninguna", "incierta"}:
        reasons.append("sin_accion_contenciosa" if action in {"no", "ninguna"} else "accion_contenciosa_incierta")

    object_ok = object_type in (RESIDENTIAL_OBJECTS if scope == "residencial" else BROAD_OBJECTS)
    if scope == "residencial":
        object_ok = object_ok and residential == "si"
    else:
        object_ok = object_ok and (real_estate == "si" or object_type in BROAD_NON_REAL_ESTATE_OBJECTS)
    if scope == "inmobiliaria_urbana_amplia" and relation == "ocupacion_propiedad_sin_desarrollo":
        object_ok = False
        reasons.append("objeto_existente_sin_vinculo_urbano")
    if not object_ok and "objeto_existente_sin_vinculo_urbano" not in reasons:
        if scope == "residencial" and real_estate == "si" and residential == "no":
            reasons.append("objeto_fuera_de_alcance_residencial")
        elif object_type in {"", "none", "objeto_no_determinado"} or real_estate in {"", "incierto"}:
            reasons.append("objeto_no_determinado")
        else:
            reasons.append("objeto_no_admisible")

    if geography == "fuera_de_area":
        reasons.append("fuera_del_area_geografica")
    elif geography in {"", "ambigua", "provincia_general"}:
        reasons.append("geografia_incierta")
    elif comuna and _key(comuna) not in _COMUNA_BY_KEY and geography in {"proyecto_exacto", "sector_barrio", "comuna"}:
        reasons.append("fuera_del_area_geografica")

    if depth == "mencion_tangencial":
        reasons.append("mencion_tangencial")
    elif depth not in {"caso_principal", "caso_secundario_documentado"}:
        reasons.append("caso_insuficientemente_documentado")

    for label, sufficient, valid in (("accion", action_ok, action_contract), ("objeto", object_ok_evidence, object_contract), ("geografica", geo_ok_evidence, geo_contract)):
        if not sufficient:
            reasons.append(f"evidencia_{label}_no_verificada")
        elif not valid:
            reasons.append(f"evidencia_{label}_contrato_invalido")

    hard_exclude = {"sin_accion_contenciosa", "objeto_fuera_de_alcance_residencial", "objeto_no_admisible", "objeto_existente_sin_vinculo_urbano", "fuera_del_area_geografica", "mencion_tangencial"}
    result["decision_final"] = "exclude" if hard_exclude.intersection(reasons) else ("uncertain" if reasons else "include")
    result["gate_reasons"] = reasons
    result["gate_evaluation"] = {
        "action": action == "confirmada" and action_type not in {"", "ninguna", "incierta"},
        "object": object_ok,
        "geography": geography not in {"fuera_de_area", "", "ambigua", "provincia_general"},
        "depth": depth in {"caso_principal", "caso_secundario_documentado"},
        "evidence_action": action_ok and action_contract,
        "evidence_object": object_ok_evidence and object_contract,
        "evidence_geo": geo_ok_evidence and geo_contract,
    }
    return result


# ---------------------------------------------------------------------------
# Gate de alcance: veto de inmueble existente sin intervención urbana formal.
# ---------------------------------------------------------------------------

def _existing_property_without_urban_intervention(mention: dict) -> bool:
    relation = str(mention.get("relacion_inmobiliaria_urbana", "")).strip().lower()
    conflict = str(mention.get("tipo_conflicto_norm", "")).strip().lower()
    legal = str(mention.get("via_legal_norm", "")).strip().lower()
    return (
        relation == "inmueble_existente_relevancia_urbana"
        and conflict == "ocupacion_propiedad"
        and legal in {"", "none", "sin_via_identificada", "incierta"}
    )


def _apply_scope_gate_v2(parsed: dict, source_text: str, scope: str) -> dict:
    """Aplica el veto de inmueble existente sin intervención urbana sobre el gate base."""
    result = _apply_scope_gate_base(parsed, source_text, scope)
    if parsed.get("decision") == "include" and _existing_property_without_urban_intervention(parsed):
        reasons = list(result.get("gate_reasons", []))
        reason = "inmueble_existente_sin_intervencion_urbana_formal"
        if reason not in reasons:
            reasons.append(reason)
        result["gate_reasons"] = reasons
        result["decision_final"] = "exclude"
        evaluation = dict(result.get("gate_evaluation", {}))
        evaluation["object"] = False
        result["gate_evaluation"] = evaluation
    return result


# ---------------------------------------------------------------------------
# Gate de alcance: separa suficiencia de evidencia y limpieza de citas;
# excepción de objeto amplio sin subtipo.
# ---------------------------------------------------------------------------

_CONTRACT_REASON_BY_LABEL = {
    "accion": "evidencia_accion_contrato_invalido",
    "objeto": "evidencia_objeto_contrato_invalido",
    "geografica": "evidencia_geografica_contrato_invalido",
}


def _quote_quality(parsed: dict, source_text: str) -> dict:
    categories = {
        "accion": "evidencia_accion_quotes",
        "objeto": "evidencia_objeto_quotes",
        "geografica": "evidencia_geografica_quotes",
    }
    quality: dict[str, dict] = {}
    for label, key in categories.items():
        flags, sufficient, clean = quote_flags(parsed.get(key), source_text)
        quality[label] = {
            "flags": flags,
            "sufficient": sufficient,
            "fully_clean": clean,
            "invalid_count": sum(not flag for flag in flags),
        }
    category_values = [quality[label] for label in categories]
    quality["all_sufficient"] = all(item["sufficient"] for item in category_values)
    quality["all_fully_clean"] = all(item["fully_clean"] for item in category_values)
    return quality


def _broad_unknown_object_is_admissible(parsed: dict, quality: dict) -> bool:
    relation = str(parsed.get("relacion_inmobiliaria_urbana", "")).strip().lower()
    return (
        str(parsed.get("tipo_objeto_norm", "")).strip().lower() == "objeto_no_determinado"
        and str(parsed.get("es_proyecto_inmobiliario", "")).strip().lower() == "si"
        and relation in {"desarrollo_proyecto", "transformacion_regulacion_uso", "inmueble_existente_relevancia_urbana"}
        and quality["objeto"]["sufficient"]
        and quality["accion"]["sufficient"]
        and quality["geografica"]["sufficient"]
        and bool(str(parsed.get("tipo_objeto_raw", "")).strip())
    )


def _apply_scope_gate_v3(parsed: dict, source_text: str, scope: str) -> dict:
    """Aplica suficiencia/limpieza de citas y la excepción de objeto amplio sobre el gate anterior."""
    if scope not in SCOPES:
        raise ValueError(f"scope no soportado: {scope}")

    result = _apply_scope_gate_v2(parsed, source_text, scope)
    quality = _quote_quality(parsed, source_text)
    result["evidence_action_quotes_verified"] = quality["accion"]["flags"]
    result["evidence_object_quotes_verified"] = quality["objeto"]["flags"]
    result["evidence_geo_quotes_verified"] = quality["geografica"]["flags"]
    result["evidence_action_verified"] = quality["accion"]["sufficient"]
    result["evidence_object_verified"] = quality["objeto"]["sufficient"]
    result["evidence_geo_verified"] = quality["geografica"]["sufficient"]
    result["case_evidence_sufficient"] = {
        "action": quality["accion"]["sufficient"],
        "object": quality["objeto"]["sufficient"],
        "geography": quality["geografica"]["sufficient"],
        "all": quality["all_sufficient"],
    }
    result["quote_set_fully_clean"] = {
        "action": quality["accion"]["fully_clean"],
        "object": quality["objeto"]["fully_clean"],
        "geography": quality["geografica"]["fully_clean"],
        "all": quality["all_fully_clean"],
    }
    result["invalid_quote_counts"] = {
        label: quality[label]["invalid_count"] for label in ("accion", "objeto", "geografica")
    }
    result["quality_flags"] = [
        f"{label}_quote_set_not_fully_clean"
        for label in ("accion", "objeto", "geografica")
        if quality[label]["sufficient"] and not quality[label]["fully_clean"]
    ]

    if str(parsed.get("decision", "uncertain")) != "include":
        return result

    reasons = [
        reason
        for reason in result.get("gate_reasons", [])
        if reason not in _CONTRACT_REASON_BY_LABEL.values()
    ]

    if "inmueble_existente_sin_intervencion_urbana_formal" in reasons:
        result["gate_reasons"] = reasons
        return result

    object_exception = scope == "inmobiliaria_urbana_amplia" and _broad_unknown_object_is_admissible(parsed, quality)
    if object_exception:
        reasons = [reason for reason in reasons if reason != "objeto_no_determinado"]

    hard_exclude = {
        "sin_accion_contenciosa",
        "objeto_fuera_de_alcance_residencial",
        "objeto_no_admisible",
        "objeto_existente_sin_vinculo_urbano",
        "fuera_del_area_geografica",
        "mencion_tangencial",
    }
    result["decision_final"] = "exclude" if hard_exclude.intersection(reasons) else ("uncertain" if reasons else "include")
    result["gate_reasons"] = reasons
    evaluation = dict(result.get("gate_evaluation", {}))
    evaluation["evidence_action_sufficient"] = quality["accion"]["sufficient"]
    evaluation["evidence_object_sufficient"] = quality["objeto"]["sufficient"]
    evaluation["evidence_geo_sufficient"] = quality["geografica"]["sufficient"]
    if object_exception:
        evaluation["object"] = True
        result["object_gate_exception"] = "broad_explicit_project_without_subtype"
    result["gate_evaluation"] = evaluation
    return result


# ---------------------------------------------------------------------------
# Gate de alcance: normalización geográfica conservadora (comunas compuestas,
# citas geográficas cortas).
# ---------------------------------------------------------------------------

def _split_comuna_names(value: str) -> list[str]:
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
            names.add(_key(name))
            derived = derive_ine_code(name)
            if derived:
                codes.add(derived)
        if code in set(COMUNA_INE_CODES.values()):
            codes.add(code)
    for name in _split_comuna_names(str(parsed.get("comuna", ""))):
        code = derive_ine_code(name)
        if code:
            names.add(_key(name))
            codes.add(code)
    return names, codes


def _geography_is_in_area(parsed: dict[str, Any]) -> bool:
    precision = str(parsed.get("precision_geografica", "")).strip().lower()
    if precision == "fuera_de_area":
        return False
    names, codes = _location_names_and_codes(parsed)
    explicit_comuna = _split_comuna_names(str(parsed.get("comuna", "")))
    if explicit_comuna:
        known = [derive_ine_code(name) for name in explicit_comuna]
        if any(code for code in known):
            return True
        return bool(codes)
    return bool(codes or names)


def _short_geography_quote_flags(parsed: dict[str, Any], source_text: str) -> tuple[list[bool], bool]:
    quotes = parsed.get("evidencia_geografica_quotes")
    values = quotes if isinstance(quotes, list) else []
    normalized_source = normalize_text(source_text)
    place_names = set()
    for location in parsed.get("lugares_mencionados", []) or []:
        if isinstance(location, dict):
            name = str(location.get("nombre", "")).strip()
            if name:
                place_names.add(_key(name))
    place_names.update(_key(name) for name in _split_comuna_names(str(parsed.get("comuna", ""))))
    if len(str(source_text or "")) < 500:
        return [False for _ in values], False
    area_anchor = _geography_is_in_area(parsed)
    flags: list[bool] = []
    for raw in values:
        quote = str(raw).strip()
        literal = bool(quote) and normalize_text(quote) in normalized_source
        anchored = _key(quote) in place_names
        flags.append(bool(literal and anchored and area_anchor))
    return flags, bool(flags) and any(flags)


def _quote_quality_v4(parsed: dict[str, Any], source_text: str) -> dict[str, dict[str, Any]]:
    quality = _quote_quality(parsed, source_text)
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
        object_exception = scope == "inmobiliaria_urbana_amplia" and _broad_unknown_object_is_admissible(parsed, quality)
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
    """Gate de alcance completo -- envuelve las capas anteriores con
    normalización geográfica conservadora. Función pública usada por el
    resto del pipeline."""
    result = _apply_scope_gate_v3(parsed, source_text, scope)
    quality = _quote_quality_v4(parsed, source_text)
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
        "decision_residencial": _decision_for_scope(residential),
        "decision_inmobiliaria_urbana_amplia": _decision_for_scope(broad),
        "decision_documento": _decision_for_scope(broad),
    }


# ---------------------------------------------------------------------------
# Llamada al modelo
# ---------------------------------------------------------------------------

def validate_classification_payload(parsed: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
    except jsonschema.ValidationError as exc:
        logger.warning("Respuesta invalida contra schema: %s", exc.message[:240])
        return False
    return True


def classify_document(doc: dict[str, Any], api_key: str, system_prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve {'parsed':..., ...} en exito, o {'error': '<codigo>'} en fallo."""
    text = str(doc.get("text", ""))[:MAX_TEXT_CHARS_FOR_PROMPT]
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"TITULO: {doc.get('title') or doc.get('discovery_title', '')}\nURL: {doc.get('url', '')}\n\nTEXTO DEL ARTICULO:\n{text}"},
        ],
        "reasoning": {"effort": REASONING_EFFORT},
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if response.status_code == 429:
                if attempt == MAX_RETRIES:
                    return {"error": "rate_limited_max_retries"}
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            parsed = json.loads(message["content"])
            if not validate_classification_payload(parsed, schema):
                return {"error": "schema_validation_failed", "usage": data.get("usage", {})}
            return {
                "parsed": parsed,
                "usage": data.get("usage", {}),
                "reasoning": message.get("reasoning"),
                "reasoning_details": message.get("reasoning_details"),
                "raw_finish_reason": data["choices"][0].get("finish_reason"),
            }
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_RETRIES:
                return {"error": f"connection_error_max_retries: {exc.__class__.__name__}"}
            time.sleep((2 ** attempt) + random.uniform(0, 1))
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            return {"error": f"response_parse_error: {exc.__class__.__name__}"}
    return {"error": "unknown_error_retry_loop_exhausted"}


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Gate de liberación de producción -- hash-pinning: verifica que el artefacto
# de aprobación corresponda al prompt/schema/script ACTUALES, no solo a 3
# booleanos.
# ---------------------------------------------------------------------------

def classification_release_reasons(review_artifact: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    policy = review_artifact.get("review_policy", review_artifact)
    if review_artifact.get("status") != "aprobado_revision_humana":
        reasons.append("status != aprobado_revision_humana")
    if policy.get("human_review_completed") is not True:
        reasons.append("review_policy.human_review_completed != true")
    if policy.get("production_allowed") is not True:
        reasons.append("review_policy.production_allowed != true")
    if reasons:
        return reasons

    fingerprint = review_artifact.get("contract_fingerprint")
    if not isinstance(fingerprint, dict):
        return ["artefacto sin contract_fingerprint -- no se puede verificar que autorice el contrato vigente"]

    checks = [
        ("prompt", PROMPT_PATH, fingerprint.get("prompt_path"), fingerprint.get("prompt_sha256")),
        ("schema", SCHEMA_PATH, fingerprint.get("schema_path"), fingerprint.get("schema_sha256")),
        ("script de entrada", Path(sys.argv[0]) if sys.argv else Path(__file__), fingerprint.get("entry_script_path"), fingerprint.get("entry_script_sha256")),
        ("gate base (classify.py)", Path(__file__), fingerprint.get("base_gate_path"), fingerprint.get("base_gate_sha256")),
    ]
    extra_files = fingerprint.get("extra_gate_files")
    for entry in (extra_files if isinstance(extra_files, list) else []):
        if not isinstance(entry, dict):
            reasons.append("contract_fingerprint.extra_gate_files tiene una entrada invalida (no es un objeto)")
            continue
        label = str(entry.get("label") or entry.get("path") or "archivo adicional")
        declared_path = entry.get("path")
        declared_hash = entry.get("sha256")
        if not declared_path or not declared_hash:
            reasons.append(f"contract_fingerprint incompleto para {label} (falta path o hash declarado)")
            continue
        checks.append((label, PROJECT_ROOT / declared_path, declared_path, declared_hash))

    for label, current_path, declared_path, declared_hash in checks:
        if not declared_path or not declared_hash:
            reasons.append(f"contract_fingerprint incompleto para {label} (falta path o hash declarado)")
            continue
        current_rel = _relpath(current_path)
        if current_rel != str(declared_path).replace("\\", "/"):
            reasons.append(f"{label}: ruta vigente ({current_rel}) no coincide con la declarada en el artefacto ({declared_path})")
            continue
        current_hash = _sha256_file(current_path)
        if current_hash is None:
            reasons.append(f"{label}: no se pudo leer el archivo vigente en {current_rel}")
        elif current_hash != declared_hash:
            reasons.append(f"{label}: hash vigente ({current_hash[:12]}...) no coincide con el declarado en el artefacto ({str(declared_hash)[:12]}...) -- el contrato cambio desde que se aprobo")

    review_sample_path = fingerprint.get("human_review_sample_path")
    declared_sample_hash = fingerprint.get("human_review_sample_sha256")
    if review_sample_path and declared_sample_hash:
        sample_full_path = PROJECT_ROOT / review_sample_path
        current_sample_hash = _sha256_file(sample_full_path)
        if current_sample_hash is None:
            reasons.append(f"muestra de revision humana: no se pudo leer {review_sample_path}")
        elif current_sample_hash != declared_sample_hash:
            reasons.append("muestra de revision humana: el archivo cambio desde que se aprobo el artefacto (hash no coincide)")
    else:
        reasons.append("contract_fingerprint incompleto: falta human_review_sample_path/sha256")

    return reasons


def classification_release_allowed(review_artifact: dict[str, Any]) -> bool:
    return not classification_release_reasons(review_artifact)


# ---------------------------------------------------------------------------
# Procesamiento del resultado y ejecución
# ---------------------------------------------------------------------------

def postprocess_result(doc: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parsed = deepcopy(result["parsed"])
    for mention in parsed.get("case_mentions", []):
        _enrich_locations(mention)
    source_text = str(doc.get("text", ""))
    derived = derive_document_decisions(parsed.get("case_mentions", []), source_text)
    record = {
        "url": doc.get("url"),
        "lineage": doc.get("lineage", {}),
        "content_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "content_char_count": len(source_text),
        "corpus_scope": "temporal_v2",
        "contract_version": CONTRACT_VERSION,
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "reasoning": result.get("reasoning"),
        "reasoning_details": result.get("reasoning_details"),
        "usage": result.get("usage", {}),
        "decision_modelo": parsed.get("decision"),
        **parsed,
        **derived,
    }
    return str(record["decision_documento"]), record


def _run(args: argparse.Namespace) -> int:
    urls_filter = {line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if line.strip()} if args.urls_file else None
    bounded_urls_file = bool(urls_filter) and len(urls_filter) <= MAX_TEST_URLS_WITHOUT_GATE
    is_test = bool(bounded_urls_file or args.dry_run)
    for stage in ("fulltext_acquisition_v2", "dedupe_fulltext"):
        if upstream_stage_is_running(stage) and not is_test:
            raise StageSkipped(3, f"{stage} activo; se bloquea produccion")
    if not is_test:
        try:
            artifact = json.loads(REVIEW_ARTIFACT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageSkipped(4, f"no se pudo leer el gate de revision: {exc}") from exc
        blocking_reasons = classification_release_reasons(artifact)
        if blocking_reasons:
            raise StageSkipped(4, "gate humano pendiente: " + "; ".join(blocking_reasons))
    env = load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    docs = load_classifiable_documents(urls_filter=urls_filter)
    done = already_classified_urls(output_path)
    pending = [doc for doc in docs if doc.get("url") not in done]
    if args.limit:
        pending = pending[:args.limit]
    if args.dry_run:
        sample = [doc.get("url", "") for doc in pending[:5]]
        logger.info("DRY RUN (sin llamadas a la API): %d documentos pendientes. Muestra: %s", len(pending), sample)
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    errors_path = output_path.with_name(output_path.stem + ".errors.jsonl")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    manifest_path = output_path.with_name(f"{output_path.stem}.run_manifest.{run_id}.json")
    # sys.argv[0] no siempre es un archivo legible: bajo ciertos arneses de
    # invocacion (algunos wrappers de pytest, interpretes embebidos) puede
    # venir vacio o apuntar a un launcher que no es un archivo real, lo que
    # dejaba entry_script_sha256=None en silencio (_sha256_file solo atrapa
    # OSError). Se cae a Path(__file__) -- el propio modulo, ya usado como
    # fallback y como base_gate_sha256 -- en vez de dejar el campo vacio.
    _entry_script_path = Path(sys.argv[0]) if sys.argv else Path(__file__)
    if not _entry_script_path.is_file():
        _entry_script_path = Path(__file__)
    run_manifest = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "output_path": str(output_path),
        "errors_path": str(errors_path),
        "is_test": is_test,
        "prompt_path": str(PROMPT_PATH),
        "prompt_sha256": _sha256_file(PROMPT_PATH),
        "schema_path": str(SCHEMA_PATH),
        "schema_sha256": _sha256_file(SCHEMA_PATH),
        "entry_script_path": str(_entry_script_path),
        "entry_script_sha256": _sha256_file(_entry_script_path),
        "base_gate_path": str(Path(__file__)),
        "base_gate_sha256": _sha256_file(Path(__file__)),
        "workers": args.workers,
        "pending_esperados": len(pending),
        "status": "running",
    }
    manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    written = 0
    error_count = 0
    total_cost = 0.0
    with output_path.open("a", encoding="utf-8") as handle, errors_path.open("a", encoding="utf-8") as errors_handle:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(classify_document, doc, api_key, prompt, schema): doc for doc in pending}
            for future in as_completed(futures):
                doc = futures[future]
                url = doc.get("url", "")
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"unhandled_exception: {exc.__class__.__name__}: {exc}"}
                if result is not None and "parsed" in result:
                    try:
                        _, record = postprocess_result(doc, result)
                    except Exception as exc:  # noqa: BLE001
                        failed_cost = float((result.get("usage") or {}).get("cost", 0) or 0)
                        total_cost += failed_cost
                        reason = f"postprocess_result_exception: {exc.__class__.__name__}: {exc}"
                        logger.warning("Fallo de postprocesamiento para %s: %s", url[:80], reason)
                        errors_handle.write(json.dumps({
                            "url": url, "error": reason, "lineage": doc.get("lineage", {}),
                            "cost_incurred_usd": failed_cost, "run_id": run_id,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False) + "\n")
                        errors_handle.flush()
                        os.fsync(errors_handle.fileno())
                        error_count += 1
                        continue
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    written += 1
                    total_cost += float((result.get("usage") or {}).get("cost", 0) or 0)
                else:
                    reason = (result or {}).get("error", "unknown_error_result_none")
                    failed_cost = float((result or {}).get("usage", {}).get("cost", 0) or 0)
                    total_cost += failed_cost
                    logger.warning("Fallo no recuperable para %s: %s", url[:80], reason)
                    errors_handle.write(json.dumps({
                        "url": url, "error": reason, "lineage": doc.get("lineage", {}),
                        "cost_incurred_usd": failed_cost, "run_id": run_id,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False) + "\n")
                    errors_handle.flush()
                    os.fsync(errors_handle.fileno())
                    error_count += 1
    esperados = len(pending)
    counts_consistent = (written + error_count == esperados)
    if not counts_consistent:
        logger.error(
            "INCONSISTENCIA DE CONTEO: esperados=%d != escritos(%d)+errores(%d)=%d -- revisar %s y %s",
            esperados, written, error_count, written + error_count, output_path, errors_path,
        )
    logger.info(
        "Clasificacion completada: %d escritos, %d errores, %d esperados -- %s (errores en %s)",
        written, error_count, esperados, output_path, errors_path,
    )
    run_manifest.update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "written": written,
        "errors": error_count,
        "esperados": esperados,
        "counts_consistent": counts_consistent,
        "total_cost_usd": round(total_cost, 6),
        "status": "completed" if counts_consistent else "completed_with_count_mismatch",
    })
    manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificación de documentos con gate determinista y frontera de actos simbólicos")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    _urls_for_detail = {l.strip() for l in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if l.strip()} if args.urls_file else None
    _bounded_for_detail = bool(_urls_for_detail) and len(_urls_for_detail) <= MAX_TEST_URLS_WITHOUT_GATE
    detail = {
        "output_path": str(Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH),
        "es_produccion": not bool(_bounded_for_detail or args.dry_run),
        "schema_version": "v5.2.3",
        "prompt_version": "v5.2.4",
        "gate_version": "v5.2.2",
    }
    try:
        with acquire_lock("classify", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
