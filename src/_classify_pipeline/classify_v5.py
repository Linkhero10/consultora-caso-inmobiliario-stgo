#!/usr/bin/env python3
"""Gate determinista y contrato candidato v5.

La unidad de análisis ya no es el documento completo sino cada mención de
caso. El módulo mantiene dos vistas: residencial e inmobiliaria/urbana amplia.
La ejecución contra OpenRouter se incorporará después del piloto local; estas
funciones son puras y se prueban sin red.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_luna import (  # noqa: E402
    already_classified_urls,
    load_classifiable_documents,
    load_env,
    read_jsonl_tolerant,
)
from pipeline_lock import acquire_lock, LockBusyError, StageSkipped, upstream_stage_is_running  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("classify_v5")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "src" / "_classify_pipeline" / "schema_stage_v5.json"
PROMPT_PATH = PROJECT_ROOT / "src" / "_classify_pipeline" / "prompt_stage_v5.md"
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "classifications.jsonl"
REVIEW_ARTIFACT_PATH = PROJECT_ROOT / "Auditoria" / "muestras_control" / "review_sample_v5_amplio.json"
MODEL = "openai/gpt-5.6-luna"
REASONING_EFFORT = "xhigh"
MAX_TEXT_CHARS_FOR_PROMPT = 30000
MAX_RETRIES = 5
MIN_EVIDENCE_QUOTE_CHARS = 15

RESIDENTIAL_OBJECTS = {
    "edificio_residencial",
    "ds19",
    "condominio",
    "loteo_residencial",
    "uso_mixto_residencial",
    "instrumento_urbano_residencial",
}

BROAD_OBJECTS = RESIDENTIAL_OBJECTS | {
    "centro_comercial",
    "edificio_oficinas",
    "hotel",
    "proyecto_industrial",
    "equipamiento_urbano",
    "infraestructura_no_residencial",
    "inmobiliario_privado_no_residencial",
    "instrumento_urbano_general",
}

SCOPES = {"residencial", "inmobiliaria_urbana_amplia"}


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def quote_is_grounded(quote: str, source_text: str) -> bool:
    quote = str(quote or "").strip()
    return bool(quote) and normalize_text(quote) in normalize_text(source_text)


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


def apply_scope_gate(parsed: dict[str, Any], source_text: str, scope: str) -> dict[str, Any]:
    """Evalúa una mención en un alcance concreto sin modificar la entrada."""
    if scope not in SCOPES:
        raise ValueError(f"scope no soportado: {scope}")

    result = deepcopy(parsed)
    reasons: list[str] = []
    model_decision = str(parsed.get("decision", "uncertain"))

    def value(name: str) -> str:
        return str(parsed.get(name, "")).strip().lower()

    action = value("accion_contenciosa")
    action_type = value("tipo_accion_contenciosa")
    object_type = value("tipo_objeto_norm") or value("tipo_objeto")
    real_estate = value("es_proyecto_inmobiliario")
    residential = value("es_proyecto_vivienda_inmobiliario")
    geography = value("precision_geografica")
    depth = value("profundidad_documentacion_caso")

    action_verified = quote_is_grounded(parsed.get("evidencia_accion_quote", ""), source_text) and len(str(parsed.get("evidencia_accion_quote", "")).strip()) >= MIN_EVIDENCE_QUOTE_CHARS
    object_verified = quote_is_grounded(parsed.get("evidencia_objeto_quote", ""), source_text) and len(str(parsed.get("evidencia_objeto_quote", "")).strip()) >= MIN_EVIDENCE_QUOTE_CHARS
    geo_verified = quote_is_grounded(parsed.get("evidencia_geografica_quote", ""), source_text) and len(str(parsed.get("evidencia_geografica_quote", "")).strip()) >= MIN_EVIDENCE_QUOTE_CHARS

    result["decision_modelo"] = model_decision
    result["scope"] = scope
    result["evidence_action_verified"] = action_verified
    result["evidence_object_verified"] = object_verified
    result["evidence_geo_verified"] = geo_verified

    if model_decision != "include":
        result["decision_final"] = model_decision
        result["gate_reasons"] = reasons
        result["gate_evaluation"] = {
            "action": action == "confirmada" and action_type not in {"", "ninguna", "incierta"},
            "object": False,
            "geography": geography not in {"fuera_de_area", "", "ambigua", "provincia_general"},
            "depth": depth in {"caso_principal", "caso_secundario_documentado"},
            "evidence_action": action_verified,
            "evidence_object": object_verified,
            "evidence_geo": geo_verified,
        }
        return result

    if action != "confirmada" or action_type in {"", "ninguna", "incierta"}:
        reasons.append("sin_accion_contenciosa" if action in {"no", "ninguna"} else "accion_contenciosa_incierta")

    object_ok = (
        object_type in (RESIDENTIAL_OBJECTS if scope == "residencial" else BROAD_OBJECTS)
        and (residential == "si" if scope == "residencial" else real_estate == "si")
    )
    if not object_ok:
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

    if depth == "mencion_tangencial":
        reasons.append("mencion_tangencial")
    elif depth not in {"caso_principal", "caso_secundario_documentado"}:
        reasons.append("caso_insuficientemente_documentado")

    if not action_verified:
        reasons.append("evidencia_accion_no_verificada")
    if not object_verified:
        reasons.append("evidencia_objeto_no_verificada")
    if not geo_verified:
        reasons.append("evidencia_geografica_no_verificada")

    hard_exclude = {"sin_accion_contenciosa", "objeto_fuera_de_alcance_residencial", "objeto_no_admisible", "fuera_del_area_geografica", "mencion_tangencial"}
    result["decision_final"] = "exclude" if hard_exclude.intersection(reasons) else ("uncertain" if reasons else "include")
    result["gate_reasons"] = reasons
    result["gate_evaluation"] = {
        "action": action == "confirmada" and action_type not in {"", "ninguna", "incierta"},
        "object": object_ok,
        "geography": geography not in {"fuera_de_area", "", "ambigua", "provincia_general"},
        "depth": depth in {"caso_principal", "caso_secundario_documentado"},
        "evidence_action": action_verified,
        "evidence_object": object_verified,
        "evidence_geo": geo_verified,
    }
    return result


def derive_document_decisions(mentions: list[dict[str, Any]], source_text: str) -> dict[str, Any]:
    """Aplica ambos alcances y conserva el expediente de cada mención."""
    processed: list[dict[str, Any]] = []
    residential_results: list[dict[str, Any]] = []
    broad_results: list[dict[str, Any]] = []
    for mention in mentions:
        residential = apply_scope_gate(mention, source_text, "residencial")
        broad = apply_scope_gate(mention, source_text, "inmobiliaria_urbana_amplia")
        item = deepcopy(mention)
        item["gate_residencial"] = residential
        item["gate_inmobiliaria_urbana_amplia"] = broad
        processed.append(item)
        residential_results.append(residential)
        broad_results.append(broad)
    return {
        "case_mentions": processed,
        "decision_residencial": _decision_for_scope(residential_results),
        "decision_inmobiliaria_urbana_amplia": _decision_for_scope(broad_results),
        "decision_documento": _decision_for_scope(broad_results),
    }


def validate_classification_payload(parsed: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
    except jsonschema.ValidationError as exc:
        logger.warning("Respuesta v5 invalida contra schema: %s", exc.message[:240])
        return False
    return True


def classify_document(doc: dict[str, Any], api_key: str, system_prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    text = str(doc.get("text", ""))[:MAX_TEXT_CHARS_FOR_PROMPT]
    user_content = (
        f"TITULO: {doc.get('title') or doc.get('discovery_title', '')}\n"
        f"URL: {doc.get('url', '')}\n\n"
        f"TEXTO DEL ARTICULO:\n{text}"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
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
                    logger.warning("429 persistente para %s", doc.get("url", "")[:80])
                    return None
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
                continue
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            parsed = json.loads(message["content"])
            if not validate_classification_payload(parsed, schema):
                return None
            return {
                "parsed": parsed,
                "usage": data.get("usage", {}),
                "reasoning": message.get("reasoning"),
                "reasoning_details": message.get("reasoning_details"),
                "raw_finish_reason": data["choices"][0].get("finish_reason"),
            }
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_RETRIES:
                logger.warning("Error persistente para %s: %s", doc.get("url", "")[:80], exc)
                return None
            time.sleep((2 ** attempt) + random.uniform(0, 1))
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Respuesta no utilizable para %s: %s", doc.get("url", "")[:80], exc)
            return None
    return None


def postprocess_result(doc: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parsed = result["parsed"]
    source_text = str(doc.get("text", ""))
    derived = derive_document_decisions(parsed.get("case_mentions", []), source_text)
    record = {
        "url": doc.get("url"),
        "lineage": doc.get("lineage", {}),
        "corpus_scope": "temporal_v2",
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


def classification_release_allowed(review_artifact: dict[str, Any]) -> bool:
    policy = review_artifact.get("review_policy", review_artifact)
    return (
        review_artifact.get("status") == "aprobado_revision_humana"
        and policy.get("human_review_completed") is True
        and policy.get("production_allowed") is True
    )


def _run(args: argparse.Namespace) -> int:
    is_test = bool(args.output_file or args.urls_file or args.dry_run)
    for stage in ("fulltext_acquisition_v2", "dedupe_fulltext"):
        if upstream_stage_is_running(stage):
            if is_test:
                logger.warning("%s activo; se continua porque es prueba", stage)
            else:
                raise StageSkipped(3, f"{stage} activo; se bloquea produccion")
    if not is_test:
        try:
            artifact = json.loads(REVIEW_ARTIFACT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageSkipped(4, f"no se pudo leer gate v5: {exc}") from exc
        if not classification_release_allowed(artifact):
            raise StageSkipped(4, "gate humano v5 pendiente")

    env = load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("OPENROUTER_API_KEY vacia")
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    urls_filter = None
    if args.urls_file:
        urls_filter = {line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if line.strip()}
    docs = load_classifiable_documents(urls_filter=urls_filter)
    done = already_classified_urls(output_path)
    pending = [doc for doc in docs if doc.get("url") not in done]
    if args.dry_run:
        pending = pending[:1]
    elif args.limit:
        pending = pending[: args.limit]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(classify_document, doc, api_key, prompt, schema): doc for doc in pending}
        for future in as_completed(futures):
            doc = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Fallo no recuperable para %s: %s", doc.get("url", "")[:80], exc)
                result = None
            if result is None:
                continue
            _, record = postprocess_result(doc, result)
            records.append(record)
    records.sort(key=lambda item: item.get("url", ""))
    if records:
        with output_path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    logger.info("v5 completado: %d registros escritos en %s", len(records), output_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificacion v5 por menciones y doble alcance")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    # El contrato v2 ya verificó 50 workers como configuración productiva.
    # Los pilotos deben pasar un valor explícito menor si se busca reducir
    # presión sobre la API; no cambiar silenciosamente el default contractual.
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    detail = {"output_path": str(output_path), "es_produccion": not bool(args.output_file or args.urls_file or args.dry_run), "schema_version": "v5"}
    try:
        with acquire_lock("classify_v5", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
