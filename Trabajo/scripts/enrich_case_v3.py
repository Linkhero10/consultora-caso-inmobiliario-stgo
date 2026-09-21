#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prueba de enrichment_schema_v3 (2026-09-16), antes de congelar y escalar
a los 934 include. v3 agrega, sobre v2 (hallazgos de la revisión y la auditoría, alcance
acotado decidido por Felipe): objeto_disputa_norm/raw, stance por actor
(reemplaza tono_emocional), instituciones_mencionadas[] (reemplaza
institucion_decisora unico), instrumento_norm/raw, via_legal_norm,
resultado_actuacion, date_precision en linea_tiempo. Corre sobre 30
documentos: los 11 del piloto Estacion Central (ya conocidos, para comparar
contra v2) + 19 nuevos elegidos por diversidad de comuna/tipo_objeto_norm
(seed=42, ver Trabajo/scripts/enrich_case_v3.py historial de seleccion).
Nunca corre sobre los 934 include completos -- eso requiere congelar v3
primero y una decision explicita nueva de escalar."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_lock import acquire_lock, LockBusyError, StageSkipped, read_jsonl_tolerant  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("enrich_case_v3")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
CONTENT_DIR = PROJECT_ROOT / "Fuentes" / "fulltext_v2" / "content"
CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5_2_3" / "classifications.jsonl"
SCHEMA_PATH = PROJECT_ROOT / "Trabajo" / "config" / "enrichment_schema_v3_2.json"
# Fix v3.1 (hallazgo real de la revisión): el schema de arriba es el contrato de
# RESPUESTA DEL LLM (additionalProperties: false), pero el registro que se
# escribe a enrichment.jsonl le agrega campos derivados en el postprocesamiento
# (verify_literal_quote_field, metadata del run) -- nunca se validaba ese
# artefacto final contra su propio contrato. RECORD_SCHEMA_PATH es ese
# segundo contrato, generado por build_enrichment_record_schema_v3.py.
RECORD_SCHEMA_PATH = PROJECT_ROOT / "Trabajo" / "config" / "enrichment_record_schema_v3_2.json"
PROMPT_PATH = PROJECT_ROOT / "Trabajo" / "prompts" / "enrichment_system_v3_2.md"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_2_prueba30"
ENRICHMENT_PATH = OUTPUT_DIR / "enrichment.jsonl"

# Guardrail duro: esta prueba esta acotada a 30 documentos (11 del piloto
# Estacion Central + 19 nuevos elegidos por diversidad de comuna/tipo_objeto).
# Nunca debe procesar el corpus include completo (934 documentos) sin que
# eso sea una decision explicita nueva, DESPUES de revisar esta prueba.
PILOT_URLS = [
    # 11 del piloto Estacion Central (ya conocidos con schema v2, para comparar)
    "https://elpais.com/chile/2025-09-17/la-vida-comprimida-en-los-guetos-verticales-de-estacion-central.html",
    "https://elquintopoder.cl/ciudad/la-unica-solucion-para-los-guetos-verticales-en-estacion-central/",
    "https://radio.uchile.cl/2021/05/23/estacion-central-un-recorrido-por-la-comuna-a-cinco-anos-del-boom-de-los-guetos-verticales/",
    "https://transportevertical.org/sitio/guetos-verticales-en-santiago/",
    "https://www.biobiochile.cl/noticias/nacional/region-metropolitana/2022/08/09/el-presente-de-15-guetos-verticales-de-estacion-central-no-son-habitados-por-falta-de-recepcion.shtml",
    "https://www.elciudadano.com/reportaje-investigacion/estacion-central-administracion-de-rodrigo-delgado-recaudo-5-mil-millones-por-polemicos-proyectos-inmobiliarios/03/23/",
    "https://www.elciudadano.com/reportaje-investigacion/las-nuevas-callampas-boom-inmobiliario-en-estacion-central/04/07/",
    "https://www.eldinamo.cl/opinion/2017/07/31/guetos-verticales-miente-miente-que-algo-queda/",
    "https://www.eldinamo.cl/opinion/2017/09/04/guetos-verticales-todos-los-analizados-por-la-autoridad-son-ilegales/",
    "https://www.hogardecristo.cl/entrevistas/alejandro-verdugo-demolamos-al-menos-una-megatorre/",
    "https://www.latercera.com/pulso-pm/noticia/estacion-central-y-los-edificios-fantasma-tres-proyectos-paralizados-por-presiones-politicas-y-perdidas-millonarias/",
    # 19 nuevos, elegidos por diversidad de comuna + tipo_objeto_norm
    # (muestreo aleatorio con seed=42 sobre los 1096 case_mentions include
    # del warehouse, 1 documento por combinacion comuna/tipo_objeto vista)
    "https://www.emol.com/noticias/Economia/2026/01/29/1190050/lo-barnechea-inmobiliaria-conflicto.html",
    "https://www.latercera.com/nacional/noticia/tras-6-anos-de-disputa-lo-barnechea-evita-pagar-millonaria-demanda-ligada-a-paralizacion-de-proyecto-habitacional/",
    "https://www.pjud.cl/prensa-y-comunicaciones/noticias-del-poder-judicial/68597",
    "https://www.ciperchile.cl/2018/06/06/se-atrevera-la-alcaldesa-evelyn-matthei-a-cumplir-la-ley/",
    "https://www.latercera.com/diario-impreso/los-edificios-fantasmas-que-dejo-el-27f/",
    "https://es.linkedin.com/posts/diarioconstitucional_una-corte-de-apelaciones-acogi%C3%B3-un-recurso-activity-7438742653397028865-4heX",
    "https://radio.uchile.cl/2020/01/02/territoria-apoquindo-el-mall-objetado-por-contralaria/",
    "https://interferencia.cl/casos/guetos-verticales",
    "https://www.elmostrador.cl/noticias/pais/2023/02/02/la-triple-amenaza-al-humedal-urbano-mas-grande-del-pais/",
    "https://www.cooperativa.cl/noticias/pais/transportes/metro/talleres-de-la-linea-7-generan-disputa-entre-renca-y-metro/2019-05-31/075043.html",
    "https://www.latercera.com/nacional/noticia/fuenzalida-vs-concha-exdiputado-representa-a-empresa-de-tragamonedas-en-pugna-judicial-en-penalolen/",
    "https://www.df.cl/periodismo-de-soluciones/recuperacion-de-barrios-programas-que-buscan-dar-respuesta-a-la",
    "https://doble-espacio.uchile.cl/millonario-deficit-del-minvu-amenaza-viviendas-sociales-en-pac/",
    "https://www.elperiodista.cl/2023/08/consejo-municipal-de-independencia-rechaza-conciliacion-con-constructora-huidobro/",
    "https://tribunalambiental.cl/sentencia-confirma-rechazo-torres-habitacionales-estacion-central/",
    "https://transparencia.sma.gob.cl/doc/resoluciones/RESOL_EXENTA_SMA_2022/RESOL%20EXENTA%20N%201090%20SMA.PDF",
    "https://radio.uchile.cl/2021/07/19/matriz-de-walmart-en-ee-uu-impartira-clases-de-etica-comercial-a-walmart-chile/",
    "https://www.labatalla.cl/conociendo-a-carlos-carvacho-candidato-a-concejal-de-maipu/",
    "https://www.ex-ante.cl/economia/paralizacion-de-proyecto-inmobiliario-golpea-con-131-despidos-y-325-millones-en-costos/",
]
MAX_PILOT_URLS = 40  # margen de seguridad sobre 30 -- sigue muy lejos de 934

