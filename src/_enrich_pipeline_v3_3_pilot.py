#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piloto de enrichment_schema_v3.3 (2026-09-24), arreglo de raiz de la relacion
proyecto->case_mention que nunca se capturaba en el momento de clasificar (ver
Auditoria/DISENO_geografia_case_mention_level_2026-09-23/). Corre SOLO sobre
PILOT_URLS (8 documentos elegidos porque ya sabemos, por auditoria manual
previa, cual es el resultado correcto esperado en cada uno -- 6 son bugs reales
ya confirmados de la relacion proyecto<->case_mention, 2 son controles
adicionales). Nunca debe procesar el corpus completo (330 documentos con >1
case_mention y >=1 proyecto) sin una decision explicita nueva tras revisar
este piloto.

Diferencia con _enrich_pipeline.py (v3.2, congelado, sigue siendo el productivo):
- Inyecta en el mensaje del usuario una lista numerada "CASE_MENTIONS
  EXISTENTES" (objeto/comuna/decision de cada case_mention ya clasificada),
  para que el modelo pueda anclar cada proyecto a un indice real.
- El schema (v3.3) cambia `proyectos_mencionados` de lista de strings a lista
  de objetos {nombre, case_mention_index}.
- sanitize_project_associations_v3_3() reemplaza a la version v3.2: valida
  que case_mention_index este en rango [0, n_case_mentions) o sea null,
  preservando el valor crudo del modelo cuando esta fuera de rango (mismo
  patron que proyecto_asociado_original_modelo)."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_lock import acquire_lock, LockBusyError, StageSkipped, read_jsonl_tolerant  # noqa: E402
