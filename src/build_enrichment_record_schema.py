#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera enrichment_record_schema_v3_2.json a partir de enrichment_schema_v3_2.json
(el contrato que responde el LLM) mas los campos derivados que enrich_case_v3.py
agrega en el postprocesamiento (verify_literal_quote_field y metadata del run).

Hallazgo real de la revisión (2026-09-16): el schema del LLM tiene additionalProperties:
false en 4 capas, pero el registro que se ESCRIBE a enrichment.jsonl incluye
campos que el postprocesamiento agrega DESPUES de jsonschema.validate() contra
ese schema (cita_verificada, cita_original_modelo, evidencia_hito_verificada,
evidencia_hito_original_modelo, evidencia_objeto_disputa_verificada,
evidencia_objeto_disputa_original_modelo, mas metadata de run) -- el artefacto
persistido real nunca se valida contra su propio contrato. Este script genera
ese segundo contrato para poder cerrar ese hueco (ver validate_record() en
enrich_case_v3.py)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LLM_SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_schema.json"
RECORD_SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_record_schema.json"


def _add_verification_fields(item_schema: dict, field: str) -> None:
    """Agrega {field}_verificada (bool, required) y {field}_original_modelo
    (string, NO required -- solo aparece cuando la verificacion falla) a un
    schema de objeto que tiene additionalProperties: false."""
    item_schema["properties"][f"{field}_verificada"] = {"type": "boolean"}
    item_schema["properties"][f"{field}_original_modelo"] = {"type": "string"}
    if f"{field}_verificada" not in item_schema["required"]:
        item_schema["required"].append(f"{field}_verificada")