MODEL = "openai/gpt-5.6-luna"
REASONING_EFFORT = "xhigh"
# Fix v3.0.1 (bloqueante real confirmado por la revisión): 8000 truncaba 12/30
# documentos de prueba (40%) y hasta 276/934 del corpus real (29.6%),
# cortando silenciosamente actores/instituciones/hitos que el prompt pide
# "todos" -- el modelo podia responder con aparente exhaustividad sin saber
# que solo vio una fraccion del articulo. Verificado contra los 934 include
# reales: el documento mas largo tiene 29.903 caracteres -- 30000 cubre
# 100% del corpus sin truncar nada, mismo limite que ya usa classify_v5_1.py
# para clasificacion. El costo marginal es despreciable: el texto de entrada
# es ~2% del costo total de una llamada real (el razonamiento domina).
MAX_TEXT_CHARS_FOR_PROMPT = 30000
# 24.947 completion_tokens fue el maximo real visto en 30 casos exitosos
# (razonamiento xhigh + respuesta JSON final); 32000 deja ~30% de margen
# sin permitir que una generacion descontrolada llegue a las 48-64k tokens
# que costaria el caso real de 192.000 caracteres sin este limite.
MAX_COMPLETION_TOKENS = 32000


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


_URL_TO_CONTENT_PATH_CACHE: dict[str, Path] | None = None


def _find_content_path(url: str) -> Path | None:
    global _URL_TO_CONTENT_PATH_CACHE
    if _URL_TO_CONTENT_PATH_CACHE is None:
        _URL_TO_CONTENT_PATH_CACHE = {}
        for path in CONTENT_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            u = data.get("url", "")
            if u:
                _URL_TO_CONTENT_PATH_CACHE[u] = path
    return _URL_TO_CONTENT_PATH_CACHE.get(url)


def load_pilot_cases() -> list[dict[str, Any]]:
    """Carga SOLO los documentos de PILOT_URLS, con su decision_documento
    y el texto completo, desde la clasificacion vigente v5.2.3."""
    if len(PILOT_URLS) > MAX_PILOT_URLS:
        raise RuntimeError(f"PILOT_URLS tiene {len(PILOT_URLS)} URLs, por encima del limite de seguridad {MAX_PILOT_URLS} -- este script no esta disenado para correr a escala completa.")

    by_url = {}
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


