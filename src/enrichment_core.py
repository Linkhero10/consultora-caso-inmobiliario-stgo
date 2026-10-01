"""Nucleo de la extraccion estructurada por LLM (enrichment).

Un documento clasificado como relevante pasa por un modelo que devuelve, segun
`config/enrichment_schema.json`, el objeto de disputa, los actores, las instituciones, la linea
de tiempo y los proyectos mencionados. Cada proyecto mencionado se ancla a una `case_mention`
concreta de la clasificacion (`case_mention_index`): el modelo recibe la lista numerada de
menciones del documento y elige a cual pertenece cada proyecto. Ese vinculo se captura AQUI, en
la extraccion, porque reconstruirlo despues por similitud de texto fue la causa de la mayor
parte de las correcciones posteriores.

Este modulo contiene la logica reutilizable y testeable (verificacion de citas, saneamiento,
invariantes, cliente HTTP con reintentos y contabilidad de costo). El ejecutor con guardrails
de gasto es `src/enrich.py`.

Garantias de verificacion (por diseno, no por prompt):
- toda cita se comprueba como subcadena literal (normalizada en espacios y mayusculas) del texto
  fuente; una cita no verificada se vacia pero su original se conserva para auditoria;
- un `case_mention_index` fuera de rango se limpia a null y el valor crudo del modelo se conserva;
- un `proyecto_asociado` que no coincide con un proyecto mencionado se limpia igual;
- el registro final se valida contra `config/enrichment_record_schema.json` y los invariantes
  semanticos; un registro invalido se cuarentena, nunca se pierde una respuesta ya pagada.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from pathlib import Path
from typing import Any, Callable

import jsonschema
import requests

from paths import CLASSIFICATIONS_PATH, PROJECT_ROOT

logger = logging.getLogger("enrichment")

ENV_PATH = PROJECT_ROOT / ".env"
CONTENT_DIR = PROJECT_ROOT / "Fuentes" / "fulltext" / "content"
SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_schema.json"
# El schema de arriba es el contrato de RESPUESTA del LLM (additionalProperties: false). El registro
# que se persiste le agrega campos derivados (verificaciones, metadata de la corrida); este segundo
# contrato, generado por build_enrichment_record_schema.py, es el que valida el archivo final.
RECORD_SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_record_schema.json"
PROMPT_PATH = PROJECT_ROOT / "config" / "enrichment_prompt.md"

MODEL = "openai/gpt-6-luna"
REASONING_EFFORT = "xhigh"
# 30000 cubre el 100% del corpus real (el documento mas largo tiene 29.903 caracteres): con un tope
# menor se truncaba en silencio hasta el 30% de los documentos y el modelo respondia con aparente
# exhaustividad sin haber visto el articulo completo.
MAX_TEXT_CHARS_FOR_PROMPT = 30000
# El maximo real observado (razonamiento + respuesta) fue ~25.000 tokens; el tope deja ~30% de
# margen y corta una generacion descontrolada antes de que se pague completa.
MAX_COMPLETION_TOKENS = 32000

API_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "nanogpt": "https://nano-gpt.com/api/v1/chat/completions",
    "vercel": "https://ai-gateway.vercel.sh/v1/chat/completions",
    "requesty": "https://router.requesty.ai/v1/chat/completions",
}
ENV_KEY_BY_PROVIDER = {
    "openrouter": "OPENROUTER_API_KEY",
    "nanogpt": "NANOGPT_API_KEY",
    "vercel": "VERCEL_AI_GATEWAY_API_KEY",
    "requesty": "REQUESTY_API_KEY",
}
# Precio de lista del modelo. Solo respalda el calculo de costo cuando el proveedor no devuelve
# `usage.cost`; nunca reemplaza el costo real si el proveedor lo entrega.
PRICE_PER_TOKEN_USD = {"input": 0.10 / 1_000_000, "output": 0.50 / 1_000_000}
MAX_RETRIES = 5


def sha256_file(path: Path) -> str:
    """SHA-256 del archivo con saltos de linea normalizados a LF: el hash no depende de la configuracion de git
    del equipo (un checkout con CRLF y otro con LF darian hashes distintos del mismo contenido)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