def build_record_schema() -> dict:
    llm_schema_wrapper = json.loads(LLM_SCHEMA_PATH.read_text(encoding="utf-8"))
    # El wrapper de OpenRouter tiene forma {"name":..., "schema": {...}} o es
    # directamente el schema -- soportar ambos, igual que enrich_case_v3.py.
    inner_key = "schema" if "schema" in llm_schema_wrapper else None
    inner = copy.deepcopy(llm_schema_wrapper[inner_key] if inner_key else llm_schema_wrapper)

    # 1. actores[]: agregar cita_verificada / cita_original_modelo
    actor_item = inner["properties"]["actores"]["items"]
    _add_verification_fields(actor_item, "cita")

    # 2. instituciones_mencionadas[]: agregar cita_verificada / cita_original_modelo
    inst_item = inner["properties"]["instituciones_mencionadas"]["items"]
    _add_verification_fields(inst_item, "cita")

    # 3. linea_tiempo[]: agregar fecha_year_grounded, evidencia_hito_verificada,
    #    evidencia_hito_original_modelo
    hito_item = inner["properties"]["linea_tiempo"]["items"]
    hito_item["properties"]["fecha_year_grounded"] = {"type": "boolean"}
    hito_item["properties"]["evidencia_hito_verificada"] = {"type": "boolean"}
    hito_item["properties"]["evidencia_hito_original_modelo"] = {"type": "string"}
    for f in ("fecha_year_grounded", "evidencia_hito_verificada"):
        if f not in hito_item["required"]:
            hito_item["required"].append(f)

    # Hallazgo real del usuario (2026-09-17, corrida completa de 934): la
    # validacion dura de proyecto_asociado (debia coincidir literal con
    # proyectos_mencionados) cuarenteno 68/869 documentos (7.8%), TODOS en
    # actores[11] (ultimo actor de un array saturado en 12) con basura de
    # generacion (caracteres de multiples alfabetos). Ahora
    # sanitize_project_associations() limpia el campo en vez de descartar
    # el registro completo -- mismo patron que las citas: _verificada +
    # _original_modelo cuando no coincide.
    for item_schema in (actor_item, inst_item, hito_item):
        _add_verification_fields(item_schema, "proyecto_asociado")

    # 4. top-level: evidencia_objeto_disputa_verificada / _original_modelo
    _add_verification_fields(inner, "evidencia_objeto_disputa")

    # Hallazgo real de la auditoría (auditoria de lanzamiento, 2026-09-16): los
    # maxItems del schema (actores=12, instituciones=10, linea_tiempo=5) no
    # dejan constancia de si el modelo omitio elementos -- un documento con
    # exactamente 12 actores es indistinguible de uno con 20 actores reales
    # que se corto en 12. Estos flags son DETERMINISTICOS (len(lista) ==
    # maxItems), calculados en el postprocesamiento, NO le piden nada nuevo
    # al LLM ni tocan enrichment_schema_v3.json (el contrato congelado).
    inner["properties"]["actores_posiblemente_truncados"] = {"type": "boolean"}
    inner["properties"]["instituciones_posiblemente_truncadas"] = {"type": "boolean"}
    inner["properties"]["hitos_posiblemente_truncados"] = {"type": "boolean"}
    for f in ("actores_posiblemente_truncados", "instituciones_posiblemente_truncadas", "hitos_posiblemente_truncados"):
        if f not in inner["required"]:
            inner["required"].append(f)

    # 5. top-level: metadata de run agregada por _run() en enrich_case_v3.py
    #    antes de escribir el registro (ver record = {..., **parsed}).
    metadata_fields = {
        "url": {"type": "string"},
        "decision_documento_etapa1": {"type": "string"},
        "contract_version_etapa1": {"type": ["string", "null"]},
        "lineage": {"type": "object"},
        "content_sha256": {"type": "string"},
        "content_char_count": {"type": "integer"},
        "input_truncated": {"type": "boolean"},
        "enriched_at": {"type": "string"},
        "model": {"type": "string"},
        "reasoning_effort": {"type": "string"},
        "enrichment_schema_version": {"type": "string"},
        "prompt_sha256": {"type": "string"},
        "schema_sha256": {"type": "string"},
        "record_schema_sha256": {"type": "string"},
        "script_sha256": {"type": "string"},
        "run_id": {"type": "string"},
        "usage": {"type": "object"},
        # Fix 2 de la revisión (contabilidad de costo de reintentos): campos nuevos
        # que ahora agrega enrich_document() -- ver ese cambio en
        # enrich_case_v3.py.
        "retry_cost_usd": {"type": "number"},
        "total_incurred_cost_usd": {"type": "number"},
        # Ajuste 1 de la revisión sobre v3.1: paid_attempt_count (respuestas HTTP 200
        # realmente cobradas) es distinto de request_attempt_count (vueltas
        # del loop, incluye 429/timeouts que no se cobran).
        "paid_attempt_count": {"type": "integer"},
        "request_attempt_count": {"type": "integer"},
        # Hallazgo real del usuario (2026-09-17): se pagaba por el
        # razonamiento del modelo (reasoning_tokens en usage) pero se
        # descartaba en memoria sin guardarlo -- classify_v5_1.py ya
        # capturaba estos 3 campos en Etapa 1, el mismo patron faltaba en
        # enrichment. Nullable porque la mayoria de los proveedores
        # devuelven reasoning/reasoning_details cifrados/opacos (None), no
        # siempre texto legible -- eso es normal, no un error.
        "reasoning": {"type": ["string", "null"]},
        "reasoning_details": {"type": ["array", "object", "null"]},
        "raw_finish_reason": {"type": ["string", "null"]},
    }
    for name, subschema in metadata_fields.items():
        inner["properties"][name] = subschema
        if name not in inner["required"]:
            inner["required"].append(name)

    # Mejora de trazabilidad de la revisión (no bloqueante, quinta revision sobre
    # v3.1): el runner de produccion (enrich_case_v3_production.py) agrega
    # runner_script_sha256 y core_enrichment_script_sha256 ademas de
    # script_sha256 -- OPCIONALES porque los registros del piloto
    # (autocontenido, no importa nada) no los tienen.
    optional_metadata_fields = {
        "runner_script_sha256": {"type": "string"},
        "core_enrichment_script_sha256": {"type": "string"},
        # Hallazgo real de la auditoría (2026-09-17, auditoria post-934): el schema
        # de registro cambio en vivo durante la corrida (868/65/1 hashes
        # distintos). Todos los 934 registros validan contra el schema
        # vigente, asi que record_schema_sha256 se normaliza al hash actual;
        # este campo preserva el hash original al momento de generacion,
        # mismo patron que los campos *_original_modelo.
        "record_schema_sha256_at_generation": {"type": "string"},
    }
    for name, subschema in optional_metadata_fields.items():
        inner["properties"][name] = subschema

    inner["title"] = "enrichment_record_v3_2"
    inner["description"] = (
        "Contrato del REGISTRO PERSISTIDO en enrichment.jsonl -- distinto del "
        "contrato de respuesta del LLM (enrichment_schema_v3_2.json). Incluye los "
        "campos que agrega el postprocesamiento (verificacion de citas, "
        "metadata del run). Generado por build_enrichment_record_schema_v3_2.py "
        "a partir de enrichment_schema_v3_2.json -- no editar a mano, regenerar."
    )
    return inner


def main() -> int:
    record_schema = build_record_schema()
    RECORD_SCHEMA_PATH.write_text(
        json.dumps(record_schema, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Escrito: {RECORD_SCHEMA_PATH}")

    import jsonschema
    jsonschema.Draft7Validator.check_schema(record_schema)
    # A diferencia del schema del LLM (donde properties == required siempre),
    # aqui los campos "_original_modelo" son legitimamente opcionales -- solo
    # aparecen cuando verify_literal_quote_field() detecta una cita no
    # verificada. Se listan en properties (porque additionalProperties=false
    # los exige explicitos) pero deliberadamente NO en required.
    optional_by_design = {n for n in record_schema["properties"] if n.endswith("_original_modelo")}
    optional_by_design |= {"runner_script_sha256", "core_enrichment_script_sha256", "record_schema_sha256_at_generation"}
    unexpected_missing = set(record_schema["properties"]) - set(record_schema["required"]) - optional_by_design
    unexpected_extra = set(record_schema["required"]) - set(record_schema["properties"])
    assert not unexpected_missing and not unexpected_extra, (unexpected_missing, unexpected_extra)
    print(f"Schema valido (Draft7). {len(optional_by_design)} campos opcionales por diseno: {sorted(optional_by_design)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