def previously_quarantined_urls() -> set[str]:
    """Comportamiento deliberado (confirmado por la revisión): una URL cuarentenada
    en invalid_records.jsonl NO cuenta como 'ya enriquecida' -- una falla de
    schema no es un enriquecimiento completado, asi que se reintenta en la
    proxima corrida y puede generar costo nuevo. Esta funcion solo sirve para
    loguear ese reintento con claridad, no para excluirlo."""
    invalid_path = OUTPUT_DIR / "invalid_records.jsonl"
    if not invalid_path.exists():
        return set()
    return {rec.get("url", "") for rec in read_jsonl_tolerant(invalid_path)}


def normalize_text(s: str) -> str:
    return " ".join(s.lower().split())


def sanitize_project_associations(parsed: dict[str, Any]) -> dict[str, Any]:
    """Corrige (no descarta) las asociaciones proyecto_asociado invalidas.

    Fix real (hallazgo del usuario, 2026-09-17, corrida completa de 934):
    la version anterior de esta logica (validate_project_associations) era
    un gate DURO -- si proyecto_asociado no coincidia literal con
    proyectos_mencionados, se descartaba el registro ENTERO. En la corrida
    real esto cuarenteno 68/869 documentos (7.8%), TODOS en exactamente
    actores[11] (el ultimo actor de un array saturado en maxItems=12) con
    el mismo patron: texto basura de multiples alfabetos pegado al nombre
    del proyecto (ej. 'Vivo בער', 'Estadio Nacionalાઈ', '...asdasdasd') --
    un problema real de generacion degenerada en la ultima posicion de un
    array largo, no un error semantico del modelo. Descartar el documento
    COMPLETO por un solo campo corrupto perdia actores/instituciones/hitos
    buenos junto con el malo.

    Ahora se trata igual que una cita no verificada (verify_literal_quote_field):
    se limpia SOLO el campo malo, se preserva el original en
    proyecto_asociado_original_modelo para auditoria, se marca
    proyecto_asociado_verificada=False, y el resto del registro se
    conserva. Un proyecto_asociado vacio (sin asociacion, caso normal) o
    que coincide literalmente con proyectos_mencionados tambien se marca
    (verificada=True solo si coincide; vacio queda verificada=False, mismo
    criterio que citas vacias -- no aplica, no es un "True" vacuo)."""
    projects = {
        value.strip()
        for value in (parsed.get("proyectos_mencionados", []) or [])
        if isinstance(value, str) and value.strip()
    }
    for collection in ("actores", "instituciones_mencionadas", "linea_tiempo"):
        items = parsed.get(collection, []) or []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            associated = (item.get("proyecto_asociado", "") or "").strip()
            if associated and associated not in projects:
                logger.warning("%s[%d].proyecto_asociado=%r no coincide con proyectos_mencionados -- se preserva en proyecto_asociado_original_modelo, proyecto_asociado queda vacio", collection, i, associated[:80])
                item["proyecto_asociado_original_modelo"] = associated
                item["proyecto_asociado"] = ""
                item["proyecto_asociado_verificada"] = False
            else:
                # Hallazgo real (la auditoría, 2026-09-17, auditoria post-934): el
                # campo coincidia con proyectos_mencionados solo DESPUES de
                # strip(), pero se guardaba el string crudo del modelo (con
                # espacios sobrantes) en vez del valor normalizado -- podia
                # romper joins exactos rio abajo aunque la verificacion
                # semantica fuera correcta.
                item["proyecto_asociado"] = associated
                item["proyecto_asociado_verificada"] = bool(associated)
    return parsed


def validate_record_invariants(parsed: dict[str, Any]) -> list[str]:
    """Aplica invariantes semánticos que JSON Schema no expresa bien.

    proyecto_asociado YA NO se valida aqui como gate duro -- se corrige en
    sanitize_project_associations() antes de llegar a esta funcion (ver
    hallazgo real del 2026-09-17). Los invariantes que SI quedan aqui son
    genuinas contradicciones estructurales (no ruido de generacion
    estocastica): revision.nivel=ninguno con campos/motivo no vacios, o
    un campo marcado _verificada=true con el valor vacio -- ambos indican
    un bug real en el postprocesamiento, no una rareza del modelo."""
    errors: list[str] = []
    revision = parsed.get("revision", {}) or {}
    if revision.get("nivel") == "ninguno":
        if revision.get("campos_afectados"):
            errors.append("revision.nivel=ninguno exige campos_afectados vacío")
        if revision.get("motivo", ""):
            errors.append("revision.nivel=ninguno exige motivo vacío")
    for collection, field in (("actores", "cita"), ("instituciones_mencionadas", "cita")):
        for index, item in enumerate(parsed.get(collection, []) or []):
            if isinstance(item, dict) and item.get(f"{field}_verificada") is True and not (item.get(field, "") or "").strip():
                errors.append(f"{collection}[{index}].{field}_verificada=true exige {field} no vacía")
    for index, item in enumerate(parsed.get("linea_tiempo", []) or []):
        if isinstance(item, dict) and item.get("evidencia_hito_verificada") is True and not (item.get("evidencia_hito", "") or "").strip():
            errors.append(f"linea_tiempo[{index}].evidencia_hito_verificada=true exige evidencia_hito no vacía")
    if parsed.get("evidencia_objeto_disputa_verificada") is True and not (parsed.get("evidencia_objeto_disputa", "") or "").strip():
        errors.append("evidencia_objeto_disputa_verificada=true exige evidencia_objeto_disputa no vacía")
    return errors