_URL_TO_CONTENT_PATH_CACHE: dict[str, Path] | None = None


def find_content_path(url: str) -> Path | None:
    global _URL_TO_CONTENT_PATH_CACHE
    if _URL_TO_CONTENT_PATH_CACHE is None:
        _URL_TO_CONTENT_PATH_CACHE = {}
        for path in CONTENT_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("url"):
                _URL_TO_CONTENT_PATH_CACHE[data["url"]] = path
    return _URL_TO_CONTENT_PATH_CACHE.get(url)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def case_mentions_context_block(case: dict[str, Any]) -> str:
    """Lista numerada de las case_mentions ya clasificadas del documento.

    El indice (base 0, orden de aparicion) es exactamente el que despues valida
    `sanitize_project_associations` y el que usa el warehouse (`case_mention_id = document:indice`)."""
    case_mentions = case.get("case_mentions") or []
    if not case_mentions:
        return "CASE_MENTIONS EXISTENTES: (ninguna -- no deberias tener proyectos con case_mention_index distinto de null)"
    lines = ["CASE_MENTIONS EXISTENTES (ya decidido por la Etapa 1, no las reinterpretes):"]
    for i, cm in enumerate(case_mentions):
        objeto = (cm.get("tipo_objeto_raw") or "").strip()
        quotes = cm.get("evidencia_objeto_quotes") or []
        quote_preview = quotes[0] if quotes else ""
        lines.append(
            f"  [{i}] objeto={objeto[:200]!r} | cita_objeto={quote_preview[:200]!r} | "
            f"comuna={cm.get('comuna') or 'sin comuna'} | decision={cm.get('decision', '?')}"
        )
    return "\n".join(lines)


def build_user_content(case: dict[str, Any]) -> str:
    text = case.get("_text", "")[:MAX_TEXT_CHARS_FOR_PROMPT]
    return (
        f"TITULO: {case.get('_title', '')}\n"
        f"CLASIFICACION PREVIA (Etapa 1, ya decidida -- no la reevalues): "
        f"decision_documento={case.get('decision_documento')}\n\n"
        f"{case_mentions_context_block(case)}\n\n"
        f"TEXTO DEL ARTICULO:\n{text}"
    )


# ---------------------------------------------------------------------------
# Verificacion y saneamiento (deterministas, sin API)
# ---------------------------------------------------------------------------

def normalize_text(s: str) -> str:
    return " ".join(s.lower().split())


def quote_is_grounded(quote: str, source_text: str) -> bool:
    if not quote:
        return True
    return normalize_text(quote) in normalize_text(source_text)


def verify_literal_quote_field(item: dict[str, Any], field: str, source_text: str, label: str) -> dict[str, Any]:
    """Marca `{field}_verificada`. Una cita que no es subcadena literal del texto se vacia, pero el
    original se conserva en `{field}_original_modelo`: borrar sin rastro ocultaria el error del modelo."""
    item = dict(item)
    valor = item.get(field, "") or ""
    if not valor.strip():
        item[f"{field}_verificada"] = False
        return item
    if quote_is_grounded(valor, source_text):
        item[f"{field}_verificada"] = True
        return item
    logger.warning("%s: cita no verificada en %r -- se preserva en %s_original_modelo, %s queda vacio", label, valor[:60], field, field)
    item[f"{field}_original_modelo"] = valor
    item[field] = ""
    item[f"{field}_verificada"] = False
    return item