from _enrich_pipeline import (  # noqa: E402 -- reutiliza toda la logica ya validada de v3.2
    load_env, _find_content_path, normalize_text, validate_record_invariants,
    quote_is_grounded, verify_literal_quote_field, compute_truncation_flags,
    verify_actor_quotes, verify_institution_quotes, verify_timeline_descriptions,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("enrich_case_v3_3_pilot")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion" / "classifications.jsonl"
SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_schema_v3_3.json"
RECORD_SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_record_schema_v3_3.json"
PROMPT_PATH = PROJECT_ROOT / "config" / "enrichment_prompt_v3_3.md"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_3_piloto"
ENRICHMENT_PATH = OUTPUT_DIR / "enrichment.jsonl"

# Guardrail duro (mismo patron que _enrich_pipeline.py): 8 URLs elegidas a
# mano porque ya conocemos el resultado esperado de cada una por auditoria
# manual previa. 6/8 son bugs reales ya confirmados de la relacion
# proyecto<->case_mention (Villa San Luis, CChC Las Condes, Suprema Estacion
# Central, Barrio Las Rejas, Ex-Ante/FIMA, Ivo Gasic); 2/8 son controles
# adicionales de diversidad (Vespucio 345, Portal Bicentenario/aeropuerto Los
# Cerrillos -- este ultimo tambien un bug ya confirmado de Fix 1C ronda 3).
PILOT_URLS = [
    "https://www.theclinic.cl/2014/05/19/villa-san-luis-la-caida-del-ultimo-bastion-de-allende-en-las-condes/",
    "https://www.biobiochile.cl/noticias/blogs/el-blog-de-patricio-herman/2021/06/23/salvado-por-la-campana-el-nuevo-edificio-de-la-camara-chilena-de-la-construccion-en-las-condes.shtml",
    "https://www.chilevision.cl/noticias/reportajes/cronicas/suprema-falla-contra-proyecto-inmobiliario-de-dos-edificios-con-mas-de-mil-departamentos-en-estacion-central/",
    "https://www.elmostrador.cl/cultura/2021/04/14/buscan-declarar-zona-tipica-el-barrio-las-rejas-de-estacion-central-para-evitar-guetos-verticales/",
    "https://www.ex-ante.cl/economia/los-contratos-por-trato-directo-del-alcalde-vodanovic-con-ong-vinculada-al-fa-para-frenar-inversion-inmobiliaria/",
    "https://revistaplaneo.cl/2015/01/26/entrevista-ivo-gasic/",
    "https://www.df.cl/empresas/construccion/abogados-de-vespucio-345-la-suprema-marca-precedente-de-la-oportunidad",
    "https://elquintopoder.cl/ciudad/un-conflicto-derivado-del-cierre-del-aeropuerto-los-cerrillos/",
]
MAX_PILOT_URLS = 10  # margen minimo -- sigue muy lejos de los 330 del universo real

MODEL = "openai/gpt-6-luna"  # 2026-09-24: GPT-6 Luna via OpenRouter, ~mitad de precio que 5.6-luna
REASONING_EFFORT = "xhigh"
MAX_TEXT_CHARS_FOR_PROMPT = 30000
MAX_COMPLETION_TOKENS = 32000


def _case_mentions_context_block(case: dict[str, Any]) -> str:
    """Construye el bloque 'CASE_MENTIONS EXISTENTES' que el prompt v3.3
    espera, a partir de las case_mentions ya clasificadas (Etapa 1) para
    este documento. El indice usado aqui (0-based, orden de aparicion) es
    EXACTAMENTE el que despues valida sanitize_project_associations_v3_3()."""
    case_mentions = case.get("case_mentions") or []
    if not case_mentions:
        return "CASE_MENTIONS EXISTENTES: (ninguna -- no deberias tener proyectos con case_mention_index distinto de null)"
    lines = ["CASE_MENTIONS EXISTENTES (ya decidido por la Etapa 1, no las reinterpretes):"]
    for i, cm in enumerate(case_mentions):
        objeto = (cm.get("tipo_objeto_raw") or "").strip()
        quotes = cm.get("evidencia_objeto_quotes") or []
        quote_preview = quotes[0] if quotes else ""
        comuna = cm.get("comuna") or "sin comuna"
        decision = cm.get("decision", "?")
        lines.append(
            f"  [{i}] objeto={objeto[:200]!r} | cita_objeto={quote_preview[:200]!r} | "
            f"comuna={comuna} | decision={decision}"
        )
    return "\n".join(lines)


def load_pilot_cases() -> list[dict[str, Any]]:
    if len(PILOT_URLS) > MAX_PILOT_URLS:
        raise RuntimeError(f"PILOT_URLS tiene {len(PILOT_URLS)} URLs, por encima del limite de seguridad {MAX_PILOT_URLS}.")

    by_url: dict[str, dict[str, Any]] = {}
    for rec in read_jsonl_tolerant(CLASSIFICATIONS_PATH):
        if rec.get("url") in PILOT_URLS:
            by_url[rec["url"]] = rec

    cases = []
    for url in PILOT_URLS:
        rec = by_url.get(url)
        if rec is None:
            logger.warning("URL del piloto no encontrada en classifications.jsonl: %s", url)
            continue
        content_path = _find_content_path(url)
        if content_path is None:
            logger.warning("No se encontro contenido fulltext para %s -- se omite", url[:70])
            continue
        content = json.loads(content_path.read_text(encoding="utf-8"))
        rec["_text"] = content.get("text", "")
        rec["_title"] = content.get("title") or rec.get("title", "")
        rec["_lineage"] = rec.get("lineage") or content.get("lineage", {})
        cases.append(rec)
    return cases


def already_enriched_urls() -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(ENRICHMENT_PATH)}