def quote_is_grounded(quote: str, source_text: str) -> bool:
    if not quote:
        return True
    return normalize_text(quote) in normalize_text(source_text)


def verify_literal_quote_field(item: dict[str, Any], field: str, source_text: str, label: str) -> dict[str, Any]:
    """Verificador generico de citas literales -- v3.0.1 (hallazgo real de
    la revisión): antes solo existia verify_actor_quotes(), sin equivalente para
    instituciones_mencionadas[].cita ni evidencia_objeto_disputa -- una cita
    inventada en esos campos entraba sin ningun gate. Ahora se aplica el
    mismo chequeo a todo campo citable.

    Tambien corrige el patron anterior de "vaciar la cita si no se
    verifica" (hallazgo de la revisión: borrar oculta la evidencia del error del
    modelo, util para QA). Ahora se preserva el texto original en
    `{field}_original_modelo` cuando no se verifica, y `cita`/el campo en
    si queda vacio solo para no confundirlo con una cita valida -- el
    original NUNCA se pierde."""
    item = dict(item)
    valor = item.get(field, "") or ""
    tiene = bool(valor.strip())
    if not tiene:
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


def compute_truncation_flags(parsed: dict[str, Any], schema: dict) -> dict[str, bool]:
    """Hallazgo real de la auditoría (auditoria de lanzamiento, 2026-09-16): los
    maxItems del schema no dejan constancia de si el modelo omitio
    elementos -- 12 actores reales es indistinguible de 20 reales cortados
    en 12. Heuristica deliberadamente honesta: solo marca 'posiblemente
    truncado' cuando el array llego EXACTO al maxItems (senal de que pudo
    haber mas), nunca intenta adivinar cuantos elementos faltan -- eso
    requeriria preguntarle al modelo de nuevo, fuera de alcance de este fix."""
    inner = schema.get("schema", schema)

    def _maybe_truncated(field: str) -> bool:
        max_items = inner["properties"].get(field, {}).get("maxItems")
        if max_items is None:
            return False
        return len(parsed.get(field, []) or []) >= max_items

    return {
        "actores_posiblemente_truncados": _maybe_truncated("actores"),
        "instituciones_posiblemente_truncadas": _maybe_truncated("instituciones_mencionadas"),
        "hitos_posiblemente_truncados": _maybe_truncated("linea_tiempo"),
    }


