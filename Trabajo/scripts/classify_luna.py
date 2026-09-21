#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clasificacion LLM con openai/gpt-5.6-luna (reasoning effort xhigh) via OpenRouter.
Caso piloto inmobiliario Santiago.

Patron adaptado de:
D:\\Analisis conflictos\\02_externo\\encargo_profesor\\Trabajo\\SAM-Cordillera\\scripts\\openrouter_production.py

Decision confirmada con el usuario 2026-09-11: la auditoría (xhigh) como unico modelo,
sin respaldo -- benchmark real (Artificial Analysis) confirma el modelo principal en xhigh ~=
el modelo de referencia en low en Intelligence Index (score 49 ambos), a ~10x menos costo.
reasoning.effort verificado contra docs.openrouter.ai/docs/use-cases/reasoning-tokens.

Uso:
  python classify_luna.py --dry-run    # 1 documento de prueba, imprime sin guardar
  python classify_luna.py --limit 10
  python classify_luna.py              # todos los documentos con texto suficiente
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_lock import acquire_lock, LockBusyError, StageSkipped, upstream_stage_is_running, read_jsonl_tolerant  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("classify_luna")

# Contrato v2 (2026-09-12): schema/prompt v1 quedan intactos como snapshot
# historico de la corrida original (44 registros, 4 comunas) -- nunca se
# fusionan corridas de contratos de esquema distintos en un mismo archivo
# (regla dura de Capacidades/skills/web-scraping-deploy/faro-scraping-pipeline/SKILL.md,
# "No fusiones corridas de contratos distintos por orden o por 'registro mas
# completo'"). v2 amplia a 32 comunas + via_legal + comuna_secundaria_mencionada
# tras la auditoria cruzada de subagentes 2026-09-12 -- ver pipeline_contract_v1.yaml.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
# Fix 2026-09-12 (bug real encontrado por QA cruzado antes de escalar):
# esto seguia apuntando a fulltext_v1 (67 docs, 4 comunas, sin lineage)
# aunque el schema/prompt ya se habian versionado a v2 -- classify_luna.py
# habria seguido leyendo el corpus chico viejo sin darse cuenta.
CONTENT_DIR = PROJECT_ROOT / "Fuentes" / "fulltext_v2" / "content"
DEDUPE_MANIFEST_PATH = PROJECT_ROOT / "Fuentes" / "fulltext_v2" / "dedupe_manifest_v2.jsonl"
# Bump a v4 2026-09-15: el piloto v3 encontro falsos positivos porque el
# gate nuevo vivia solo en prompt/schema y no se aplicaba deterministicamente.
# v3 y su salida quedan como historial; v4 exige evidencias separadas y
# calcula decision_final en codigo, sin mezclar contratos.
SCHEMA_PATH = PROJECT_ROOT / "Trabajo" / "config" / "classification_schema_v4.json"
PROMPT_PATH = PROJECT_ROOT / "Trabajo" / "prompts" / "classifier_system_v4.md"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v4"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "classifications.jsonl"
LEGACY_CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v2" / "classifications.jsonl"
REVIEW_ARTIFACT_PATH = PROJECT_ROOT / "Auditoria" / "muestras_control" / "review_sample_v4_70.json"

MODEL = "openai/gpt-5.6-luna"
REASONING_EFFORT = "xhigh"
MIN_TEXT_CHARS = 200
MIN_EVIDENCE_QUOTE_CHARS = 15  # mismo minimo que declara (solo como descripcion, no como restriccion real) classification_schema_v3.json
# Fix 2026-09-13 (decision de Felipe, con datos reales): el limite anterior
# de 6000 truncaba el 15.6% de los documentos con texto (362/2326), y
# quote_is_grounded() verifica contra el texto COMPLETO mientras el modelo
# solo ve el texto truncado -- el modelo jamas puede citar evidencia que
# este mas alla del corte, y los documentos mas largos (sentencias,
# resoluciones oficiales, informes) suelen ser justo los de mayor
# autoridad probatoria. Subido a 30000 (cubre el percentil ~90-95 real).
# Los que superen esto NO se truncan silenciosamente -- se apartan sin
# clasificar (ver DOCUMENTOS_LARGOS_PATH) para revision humana o
# delegacion a otro modelo, en vez de arriesgar una decision con texto
# incompleto.
MAX_TEXT_CHARS_FOR_PROMPT = 30000
DOCUMENTOS_LARGOS_PATH = OUTPUT_DIR / "documentos_largos_apartados.jsonl"