def sanitize_project_associations_v3_3(parsed: dict[str, Any], n_case_mentions: int) -> dict[str, Any]:
    """Version v3.3 de sanitize_project_associations: valida
    case_mention_index de cada elemento de proyectos_mencionados en vez de
    proyecto_asociado como string. Mismo principio (corregir, no descartar el
    registro): un indice fuera de rango se preserva en
    case_mention_index_original_modelo y se limpia a null, nunca se
    descarta el documento completo por un solo indice invalido."""
    proyectos = parsed.get("proyectos_mencionados", []) or []
    project_names = {p.get("nombre", "").strip() for p in proyectos if isinstance(p, dict) and p.get("nombre")}

    for item in proyectos:
        if not isinstance(item, dict):
            continue
        idx = item.get("case_mention_index")
        if idx is None:
            item["case_mention_index_verificada"] = False
            continue
        if not isinstance(idx, int) or idx < 0 or idx >= n_case_mentions:
            logger.warning("proyectos_mencionados: case_mention_index=%r fuera de rango [0,%d) -- se preserva en case_mention_index_original_modelo, se limpia a null", idx, n_case_mentions)
            item["case_mention_index_original_modelo"] = idx
            item["case_mention_index"] = None
            item["case_mention_index_verificada"] = False
        else:
            item["case_mention_index_verificada"] = True

    # proyecto_asociado (actores/instituciones/hitos, v3.2) sigue vigente sin cambios --
    # solo se re-verifica contra los NOMBRES (ahora dentro de objetos, no strings sueltos).
    for collection in ("actores", "instituciones_mencionadas", "linea_tiempo"):
        items = parsed.get(collection, []) or []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            associated = (item.get("proyecto_asociado", "") or "").strip()
            if associated and associated not in project_names:
                logger.warning("%s[%d].proyecto_asociado=%r no coincide con proyectos_mencionados -- se preserva en proyecto_asociado_original_modelo, proyecto_asociado queda vacio", collection, i, associated[:80])
                item["proyecto_asociado_original_modelo"] = associated
                item["proyecto_asociado"] = ""
                item["proyecto_asociado_verificada"] = False
            else:
                item["proyecto_asociado"] = associated
                item["proyecto_asociado_verificada"] = bool(associated)
    return parsed


API_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "nanogpt": "https://nano-gpt.com/api/v1/chat/completions",
}

# Precio de lista de gpt-6-luna (confirmado via WebSearch 2026-09-24, mismo en
# OpenRouter y NanoGPT porque ambos cobran al precio de lista del proveedor
# real, sin markup en el token): $0.10/M input, $0.50/M output. Se usa SOLO
# como respaldo cuando la respuesta del proveedor no trae "usage.cost" ya
# calculado (OpenRouter si lo trae; NanoGPT puede no traerlo) -- nunca
# reemplaza el costo real si el proveedor lo entrega.
PRICE_PER_TOKEN_USD = {"input": 0.10 / 1_000_000, "output": 0.50 / 1_000_000}


def _estimate_cost_usd(usage: dict) -> float:
    prompt_tokens = usage.get("prompt_tokens") or 0
    completion_tokens = usage.get("completion_tokens") or 0
    return prompt_tokens * PRICE_PER_TOKEN_USD["input"] + completion_tokens * PRICE_PER_TOKEN_USD["output"]