def verify_actor_quotes(actores: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    return [verify_literal_quote_field(a, "cita", source_text, f"actor {a.get('nombre', '')[:30]!r}") for a in actores]


def verify_institution_quotes(instituciones: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    return [verify_literal_quote_field(i, "cita", source_text, f"institucion {i.get('nombre', '')[:30]!r}") for i in instituciones]


_YEAR_RE = re.compile(r"\b(\d{4})\b")


def verify_timeline_descriptions(linea_tiempo: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    """Cada hito se verifica en dos capas: el año (palabra completa, no subcadena suelta) aparece en el
    texto fuente, y la cita literal propia del hito (`evidencia_hito`) es subcadena real del texto.
    Lo primero solo prueba que el año existe en algun lugar del articulo; lo segundo ancla el hito."""
    verified = []
    years_in_text = _YEAR_RE.findall(source_text)
    for hito in linea_tiempo:
        hito = dict(hito)
        fecha = str(hito.get("fecha", "")).strip()
        year_match = re.match(r"^(\d{4})", fecha)
        hito["fecha_year_grounded"] = bool(year_match and year_match.group(1) in years_in_text)
        hito = verify_literal_quote_field(hito, "evidencia_hito", source_text, f"hito {fecha!r}")
        verified.append(hito)
    return verified


def compute_truncation_flags(parsed: dict[str, Any], schema: dict) -> dict[str, bool]:
    """Un arreglo que llega EXACTO a su maxItems pudo haber sido cortado. No se intenta adivinar cuantos
    elementos faltan: solo se deja constancia de la posibilidad."""
    inner = schema.get("schema", schema)

    def _maybe_truncated(field: str) -> bool:
        max_items = inner["properties"].get(field, {}).get("maxItems")
        return max_items is not None and len(parsed.get(field, []) or []) >= max_items

    return {
        "actores_posiblemente_truncados": _maybe_truncated("actores"),
        "instituciones_posiblemente_truncadas": _maybe_truncated("instituciones_mencionadas"),
        "hitos_posiblemente_truncados": _maybe_truncated("linea_tiempo"),
    }


def sanitize_project_associations(parsed: dict[str, Any], n_case_mentions: int) -> dict[str, Any]:
    """Corrige (no descarta) las asociaciones invalidas del modelo.

    - `proyectos_mencionados[].case_mention_index` debe ser un entero en [0, n_case_mentions) o null;
      fuera de rango se conserva en `case_mention_index_original_modelo` y queda null.
    - `proyecto_asociado` de actores, instituciones e hitos debe coincidir con el nombre de un proyecto
      mencionado; si no, se conserva en `proyecto_asociado_original_modelo` y queda vacio.

    Descartar el documento entero por un campo corrupto perdia actores, instituciones e hitos buenos
    (en la primera corrida completa cuarentenaba el 7,8% de los documentos por un solo campo)."""
    proyectos = parsed.get("proyectos_mencionados", []) or []
    project_names = {p.get("nombre", "").strip() for p in proyectos if isinstance(p, dict) and p.get("nombre")}

    for item in proyectos:
        if not isinstance(item, dict):
            continue
        idx = item.get("case_mention_index")
        if idx is None:
            item["case_mention_index_verificada"] = False
            continue
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0 or idx >= n_case_mentions:
            logger.warning("proyectos_mencionados: case_mention_index=%r fuera de rango [0,%d) -- se preserva en case_mention_index_original_modelo, se limpia a null", idx, n_case_mentions)
            item["case_mention_index_original_modelo"] = idx
            item["case_mention_index"] = None
            item["case_mention_index_verificada"] = False
        else:
            item["case_mention_index_verificada"] = True

    for collection in ("actores", "instituciones_mencionadas", "linea_tiempo"):
        for i, item in enumerate(parsed.get(collection, []) or []):
            if not isinstance(item, dict):
                continue
            associated = (item.get("proyecto_asociado", "") or "").strip()
            if associated and associated not in project_names:
                logger.warning("%s[%d].proyecto_asociado=%r no coincide con proyectos_mencionados -- se preserva en proyecto_asociado_original_modelo, proyecto_asociado queda vacio", collection, i, associated[:80])
                item["proyecto_asociado_original_modelo"] = associated
                item["proyecto_asociado"] = ""
                item["proyecto_asociado_verificada"] = False
            else:
                # Se guarda el valor normalizado (strip), no el crudo: los espacios sobrantes rompian joins exactos.
                item["proyecto_asociado"] = associated
                item["proyecto_asociado_verificada"] = bool(associated)
    return parsed


def validate_record_invariants(parsed: dict[str, Any]) -> list[str]:
    """Contradicciones estructurales que JSON Schema no expresa: `revision.nivel=ninguno` con campos o
    motivo no vacios, o un campo marcado `_verificada=true` con el valor vacio (bug de postproceso)."""
    errors: list[str] = []
    revision = parsed.get("revision", {}) or {}
    if revision.get("nivel") == "ninguno":
        if revision.get("campos_afectados"):
            errors.append("revision.nivel=ninguno exige campos_afectados vacío")
        if revision.get("motivo", ""):
            errors.append("revision.nivel=ninguno exige motivo vacío")
    for collection in ("actores", "instituciones_mencionadas"):
        for index, item in enumerate(parsed.get(collection, []) or []):
            if isinstance(item, dict) and item.get("cita_verificada") is True and not (item.get("cita", "") or "").strip():
                errors.append(f"{collection}[{index}].cita_verificada=true exige cita no vacía")
    for index, item in enumerate(parsed.get("linea_tiempo", []) or []):
        if isinstance(item, dict) and item.get("evidencia_hito_verificada") is True and not (item.get("evidencia_hito", "") or "").strip():
            errors.append(f"linea_tiempo[{index}].evidencia_hito_verificada=true exige evidencia_hito no vacía")
    if parsed.get("evidencia_objeto_disputa_verificada") is True and not (parsed.get("evidencia_objeto_disputa", "") or "").strip():
        errors.append("evidencia_objeto_disputa_verificada=true exige evidencia_objeto_disputa no vacía")
    return errors


# ---------------------------------------------------------------------------
# Cliente HTTP con contabilidad de costo
# ---------------------------------------------------------------------------

def estimate_cost_usd(usage: dict) -> float:
    return (usage.get("prompt_tokens") or 0) * PRICE_PER_TOKEN_USD["input"] + (
        usage.get("completion_tokens") or 0
    ) * PRICE_PER_TOKEN_USD["output"]


def _failure(error: str, attempt_costs: list[float], request_attempt_count: int, raw_content: str | None,
             usage: dict | None = None) -> dict[str, Any]:
    return {
        "error": error[:300], "usage": usage or {}, "total_incurred_cost_usd": sum(attempt_costs),
        "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count,
        "raw_content_on_failure": raw_content,
    }


def enrich_document(
    case: dict[str, Any],
    api_key: str,
    system_prompt: str,
    schema: dict,
    effort: str = REASONING_EFFORT,
    provider: str = "openrouter",
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Una llamada al modelo con reintentos.

    Contabilidad: cada respuesta HTTP 200 se cobra aunque su JSON sea invalido, asi que el costo de TODOS
    los intentos pagados se acumula (`total_incurred_cost_usd`) y se separa del ultimo (`retry_cost_usd`).
    Se reintenta con backoff exponencial un 429, un error de conexion o un JSON malformado (la generacion
    es estocastica); una respuesta que viola el schema NO se reintenta (pagarla otra vez no la corrige)."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_content(case)},
        ],
        "reasoning": {"effort": effort},
        "response_format": {"type": "json_schema", "json_schema": schema},
        "max_tokens": MAX_COMPLETION_TOKENS,
    }
    if provider == "nanogpt":
        # NanoGPT no siempre devuelve el costo calculado salvo que se pida explicitamente.
        payload["include_usage"] = True

    url_label = case.get("url", "")[:60]
    attempt_costs: list[float] = []
    request_attempt_count = 0
    last_raw_content: str | None = None
    for attempt in range(MAX_RETRIES + 1):
        request_attempt_count += 1
        backoff = (2 ** attempt) + random.uniform(0, 1)
        try:
            resp = requests.post(
                API_BASE_URLS[provider],
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if resp.status_code == 429:
                if attempt == MAX_RETRIES:
                    return _failure("rate_limited_max_retries", attempt_costs, request_attempt_count, last_raw_content)
                sleep(backoff)
                continue
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            attempt_costs.append(usage.get("cost", 0.0) or estimate_cost_usd(usage))
            message = data["choices"][0]["message"]
            content = message["content"]
            last_raw_content = content
            meta = {
                "usage": usage,
                "raw_finish_reason": data["choices"][0].get("finish_reason"),
                "reasoning": message.get("reasoning"),
                "reasoning_details": message.get("reasoning_details"),
            }
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                if attempt == MAX_RETRIES:
                    return _failure(f"json_decode_failed_max_retries: {exc}", attempt_costs, request_attempt_count, content, usage)
                logger.warning("JSON invalido para %s (%s) -- reintento %d/%d", url_label, exc, attempt + 1, MAX_RETRIES)
                sleep(backoff)
                continue
            try:
                jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
            except jsonschema.ValidationError as val_exc:
                return _failure(f"schema_validation_failed: {val_exc.message[:200]}", attempt_costs, request_attempt_count, content, usage)
            return {
                "parsed": parsed, **meta,
                "total_incurred_cost_usd": sum(attempt_costs),
                "retry_cost_usd": sum(attempt_costs[:-1]),
                "paid_attempt_count": len(attempt_costs),
                "request_attempt_count": request_attempt_count,
            }
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_RETRIES:
                return _failure(f"connection_error_max_retries: {exc}", attempt_costs, request_attempt_count, last_raw_content)
            logger.info("Error de conexion transitorio para %s (%s) -- reintento %d/%d", url_label, type(exc).__name__, attempt + 1, MAX_RETRIES)
            sleep(backoff)
        except Exception as exc:  # noqa: BLE001 -- respuesta con forma inesperada: no se reintenta, no se oculta
            return _failure(f"unrecoverable_error: {exc}", attempt_costs, request_attempt_count, last_raw_content)
    return _failure("retry_loop_exhausted", attempt_costs, request_attempt_count, last_raw_content)


# ---------------------------------------------------------------------------
# Un documento de punta a punta
# ---------------------------------------------------------------------------

def process_document(
    case: dict[str, Any], result: dict[str, Any], record_schema: dict, schema: dict, run_id: str,
    effort: str, run_label: str, enriched_at: str, file_hashes: dict[str, str],
) -> dict[str, Any]:
    """Convierte la respuesta del modelo en un registro persistible.

    Devuelve {"status": "ok"|"invalid", "record", "parsed", "cost", "validation_error"}. Un registro que no
    cumple su contrato NO entra al archivo canonico: se cuarentena integro."""
    n_case_mentions = len(case.get("case_mentions") or [])
    parsed = result["parsed"]
    cost = result.get("total_incurred_cost_usd", 0.0)
    source_text = case.get("_text", "")

    parsed["actores"] = verify_actor_quotes(parsed.get("actores", []), source_text)
    parsed["instituciones_mencionadas"] = verify_institution_quotes(parsed.get("instituciones_mencionadas", []), source_text)
    parsed["linea_tiempo"] = verify_timeline_descriptions(parsed.get("linea_tiempo", []), source_text)
    parsed = verify_literal_quote_field(parsed, "evidencia_objeto_disputa", source_text, "objeto_disputa")
    parsed = sanitize_project_associations(parsed, n_case_mentions)
    invariant_errors = validate_record_invariants(parsed)

    record = {
        "url": case.get("url"),
        "n_case_mentions_etapa1": n_case_mentions,
        "decision_documento_etapa1": case.get("decision_documento"),
        "contract_version_etapa1": case.get("contract_version"),
        "lineage": case.get("_lineage", {}),
        "content_sha256": sha256_text(source_text),
        "content_char_count": len(source_text),
        "input_truncated": len(source_text) > MAX_TEXT_CHARS_FOR_PROMPT,
        "enriched_at": enriched_at,
        "model": MODEL,
        "reasoning_effort": effort,
        "enrichment_schema_version": run_label,
        "prompt_sha256": file_hashes["prompt"],
        "schema_sha256": file_hashes["schema"],
        "record_schema_sha256": file_hashes["record_schema"],
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
        return {"status": "invalid", "record": record, "parsed": parsed, "cost": cost,
                "validation_error": getattr(val_exc, "message", str(val_exc))[:500]}
    return {"status": "ok", "record": record, "parsed": parsed, "cost": cost, "validation_error": None}