# Decision 2026-09-15 (Felipe, sobre hallazgo real: 15/37 posts de X/Twitter
# del corpus eran o bien el muro de login de X capturado por el scraper en
# vez del tuit real ("Post Iniciar sesion Registrate...", "JavaScript no
# esta disponible...") o el texto del tuit genuinamente cortado a mitad de
# frase por el limite del scraper -- ninguno de los dos casos tiene
# informacion suficiente para clasificar con criterio parejo al de una
# noticia de medio nacional. Se aparta ANTES de la API, sin costo, en vez de
# dejar que el modelo decida con texto incompleto.
SOCIAL_TRUNCATION_DOMAINS = {"x.com", "twitter.com", "t.co", "mobile.twitter.com"}
SOCIAL_LOGIN_WALL_MARKERS = (
    "post iniciar sesion registrate",
    "javascript no esta disponible",
)
SOCIAL_SENTENCE_ENDERS = tuple(".!?…\"'”’)]")
SOCIAL_TRUNCADO_PATH = PROJECT_ROOT / "Fuentes" / "fulltext_v2" / "social_truncado_apartados.jsonl"


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def _is_incomplete_social_post(url: str, text: str) -> str:
    """Devuelve el motivo si el post de X/Twitter debe apartarse sin
    clasificar, o cadena vacia si el contenido esta completo. Puramente
    deterministico, sin llamar al modelo."""
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


def corpus_scope_for_lineage(lineage: dict[str, Any] | None) -> str:
    """Clasifica el alcance analítico sin inventar un periodo temporal.

    `legacy_sin_ventana` queda fuera del corpus temporal principal. Una URL
    descubierta por ambos contratos conserva la procedencia mixta y puede
    mantenerse en el corpus v2 porque existe al menos un origen temporal v2.
    """
    lineage = lineage or {}
    origins = lineage.get("origins")
    candidates = origins if isinstance(origins, list) and origins else [lineage]
    has_legacy = any(not str(origin.get("periodo", "")).strip() or not str(origin.get("nivel", "")).strip() for origin in candidates)
    has_v2 = any(str(origin.get("periodo", "")).strip() and str(origin.get("nivel", "")).strip() for origin in candidates)
    if has_v2 and has_legacy:
        return "temporal_v2_mixed_legacy"
    if has_v2:
        return "temporal_v2"
    if has_legacy:
        return "legacy_sin_ventana"
    return "unknown"


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def load_excluded_duplicate_urls() -> set[str]:
    """URLs marcadas como duplicado exacto (content_hash) por
    dedupe_fulltext.py -- solo se excluyen esas, nunca los
    candidato_revision de fingerprint corto (esos si se clasifican).
    Si el manifest de dedupe todavia no existe (no se ha corrido
    dedupe_fulltext.py), no excluye nada -- no bloquea el triage."""
    excluded: set[str] = set()
    for rec in read_jsonl_tolerant(DEDUPE_MANIFEST_PATH):
        if rec.get("tipo") == "duplicado_exacto":
            excluded.add(rec.get("url", ""))
    return excluded


def already_set_aside_long_urls() -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(DOCUMENTOS_LARGOS_PATH)}


def set_aside_long_document(data: dict[str, Any]) -> None:
    """Fix 2026-09-13: un documento que supera MAX_TEXT_CHARS_FOR_PROMPT no
    se trunca ni se clasifica con texto incompleto -- se aparta para
    revision humana o delegacion a otro modelo (decision explicita de
    Felipe). Append-only, deduplicado por URL contra lo ya apartado."""
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
            # Un contenido truncado no debe tumbar toda la corrida ni entrar
            # como documento clasificable. fulltext lo volvera a intentar si
            # su manifest tampoco pudo validar el artefacto.
            logger.warning("Contenido invalido omitido de clasificacion: %s (%s)", path, exc)
            continue
        if not isinstance(data, dict):
            logger.warning("Contenido no-objeto omitido de clasificacion: %s", path)
            continue
        if data.get("char_count", 0) < MIN_TEXT_CHARS:
            continue
        if corpus_scope_for_lineage(data.get("lineage")) == "legacy_sin_ventana":
            logger.info("Contenido legacy sin ventana excluido del triage v2: %s", data.get("url", "")[:80])
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
        logger.info("Documentos apartados por exceder %d caracteres (nuevos esta corrida): %d -- ver %s", MAX_TEXT_CHARS_FOR_PROMPT, apartados_nuevos, DOCUMENTOS_LARGOS_PATH)
    if apartados_sociales_nuevos:
        logger.info("Posts de X/Twitter apartados por muro de login o truncamiento (nuevos esta corrida): %d -- ver %s", apartados_sociales_nuevos, SOCIAL_TRUNCADO_PATH)
    return docs