def enrich_document(case: dict[str, Any], api_key: str, system_prompt: str, schema: dict, effort: str = REASONING_EFFORT, provider: str = "openrouter") -> dict[str, Any]:
    attempt_costs: list[float] = []
    text = case.get("_text", "")[:MAX_TEXT_CHARS_FOR_PROMPT]
    context_block = _case_mentions_context_block(case)
    user_content = (
        f"TITULO: {case.get('_title', '')}\n"
        f"CLASIFICACION PREVIA (Etapa 1, ya decidida -- no la reevalues): "
        f"decision_documento={case.get('decision_documento')}\n\n"
        f"{context_block}\n\n"
        f"TEXTO DEL ARTICULO:\n{text}"
    )
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "reasoning": {"effort": effort},
        "response_format": {"type": "json_schema", "json_schema": schema},
        "max_tokens": MAX_COMPLETION_TOKENS,
    }
    if provider == "nanogpt":
        # NanoGPT no siempre incluye el costo calculado en la respuesta no-streaming
        # salvo que se pida explicitamente (a diferencia de OpenRouter, que lo trae
        # siempre en usage.cost). No cambia modelo/esfuerzo/schema, solo pide el dato.
        payload["include_usage"] = True

    api_base_url = API_BASE_URLS[provider]
    max_retries = 5
    request_attempt_count = 0
    last_raw_content: str | None = None
    for attempt in range(max_retries + 1):
        request_attempt_count += 1
        try:
            resp = requests.post(
                api_base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            attempt_cost = usage.get("cost", 0.0) or 0.0
            if not attempt_cost:
                attempt_cost = _estimate_cost_usd(usage)
            attempt_costs.append(attempt_cost)
            message = data["choices"][0]["message"]
            content = message["content"]
            last_raw_content = content
            raw_finish_reason = data["choices"][0].get("finish_reason")
            reasoning = message.get("reasoning")
            reasoning_details = message.get("reasoning_details")
            parsed = json.loads(content)
            jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
            total_cost = sum(attempt_costs)
            retry_cost = sum(attempt_costs[:-1])
            return {
                "parsed": parsed, "usage": usage, "total_incurred_cost_usd": total_cost,
                "retry_cost_usd": retry_cost,
                "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count,
                "raw_finish_reason": raw_finish_reason,
                "reasoning": reasoning, "reasoning_details": reasoning_details,
            }
        except Exception as exc:  # noqa: BLE001 -- piloto chico, sin necesidad del backoff completo de produccion
            if attempt == max_retries:
                logger.warning("Fallo persistente para %s: %s -- costo incurrido=$%.5f", case.get("url", "")[:60], exc, sum(attempt_costs))
                # Preserva el ultimo contenido crudo recibido (si lo hubo) aunque
                # no haya pasado json.loads/jsonschema.validate -- una respuesta
                # HTTP 200 ya se pago, nunca se descarta en silencio.
                return {"error": str(exc)[:300], "total_incurred_cost_usd": sum(attempt_costs), "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "raw_content_on_failure": last_raw_content}
            logger.warning("Reintentando %s tras error: %s", case.get("url", "")[:60], exc)
            continue
    return {"error": "retry_loop_exhausted", "total_incurred_cost_usd": sum(attempt_costs), "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "raw_content_on_failure": last_raw_content}


def main() -> int:
    detail = {"piloto_acotado": True, "n_urls_piloto": len(PILOT_URLS), "schema_version": "v3.3"}
    try:
        with acquire_lock("enrich_case_v3_3_pilot", detail=detail):
            return _run()
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        return exc.return_code


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run() -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("OPENROUTER_API_KEY vacia")
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record_schema = json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    cases = load_pilot_cases()
    done_urls = already_enriched_urls()
    pending = [c for c in cases if c.get("url") not in done_urls]
    logger.info("Casos piloto: %d | ya enriquecidos: %d | pendientes: %d", len(cases), len(done_urls), len(pending))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    manifest_path = OUTPUT_DIR / f"run_manifest.{run_id}.json"

    total_cost = 0.0
    n_written = 0
    n_errors = 0

    with ENRICHMENT_PATH.open("a", encoding="utf-8") as out_file:
        for case in pending:
            n_case_mentions = len(case.get("case_mentions") or [])
            result = enrich_document(case, api_key, system_prompt, schema)
            if not result or "error" in result:
                n_errors += 1
                total_cost += (result or {}).get("total_incurred_cost_usd", 0.0) or 0.0
                logger.warning("Fallo para %s: %s", case.get("url", "")[:70], (result or {}).get("error"))
                if (result or {}).get("raw_content_on_failure"):
                    with (OUTPUT_DIR / "invalid_records.jsonl").open("a", encoding="utf-8") as invalid_file:
                        invalid_file.write(json.dumps({
                            "url": case.get("url"), "validation_error": (result or {}).get("error"),
                            "raw_content": result["raw_content_on_failure"], "run_id": run_id,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False) + "\n")
                continue

            parsed = result["parsed"]
            cost = result.get("total_incurred_cost_usd", 0.0)
            total_cost += cost

            source_text = case.get("_text", "")
            parsed["actores"] = verify_actor_quotes(parsed.get("actores", []), source_text)
            parsed["instituciones_mencionadas"] = verify_institution_quotes(parsed.get("instituciones_mencionadas", []), source_text)
            parsed["linea_tiempo"] = verify_timeline_descriptions(parsed.get("linea_tiempo", []), source_text)
            parsed = verify_literal_quote_field(parsed, "evidencia_objeto_disputa", source_text, "objeto_disputa")
            parsed = sanitize_project_associations_v3_3(parsed, n_case_mentions)
            invariant_errors = validate_record_invariants(parsed)

            record = {
                "url": case.get("url"),
                "n_case_mentions_etapa1": n_case_mentions,
                "decision_documento_etapa1": case.get("decision_documento"),
                "contract_version_etapa1": case.get("contract_version"),
                "lineage": case.get("_lineage", {}),
                "content_sha256": _sha256_text(source_text),
                "content_char_count": len(source_text),
                "input_truncated": len(source_text) > MAX_TEXT_CHARS_FOR_PROMPT,
                "enriched_at": datetime.now(timezone.utc).isoformat(),
                "model": MODEL,
                "reasoning_effort": REASONING_EFFORT,
                "enrichment_schema_version": "v3.3_piloto",
                "prompt_sha256": _sha256_file(PROMPT_PATH),
                "schema_sha256": _sha256_file(SCHEMA_PATH),
                "run_id": run_id,
                "usage": result.get("usage", {}),
                "retry_cost_usd": result.get("retry_cost_usd", 0.0),
                "total_incurred_cost_usd": cost,
                "paid_attempt_count": result.get("paid_attempt_count", 1),
                "request_attempt_count": result.get("request_attempt_count", 1),
                "reasoning": result.get("reasoning"),
                "reasoning_details": result.get("reasoning_details"),
                "raw_finish_reason": result.get("raw_finish_reason"),
                **compute_truncation_flags(parsed, schema),
                **parsed,
            }

            try:
                if invariant_errors:
                    raise ValueError("; ".join(invariant_errors))
                jsonschema.validate(instance=record, schema=record_schema)
            except (jsonschema.ValidationError, ValueError) as val_exc:
                # Hallazgo real (2026-09-24, primera corrida): antes esto solo
                # logueaba y descartaba el registro -- una respuesta YA PAGADA
                # se perdia para siempre si fallaba esta validacion final.
                # Ahora se cuarentena integra (misma logica que
                # invalid_records.jsonl en _enrich_pipeline.py v3.2): nunca se
                # pierde una respuesta pagada, aunque no pase el contrato.
                n_errors += 1
                error_message = str(val_exc)[:500]
                logger.error("Registro invalido para %s: %s -- cuarentenado en invalid_records.jsonl, NO se pierde", case.get("url", "")[:70], error_message[:300])
                with (OUTPUT_DIR / "invalid_records.jsonl").open("a", encoding="utf-8") as invalid_file:
                    invalid_file.write(json.dumps({
                        "url": case.get("url"), "validation_error": error_message,
                        "record": record, "run_id": run_id,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False) + "\n")
                continue

            out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_file.flush()
            n_written += 1
            logger.info(
                "[%d/%d] %s -> proyectos=%s | costo=$%.5f",
                n_written, len(pending), case.get("url", "")[:60],
                [(p.get("nombre"), p.get("case_mention_index")) for p in parsed.get("proyectos_mencionados", [])],
                cost,
            )

    manifest = {
        "run_id": run_id, "written": n_written, "errors": n_errors, "total_cost_usd": total_cost,
        "schema_version": "v3.3_piloto", "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Total enriquecidos: %d | errores: %d | costo total: $%.5f USD | manifest: %s", n_written, n_errors, total_cost, manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