def verify_actor_quotes(actores: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    return [verify_literal_quote_field(a, "cita", source_text, f"actor {a.get('nombre','')[:30]!r}") for a in actores]


def verify_institution_quotes(instituciones: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    return [verify_literal_quote_field(i, "cita", source_text, f"institucion {i.get('nombre','')[:30]!r}") for i in instituciones]


_YEAR_RE = re.compile(r"\b(\d{4})\b")


def verify_timeline_descriptions(linea_tiempo: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    """La descripcion de cada hito no es una cita literal exigida por el
    schema (es una sintesis), pero se marca si el año del hito aparece
    literalmente en el texto fuente, para poder filtrar hitos completamente
    fabricados en la revision humana.

    Fix 2026-09-16 (hallazgo real de la auditoría, verificado): la version anterior
    hacia `fecha[:4] in source_text` -- para una fecha como '26 de julio'
    (sin año, formato no-YYYY que el LLM a veces devuelve pese al schema)
    eso comparaba el substring '26 d' contra el texto completo SIN limite
    de palabra, dando falsos positivos (marcaba grounded=True para una
    fecha sin año real). Ahora se exige que `fecha` tenga un año de 4
    digitos al inicio (regex ^\\d{4}) y que ese año aparezca como palabra
    completa (limite de palabra, no substring suelto) en el texto fuente.

    Fix v3.0.1 (hallazgo real de la revisión): fecha_year_grounded solo prueba que
    el año existe EN ALGUNA PARTE del articulo, no que ESE hito especifico
    ocurrio ese año -- un articulo con hitos en 2018/2021/2024 podia mezclar
    fecha y descripcion de hitos distintos y aun asi pasar. Ahora se agrega
    ademas `evidencia_hito_verificada`: la cita literal de ese hito puntual
    (campo nuevo del schema v3.0.1) se verifica como substring real del
    texto fuente -- verificacion en capas: año existe en el articulo (ya
    existia) + la cita especifica de ESTE hito es literal (nuevo)."""
    verified = []
    for hito in linea_tiempo:
        hito = dict(hito)
        fecha = str(hito.get("fecha", "")).strip()
        year_match = re.match(r"^(\d{4})", fecha)
        if year_match:
            year = year_match.group(1)
            hito["fecha_year_grounded"] = bool(_YEAR_RE.search(source_text)) and year in _YEAR_RE.findall(source_text)
        else:
            hito["fecha_year_grounded"] = False
        hito = verify_literal_quote_field(hito, "evidencia_hito", source_text, f"hito {fecha!r}")
        verified.append(hito)
    return verified


def enrich_document(case: dict[str, Any], api_key: str, system_prompt: str, schema: dict, effort: str = REASONING_EFFORT) -> dict[str, Any]:
    # Fix 2 de la revisión sobre v3.1 (hallazgo real, verificado contra el codigo):
    # antes solo se devolvia el `usage` del intento que finalmente se usaba
    # (el exitoso, o el ultimo fallido) -- si un intento anterior ya habia
    # costado dinero (HTTP 200 con JSON invalido, que SI se paga) ese costo
    # se perdia de la contabilidad. Ahora se acumula el costo de CADA
    # respuesta HTTP 200 real (valida o invalida) en retry_cost_usd, y se
    # devuelve por separado del usage del intento final (usage_final), mas
    # total_incurred_cost_usd = suma de todos los intentos.
    attempt_costs: list[float] = []
    text = case.get("_text", "")[:MAX_TEXT_CHARS_FOR_PROMPT]
    user_content = (
        f"TITULO: {case.get('_title', '')}\n"
        f"CLASIFICACION PREVIA (Etapa 1, ya decidida -- no la reevalues): "
        f"decision_documento={case.get('decision_documento')}\n\n"
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
        # Fix 2026-09-16 (hallazgo real de Felipe sobre la prueba de 30 docs):
        # sin tope, una generacion descontrolada del modelo (1/30 caso real:
        # respuesta de 192.000 caracteres, ~48-64k tokens) se paga completa.
        # Los 30 casos reales exitosos nunca superaron 24.947 completion_tokens
        # totales (razonamiento + respuesta); MAX_COMPLETION_TOKENS deja margen
        # generoso (~30%) sobre eso pero corta duro un caso descontrolado mucho
        # antes de los 48-64k tokens que costaria sin este limite.
        "max_tokens": MAX_COMPLETION_TOKENS,
    }

    # Ajuste 1 de la revisión sobre v3.1 (hallazgo real, verificado): attempt_count
    # antes solo contaba respuestas HTTP 200 pagadas -- un 429 o timeout
    # repetido incrementaba el loop pero no attempt_costs, asi que
    # "3 requests, 1 pagado" se reportaba como attempt_count=1. Ahora se
    # distingue request_attempt_count (cada vuelta del loop, se cobre o no)
    # de paid_attempt_count (= len(attempt_costs), solo respuestas HTTP 200).
    request_attempt_count = 0
    max_retries = 5
    for attempt in range(max_retries + 1):
        request_attempt_count += 1
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if resp.status_code == 429:
                if attempt == max_retries:
                    logger.warning("429 persistente tras %d reintentos para %s -- se abandona (costo ya incurrido en intentos previos=$%.5f)", max_retries, case.get("url", "")[:60], sum(attempt_costs))
                    return {"error": "rate_limited_max_retries", "usage": {}, "usage_final": {}, "retry_cost_usd": sum(attempt_costs), "total_incurred_cost_usd": sum(attempt_costs), "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": None, "reasoning_details": None, "raw_finish_reason": None}
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            attempt_costs.append(usage.get("cost", 0.0) or 0.0)
            message = data["choices"][0]["message"]
            content = message["content"]
            # Hallazgo real del usuario (2026-09-17): se pagaba por el
            # razonamiento del modelo (reasoning_tokens, ver usage arriba)
            # pero se descartaba en memoria sin guardarlo -- classify_v5_1.py
            # ya capturaba message.get("reasoning")/("reasoning_details") en
            # la Etapa 1, el mismo patron faltaba aqui. La mayoria de los
            # proveedores devuelven esto cifrado/opaco (no es texto libre
            # legible), pero cuando SI viene un resumen legible, ahora se
            # preserva en vez de perderse.
            reasoning = message.get("reasoning")
            reasoning_details = message.get("reasoning_details")
            # Mismo hallazgo: classify_v5_1.py tambien captura finish_reason
            # (si la respuesta termino normal="stop" o se corto por
            # max_tokens="length") -- diagnostico real para saber si
            # MAX_COMPLETION_TOKENS alguna vez trunca una respuesta legitima.
            raw_finish_reason = data["choices"][0].get("finish_reason")

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                # Fix 2026-09-16 (hallazgo real de la prueba de 30 documentos
                # con schema v3): antes esto caia al except Exception generico
                # y se abandonaba sin reintentar. Un JSON malformado/truncado
                # (visto en 3/30 de esta prueba, ej. char 192076 -- una
                # respuesta anormalmente larga, probable generacion
                # degenerada/en bucle del modelo con el schema mas grande de
                # v3) es potencialmente transitorio -- la generacion es
                # estocastica, reintentar puede dar una respuesta limpia. Se
                # trata igual que un error de conexion (mismo backoff), no
                # se abandona en el primer intento.
                if attempt == max_retries:
                    total_cost = sum(attempt_costs)
                    retry_cost = sum(attempt_costs[:-1])  # todo menos el intento final actual
                    logger.warning("JSON invalido persistente tras %d reintentos para %s: %s (largo respuesta=%d chars) -- se abandona, costo total incurrido=$%.5f en %d intentos", max_retries, case.get("url", "")[:60], exc, len(content), total_cost, len(attempt_costs))
                    # Fix 2026-09-16: la llamada SI se pago (usage viene de
                    # una respuesta HTTP 200 real) aunque el JSON no se pudo
                    # parsear -- no descartar el costo silenciosamente, mismo
                    # criterio que classify_v5_2_1.py para schema_validation_failed.
                    # Fix v3.1 (hallazgo real de la revisión): antes solo se devolvia
                    # `usage` del ultimo intento, perdiendo el costo de
                    # reintentos previos que tambien se pagaron (HTTP 200 con
                    # JSON invalido). Ahora retry_cost_usd = suma de intentos
                    # previos al final, total_incurred_cost_usd = suma de TODOS.
                    return {"error": "json_decode_failed_max_retries", "usage": usage, "usage_final": usage, "retry_cost_usd": retry_cost, "total_incurred_cost_usd": total_cost, "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": reasoning, "reasoning_details": reasoning_details, "raw_finish_reason": raw_finish_reason}
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning("JSON invalido para %s (%s, largo=%d chars) -- reintento %d/%d en %.1fs (costo acumulado hasta ahora=$%.5f)", case.get("url", "")[:60], exc, len(content), attempt + 1, max_retries, wait, sum(attempt_costs))
                time.sleep(wait)
                continue

            try:
                jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
            except jsonschema.ValidationError as val_exc:
                total_cost = sum(attempt_costs)
                retry_cost = sum(attempt_costs[:-1])
                logger.warning("Respuesta no valida contra el schema para %s: %s -- se abandona, costo total incurrido=$%.5f en %d intentos", case.get("url", "")[:60], val_exc.message[:200], total_cost, len(attempt_costs))
                return {"error": f"schema_validation_failed: {val_exc.message[:200]}", "usage": usage, "usage_final": usage, "retry_cost_usd": retry_cost, "total_incurred_cost_usd": total_cost, "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": reasoning, "reasoning_details": reasoning_details, "raw_finish_reason": raw_finish_reason}

            total_cost = sum(attempt_costs)
            retry_cost = sum(attempt_costs[:-1])
            return {"parsed": parsed, "usage": usage, "usage_final": usage, "retry_cost_usd": retry_cost, "total_incurred_cost_usd": total_cost, "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": reasoning, "reasoning_details": reasoning_details, "raw_finish_reason": raw_finish_reason}
        except requests.exceptions.RequestException as exc:
            if attempt == max_retries:
                logger.warning("Error de conexion persistente tras %d reintentos para %s: %s -- se abandona (costo ya incurrido en intentos previos=$%.5f)", max_retries, case.get("url", "")[:60], exc, sum(attempt_costs))
                return {"error": f"connection_error_max_retries: {exc}"[:200], "usage": {}, "usage_final": {}, "retry_cost_usd": sum(attempt_costs), "total_incurred_cost_usd": sum(attempt_costs), "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": None, "reasoning_details": None, "raw_finish_reason": None}
            wait = (2 ** attempt) + random.uniform(0, 1)
            logger.info("Error de conexion transitorio para %s (%s) -- reintento %d/%d en %.1fs", case.get("url", "")[:60], type(exc).__name__, attempt + 1, max_retries, wait)
            time.sleep(wait)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error no recuperable enriqueciendo %s: %s (costo ya incurrido en intentos previos=$%.5f)", case.get("url", "")[:60], exc, sum(attempt_costs))
            return {"error": f"unrecoverable_error: {exc}"[:200], "usage": {}, "usage_final": {}, "retry_cost_usd": sum(attempt_costs), "total_incurred_cost_usd": sum(attempt_costs), "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": None, "reasoning_details": None, "raw_finish_reason": None}
    return {"error": "retry_loop_exhausted_unexpectedly", "usage": {}, "usage_final": {}, "retry_cost_usd": sum(attempt_costs), "total_incurred_cost_usd": sum(attempt_costs), "paid_attempt_count": len(attempt_costs), "request_attempt_count": request_attempt_count, "reasoning": None, "reasoning_details": None, "raw_finish_reason": None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--effort", type=str, default=REASONING_EFFORT, choices=["none", "minimal", "low", "medium", "high", "xhigh"])
    parser.add_argument("--workers", type=int, default=5, help="Corridas concurrentes -- fix 2026-09-16: el piloto original corria secuencial (1 documento a la vez), ~2min/doc a xhigh hacia que 11 documentos tardaran ~20min. Con ThreadPoolExecutor y este acotado a <=20 URLs (MAX_PILOT_URLS) no hay riesgo de saturar la API como si fuera produccion a escala.")
    args = parser.parse_args()

    detail = {"effort": args.effort, "es_produccion": not args.dry_run, "limit": args.limit, "piloto_acotado": True, "n_urls_piloto": len(PILOT_URLS)}
    try:
        with acquire_lock("enrich_case_v3", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        return exc.return_code


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run(args) -> int:
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

    quarantined_urls = previously_quarantined_urls()
    reintentos_cuarentena = [c.get("url", "") for c in pending if c.get("url") in quarantined_urls]
    if reintentos_cuarentena:
        logger.warning("%d URL(s) pendientes fueron cuarentenadas en una corrida anterior (fallaron record schema) y se van a REINTENTAR, con costo nuevo: %s", len(reintentos_cuarentena), reintentos_cuarentena)

    logger.info("Casos piloto: %d | ya enriquecidos: %d | pendientes: %d | reintentos de cuarentena: %d", len(cases), len(done_urls), len(pending), len(reintentos_cuarentena))

    if args.dry_run:
        logger.info("DRY RUN: %d documentos pendientes, sin llamadas a la API. Muestra: %s", len(pending), [c["url"] for c in pending[:5]])
        return 0
    if args.limit:
        pending = pending[: args.limit]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    errors_path = OUTPUT_DIR / "errors.jsonl"
    manifest_path = OUTPUT_DIR / f"run_manifest.{run_id}.json"
    prompt_sha256 = _sha256_file(PROMPT_PATH)
    schema_sha256 = _sha256_file(SCHEMA_PATH)
    record_schema_sha256 = _sha256_file(RECORD_SCHEMA_PATH)
    script_sha256 = _sha256_file(Path(__file__).resolve())

    total_cost = 0.0
    revision_niveles = {"ninguno": 0, "campo": 0, "caso": 0, "bloqueante": 0}
    n_triage_consistency_flags = 0
    n_hitos_totales = 0
    n_written = 0
    n_errors = 0
    n_record_schema_failures = 0

    invalid_path = OUTPUT_DIR / "invalid_records.jsonl"
    with ENRICHMENT_PATH.open("a", encoding="utf-8") as out_file, errors_path.open("a", encoding="utf-8") as err_file, invalid_path.open("a", encoding="utf-8") as invalid_file, ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(enrich_document, case, api_key, system_prompt, schema, args.effort): case for case in pending}
        for future in as_completed(futures):
            case = futures[future]
            result = future.result()
            if not result or "error" in result:
                n_errors += 1
                # Fix v3.1 (hallazgo real de la revisión): usar total_incurred_cost_usd
                # (suma de TODOS los intentos HTTP 200, validos o no), no solo
                # el usage del ultimo intento -- antes se perdia el costo de
                # reintentos previos que tambien se habian pagado.
                failed_cost = (result or {}).get("total_incurred_cost_usd", 0.0) or 0.0
                total_cost += failed_cost
                err_file.write(json.dumps({
                    "url": case.get("url"),
                    "error": (result or {}).get("error", "enrich_document_returned_none"),
                    "cost_incurred_usd": failed_cost,
                    "paid_attempt_count": (result or {}).get("paid_attempt_count", 0),
                    "request_attempt_count": (result or {}).get("request_attempt_count", 0),
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + "\n")
                err_file.flush()
                logger.warning("Fallo para %s (costo incurrido=$%.5f en %d intentos pagados) -- registrado en errors.jsonl", case.get("url", "")[:70], failed_cost, (result or {}).get("paid_attempt_count", 0))
                continue

            parsed = result["parsed"]
            usage = result.get("usage", {})
            cost = result.get("total_incurred_cost_usd", usage.get("cost", 0.0) or 0.0)
            total_cost += cost

            source_text = case.get("_text", "")
            parsed["actores"] = verify_actor_quotes(parsed.get("actores", []), source_text)
            parsed["instituciones_mencionadas"] = verify_institution_quotes(parsed.get("instituciones_mencionadas", []), source_text)
            parsed["linea_tiempo"] = verify_timeline_descriptions(parsed.get("linea_tiempo", []), source_text)
            parsed = verify_literal_quote_field(parsed, "evidencia_objeto_disputa", source_text, "objeto_disputa")
            parsed = sanitize_project_associations(parsed)
            invariant_errors = validate_record_invariants(parsed)
            nivel = parsed.get("revision", {}).get("nivel", "ninguno")

            record = {
                "url": case.get("url"),
                "decision_documento_etapa1": case.get("decision_documento"),
                "contract_version_etapa1": case.get("contract_version"),
                "lineage": case.get("_lineage", {}),
                "content_sha256": _sha256_text(source_text),
                "content_char_count": len(source_text),
                "input_truncated": len(source_text) > MAX_TEXT_CHARS_FOR_PROMPT,
                "enriched_at": datetime.now(timezone.utc).isoformat(),
                "model": MODEL,
                "reasoning_effort": args.effort,
                # Ajuste 2 de la revisión sobre v3.1: antes decia "v3" aunque el
                # instrumento congelado ya es v3.1 (QA graduado,
                # nivel_involucramiento, instrumento_norm ampliado, etc).
                # Los hashes ya permitian reconstruir la version exacta, pero
                # el string ahora tambien lo dice explicitamente.
                "enrichment_schema_version": "v3.2",
                "prompt_sha256": prompt_sha256,
                "schema_sha256": schema_sha256,
                "record_schema_sha256": record_schema_sha256,
                "script_sha256": script_sha256,
                "run_id": run_id,
                "usage": usage,
                "retry_cost_usd": result.get("retry_cost_usd", 0.0),
                "total_incurred_cost_usd": cost,
                "paid_attempt_count": result.get("paid_attempt_count", 1),
                "request_attempt_count": result.get("request_attempt_count", 1),
                # Hallazgo real del usuario (2026-09-17): se pagaba por el
                # razonamiento del modelo pero se descartaba sin guardarlo --
                # classify_v5_1.py ya capturaba estos 3 campos en Etapa 1, el
                # mismo patron faltaba en enrichment. reasoning/reasoning_details
                # suelen venir cifrados/opacos segun el proveedor (no siempre
                # texto legible), pero se preservan tal cual venga.
                "reasoning": result.get("reasoning"),
                "reasoning_details": result.get("reasoning_details"),
                "raw_finish_reason": result.get("raw_finish_reason"),
                **compute_truncation_flags(parsed, schema),
                **parsed,
            }

            # Fix v3.1 (bloqueante real de la revisión): antes, un registro que
            # fallaba la validacion contra su propio contrato se escribia
            # IGUAL a enrichment.jsonl -- el schema era un monitor, no un
            # gate, y el proposito de crear este segundo contrato (garantizar
            # que TODO lo que esta en enrichment.jsonl lo cumple) quedaba
            # incumplido. Ahora un registro invalido se CUARENTENA en
            # invalid_records.jsonl (se conserva integro: url, costos,
            # hashes, run_id, la respuesta pagada completa) y NO entra al
            # archivo canonico -- cuenta como error, no como escrito.
            try:
                if invariant_errors:
                    raise ValueError("; ".join(invariant_errors))
                jsonschema.validate(instance=record, schema=record_schema)
            except (jsonschema.ValidationError, ValueError) as val_exc:
                n_record_schema_failures += 1
                n_errors += 1
                error_message = getattr(val_exc, "message", str(val_exc))
                logger.error("Registro persistido NO valido contra los contratos v3.2 para %s: %s -- cuarentenado en invalid_records.jsonl, NO entra a enrichment.jsonl", case.get("url", "")[:70], error_message[:200])
                invalid_file.write(json.dumps({
                    "url": case.get("url"),
                    "validation_error": error_message[:500],
                    "record": record,
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + "\n")
                invalid_file.flush()
                continue

            # Fix v3.1 (hallazgo real de la revisión): estos contadores alimentan el
            # manifest, que debe describir SOLO lo que quedo en
            # enrichment.jsonl -- antes se incrementaban ANTES de la
            # validacion del record schema, asi que un documento cuarentenado
            # (nunca llega al archivo canonico) igual sumaba a
            # n_hitos_totales/revision_niveles/n_triage_consistency_flags.
            # Movido a despues del PASS de jsonschema.validate().
            n_hitos_totales += len(parsed.get("linea_tiempo", []))
            revision_niveles[nivel] = revision_niveles.get(nivel, 0) + 1
            if parsed.get("triage_consistency_check"):
                n_triage_consistency_flags += 1

            out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_file.flush()
            n_written += 1

            logger.info(
                "[%d/%d] %s -> proyecto=%r hitos=%d actores=%d (central=%d) revision=%s truncado=%s | costo=$%.5f",
                n_written, len(pending), case.get("url", "")[:60],
                parsed.get("nombre_proyecto", "")[:40], len(parsed.get("linea_tiempo", [])),
                len(parsed.get("actores", [])),
                sum(1 for a in parsed.get("actores", []) if a.get("nivel_involucramiento") == "central"),
                nivel, record["input_truncated"], cost,
            )

    esperados = len(pending)
    counts_consistent = (n_written + n_errors == esperados)
    if not counts_consistent:
        logger.error("Inconsistencia de conteos: escritos=%d + errores=%d != esperados=%d", n_written, n_errors, esperados)

    manifest = {
        "run_id": run_id,
        "started_pending": esperados,
        "written": n_written,
        "errors": n_errors,
        "counts_consistent": counts_consistent,
        "total_cost_usd": total_cost,
        "hitos_linea_tiempo": n_hitos_totales,
        "revision_niveles": revision_niveles,
        "triage_consistency_flags": n_triage_consistency_flags,
        "record_schema_validation_failures": n_record_schema_failures,
        "prompt_path": str(PROMPT_PATH.relative_to(PROJECT_ROOT)),
        "prompt_sha256": prompt_sha256,
        "schema_path": str(SCHEMA_PATH.relative_to(PROJECT_ROOT)),
        "schema_sha256": schema_sha256,
        "record_schema_path": str(RECORD_SCHEMA_PATH.relative_to(PROJECT_ROOT)),
        "record_schema_sha256": _sha256_file(RECORD_SCHEMA_PATH),
        "script_sha256": script_sha256,
        "workers": args.workers,
        "effort": args.effort,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("Total enriquecidos: %d | errores: %d | hitos linea_tiempo: %d | revision_niveles: %s | triage_consistency_flags: %d | fallas de schema del registro persistido: %d | costo total: $%.5f USD | manifest: %s", n_written, n_errors, n_hitos_totales, revision_niveles, n_triage_consistency_flags, n_record_schema_failures, total_cost, manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