def already_classified_urls(output_path: Path) -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(output_path)}


def normalize_text(s: str) -> str:
    return " ".join(s.lower().split())


def quote_is_grounded(quote: str, source_text: str) -> bool:
    """Verifica que evidence_quote sea substring literal (normalizado en
    espacios/mayusculas) del texto fuente -- sin esto, el LLM puede
    fabricar una cita que suena real pero no esta en el articulo.
    Hallazgo del subagente auditor 2026-09-12."""
    if not quote:
        return True
    return normalize_text(quote) in normalize_text(source_text)


ADMISSIBLE_OBJECTS_V4 = {
    "edificio_residencial",
    "ds19",
    "condominio",
    "loteo_residencial",
    "uso_mixto_residencial",
    "instrumento_urbano_residencial",
}


def apply_deterministic_gate(parsed: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Calcula la decision final a partir de premisas verificables.

    El LLM extrae las premisas; esta función decide. Un campo ausente o
    ambiguo nunca habilita ``include``. Las razones quedan en el registro
    para que cada degradación sea auditable y reproducible sin otra llamada
    al modelo.
    """
    result = dict(parsed)
    model_decision = str(parsed.get("decision", "error"))
    result["decision_modelo"] = model_decision
    reasons: list[str] = []

    def value(name: str) -> str:
        return str(parsed.get(name, "")).strip().lower()

    def verified_quote(name: str) -> bool:
        quote = str(parsed.get(name, "") or "").strip()
        return len(quote) >= MIN_EVIDENCE_QUOTE_CHARS and quote_is_grounded(quote, source_text)

    action = value("accion_contenciosa")
    action_type = value("tipo_accion_contenciosa")
    object_scope = value("es_proyecto_vivienda_inmobiliario")
    object_type = value("tipo_objeto")
    geography = value("precision_geografica")
    depth = value("profundidad_documentacion_caso")

    action_verified = verified_quote("evidencia_accion_quote")
    object_verified = verified_quote("evidencia_objeto_quote")
    geo_verified = verified_quote("evidencia_geografica_quote")
    result["evidence_action_verified"] = action_verified
    result["evidence_object_verified"] = object_verified
    result["evidence_geo_verified"] = geo_verified

    if model_decision != "include":
        result["decision_final"] = model_decision
        result["gate_reasons"] = reasons
        return result

    if action in {"no", "ninguna", "false"} or action_type in {"ninguna", "no", "none"}:
        reasons.append("sin_accion_contenciosa")
    elif action in {"", "incierta", "incerta", "unknown"} or action_type in {"", "incierta", "incerta", "unknown"}:
        reasons.append("accion_contenciosa_incierta")

    if object_scope in {"no", "false"} or object_type == "infraestructura_no_residencial":
        reasons.append("objeto_fuera_de_alcance")
    elif object_scope in {"", "incierto", "incerta"} or object_type in {"", "none", "objeto_no_determinado", "otro"}:
        reasons.append("objeto_no_determinado")
    elif object_type not in ADMISSIBLE_OBJECTS_V4:
        reasons.append("objeto_no_admisible")

    if geography == "fuera_de_area":
        reasons.append("fuera_del_area_geografica")
    elif geography in {"", "ambigua", "provincia_general"}:
        reasons.append("geografia_incierta")

    if depth == "mencion_tangencial":
        reasons.append("mencion_tangencial")
    elif depth in {"", "no_aplica", "unknown"}:
        reasons.append("caso_insuficientemente_documentado")

    if not action_verified:
        reasons.append("evidencia_accion_no_verificada")
    if not object_verified:
        reasons.append("evidencia_objeto_no_verificada")
    if not geo_verified:
        reasons.append("evidencia_geografica_no_verificada")

    hard_exclude = {
        "sin_accion_contenciosa",
        "objeto_fuera_de_alcance",
        "fuera_del_area_geografica",
        "mencion_tangencial",
    }
    if hard_exclude.intersection(reasons):
        final = "exclude"
    elif reasons:
        final = "uncertain"
    else:
        final = "include"

    result["decision_final"] = final
    result["gate_reasons"] = reasons
    return result


def validate_classification_payload(parsed: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
    except jsonschema.ValidationError as exc:
        logger.warning("Respuesta de clasificación inválida contra schema: %s", exc.message[:200])
        return False
    return True


def classification_release_allowed(review_artifact: dict[str, Any]) -> bool:
    """Solo permite produccion despues de una aprobacion humana explicita."""
    policy = review_artifact.get("review_policy", review_artifact)
    return (
        review_artifact.get("status") == "aprobado_revision_humana"
        and policy.get("human_review_completed") is True
        and policy.get("production_allowed") is True
    )


MAX_429_RETRIES = 5


def classify_document(doc: dict[str, Any], api_key: str, system_prompt: str, schema: dict) -> dict[str, Any] | None:
    text = doc.get("text", "")[:MAX_TEXT_CHARS_FOR_PROMPT]
    # NO se incluye la comuna de descubrimiento en el payload que ve el
    # modelo -- es una hipotesis del propio pipeline (de que busqueda vino
    # el articulo), no un dato del contenido, y contaminaba la clasificacion
    # con maxima prominencia posicional. Se guarda por separado en el
    # registro de salida como "comuna_descubrimiento" para comparar despues
    # contra la comuna que el modelo determine de forma independiente.
    # Hallazgo del subagente auditor 2026-09-12.
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

    # Reintento con backoff para 429 (rate limit) Y para errores de
    # conexion/TLS transitorios (SSLEOFError, ConnectionError, Timeout) --
    # fix 2026-09-12: probando 100 workers concurrentes aparecieron 87/100
    # fallos, pero NO eran 429 -- eran SSLEOFError a mitad del handshake
    # TLS, consistentes con la proteccion anti-DDoS de Cloudflare que la
    # doc de OpenRouter menciona ("bloqueara requests que excedan
    # dramaticamente el uso razonable") mas que con un rate-limit
    # documentado. Sin este fix, esos 87 documentos se perdian
    # permanentemente (el except generico los daba por error sin
    # reintentar) -- ahora se tratan igual que un 429, con el mismo backoff.
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if resp.status_code == 429:
                if attempt == MAX_429_RETRIES:
                    logger.warning("429 persistente tras %d reintentos para %s -- se abandona este documento", MAX_429_RETRIES, doc.get("url", "")[:60])
                    return None
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.info("429 (rate limit) para %s -- reintento %d/%d en %.1fs", doc.get("url", "")[:60], attempt + 1, MAX_429_RETRIES, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            message = data["choices"][0]["message"]
            content = message["content"]
            parsed = json.loads(content)
            if not validate_classification_payload(parsed, schema):
                return None
            # 2026-09-15: el razonamiento (reasoning/reasoning_details) ya
            # viene incluido en la respuesta y ya esta cobrado dentro de
            # usage.completion_tokens_details.reasoning_tokens -- guardarlo
            # no cuesta nada extra, antes se descartaba sin usarlo.
            return {
                "parsed": parsed,
                "usage": usage,
                "reasoning": message.get("reasoning"),
                "reasoning_details": message.get("reasoning_details"),
                "raw_finish_reason": data["choices"][0].get("finish_reason"),
            }
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_429_RETRIES:
                logger.warning("Error de conexion persistente tras %d reintentos para %s: %s -- se abandona", MAX_429_RETRIES, doc.get("url", "")[:60], exc)
                return None
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.info("Error de conexion transitorio para %s (%s) -- reintento %d/%d en %.1fs", doc.get("url", "")[:60], type(exc).__name__, attempt + 1, MAX_429_RETRIES, wait)
            time.sleep(wait)
            continue
        except Exception as exc:  # noqa: BLE001 -- errores no transitorios (parseo JSON, etc.): no tiene sentido reintentar
            logger.warning("Error no recuperable clasificando %s: %s", doc.get("url", "")[:60], exc)
            return None
    return None


def postprocess_result(doc: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Aplica las mismas verificaciones de coherencia/evidencia que antes,
    factorizadas para que las use tanto el camino secuencial como cada
    worker del pool sin duplicar la logica."""
    parsed = result["parsed"]
    usage = result.get("usage", {})
    decision = parsed.get("decision", "error")

    if decision not in ("include", "exclude", "uncertain", "insufficient_content"):
        logger.error("Decision fuera de vocabulario esperado: %r para %s -- tratando como error", decision, doc.get("url", "")[:60])
        decision = "error"
        parsed["decision"] = "error"

    if decision == "include" and (parsed.get("comuna") in ("none", "", None) or parsed.get("tipo_conflicto") in ("none", "", None)):
        logger.warning("include=true con comuna/tipo_conflicto vacio en %s -- degradando a uncertain", doc.get("url", "")[:60])
        decision = "uncertain"
        parsed["decision"] = "uncertain"

    # Fix 2026-09-12 (auditoria adversarial de Codex, xhigh, hallazgo
    # bloqueante #3): quote_is_grounded("") devuelve True a proposito
    # (una cita vacia es valida cuando decision != include), pero ese
    # mismo booleano se estaba usando tambien como el gate de include --
    # un include con evidence_quote="" pasaba el chequeo porque "vacio
    # implica grounded=True", no porque hubiera evidencia real. El schema
    # pide "minimo 15 caracteres" solo en la descripcion (documentacion,
    # no una restriccion real de JSON Schema) -- se aplica aca como chequeo
    # explicito, separado de si la cita esta o no gramaticalmente
    # "grounded" en el texto.
    evidence_quote = parsed.get("evidence_quote", "") or ""
    evidence_verified = bool(evidence_quote.strip()) and quote_is_grounded(evidence_quote, doc.get("text", ""))
    if decision == "include" and len(evidence_quote.strip()) < MIN_EVIDENCE_QUOTE_CHARS:
        logger.warning("include=true con evidence_quote vacia o demasiado corta (%d chars) en %s -- degradando a uncertain", len(evidence_quote.strip()), doc.get("url", "")[:60])
        decision = "uncertain"
        parsed["decision"] = "uncertain"
    elif decision == "include" and not evidence_verified:
        logger.warning("evidence_quote no encontrada como substring literal en %s -- degradando a uncertain", doc.get("url", "")[:60])
        decision = "uncertain"
        parsed["decision"] = "uncertain"

    gated = apply_deterministic_gate(parsed, doc.get("text", ""))
    decision = gated["decision_final"]
    gated["decision"] = decision
    parsed = gated

    lineage = doc.get("lineage", {})
    record = {
        "url": doc.get("url"),
        "comuna_descubrimiento": lineage.get("comuna", ""),
        "lineage": lineage,
        "corpus_scope": corpus_scope_for_lineage(lineage),
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "reasoning": result.get("reasoning"),
        "usage": usage,
        "evidence_verified": evidence_verified,
        "evidence_present": bool(evidence_quote.strip()),
        **parsed,
    }
    return decision, record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", type=str, default="", help="Restringir a estas URLs exactas (una por linea) -- para lotes de prueba congelados")
    parser.add_argument("--output-file", type=str, default="", help="Escribir a este archivo en vez de classifications.jsonl -- evita que already_classified_urls() mezcle lotes de prueba con produccion")
    parser.add_argument("--workers", type=int, default=50, help="Llamadas concurrentes a OpenRouter. Default 50 -- verificado empiricamente 2026-09-12 (50/50 sin errores ni 429 en ~34s); OpenRouter no publica un techo duro para cuentas de pago (confirmado contra doc + GET /api/v1/key), asi que el backoff automatico ante 429 absorbe cualquier throttling si se sube mas")
    args = parser.parse_args()

    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    detail = {
        "output_path": str(output_path),
        "es_produccion": (output_path == CLASSIFICATIONS_PATH) and not args.dry_run and not args.urls_file,
        "workers": args.workers,
        "dry_run": args.dry_run,
    }
    try:
        with acquire_lock("classify_luna", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        return exc.return_code


def _run(args) -> int:
    # Fix 2026-09-12 (Codex, hallazgo #4): coordinacion productor/consumidor
    # entre etapas. Bloquea duro solo la corrida de PRODUCCION (sin
    # --output-file/--urls-file/--dry-run, la que escribe a
    # classifications.jsonl de verdad) -- para pruebas puntuales con salida
    # separada, solo se avisa, porque no comprometen el artefacto real.
    es_test = bool(args.output_file or args.urls_file or args.dry_run)
    for etapa_previa in ("fulltext_acquisition_v2", "dedupe_fulltext"):
        if upstream_stage_is_running(etapa_previa):
            msg = f"{etapa_previa} todavia esta corriendo -- el corpus/manifest de dedupe puede estar a medio escribir."
            if es_test:
                logger.warning("%s Continuando de todos modos porque esto es una corrida de prueba (--output-file/--urls-file/--dry-run), no de produccion.", msg)
            else:
                logger.warning("%s Corrida de PRODUCCION -- se sale sin clasificar nada. Reintentar en el proximo ciclo.", msg)
                raise StageSkipped(3, msg)

    if not es_test:
        try:
            review_artifact = json.loads(REVIEW_ARTIFACT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"Gate editorial bloqueado: no se pudo leer {REVIEW_ARTIFACT_PATH}: {exc}"
            logger.warning(msg)
            raise StageSkipped(4, msg)
        if not classification_release_allowed(review_artifact):
            msg = (
                "Gate editorial bloqueado: review_sample_v4_70.json no tiene "
                "status=aprobado_revision_humana, human_review_completed=true y "
                "production_allowed=true. Las corridas de prueba siguen permitidas."
            )
            logger.warning(msg)
            raise StageSkipped(4, msg)

    env = load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("OPENROUTER_API_KEY vacia")
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    urls_filter = None
    if args.urls_file:
        urls_filter = {u.strip() for u in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if u.strip()}
        logger.info("Restringido a --urls-file: %d URLs", len(urls_filter))

    docs = load_classifiable_documents(urls_filter=urls_filter)
    done_urls = already_classified_urls(output_path)
    pending = [d for d in docs if d.get("url") not in done_urls]

    logger.info("Documentos con texto suficiente: %d | ya clasificados en %s: %d | pendientes: %d", len(docs), output_path.name, len(done_urls), len(pending))

    if args.dry_run:
        pending = pending[:1]
    elif args.limit:
        pending = pending[: args.limit]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_cost = 0.0
    counts = {"include": 0, "exclude": 0, "uncertain": 0, "insufficient_content": 0, "error": 0}
    write_lock = threading.Lock()
    n_done = 0

    def process_one(doc: dict[str, Any]) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        result = classify_document(doc, api_key, system_prompt, schema)
        if not result:
            return doc, "error", None
        decision, record = postprocess_result(doc, result)
        return doc, decision, record

    out_file = output_path.open("a", encoding="utf-8") if not args.dry_run else open("nul" if sys.platform == "win32" else "/dev/null", "w")
    try:
        workers = 1 if args.dry_run else max(1, args.workers)
        logger.info("Procesando %d documentos con %d worker(s) concurrentes", len(pending), workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_one, doc): doc for doc in pending}
            for future in as_completed(futures):
                doc, decision, record = future.result()
                n_done += 1
                with write_lock:
                    counts[decision] = counts.get(decision, 0) + 1
                    if record is not None:
                        cost = record.get("usage", {}).get("cost", 0.0) or 0.0
                        total_cost += cost
                        out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                        out_file.flush()
                        logger.info(
                            "[%d/%d] %s -> %s | comuna=%s tipo=%s | costo=$%.5f",
                            n_done, len(pending), doc.get("url", "")[:60], decision,
                            record.get("comuna"), record.get("tipo_conflicto"), cost,
                        )
                    else:
                        logger.info("[%d/%d] %s -> error (sin resultado)", n_done, len(pending), doc.get("url", "")[:60])
    finally:
        out_file.close()

    logger.info("Distribucion de decisiones: %s", counts)
    logger.info("Costo total real: $%.5f USD", total_cost)
    return 0


if __name__ == "__main__":
    sys.exit(main())
