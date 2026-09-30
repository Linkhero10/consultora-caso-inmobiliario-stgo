#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera `config/enrichment_record_schema.json` a partir de `config/enrichment_schema.json`.

El primero es el contrato del REGISTRO PERSISTIDO en `enrichment.jsonl`; el segundo, el contrato de
RESPUESTA del LLM (additionalProperties: false en todas las capas). El registro que se escribe incluye
campos que el postprocesamiento agrega DESPUES de validar la respuesta contra su contrato (`*_verificada`,
`*_original_modelo`, metadata de la corrida). Sin un segundo contrato, el artefacto persistido real nunca
se validaba contra nada. Este script lo deriva del primero para que ambos no diverjan; una prueba
(`tests/test_enrichment_record_schema_in_sync.py`) exige que el archivo versionado sea exactamente lo que
este script genera.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LLM_SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_schema.json"
RECORD_SCHEMA_PATH = PROJECT_ROOT / "config" / "enrichment_record_schema.json"


def _add_verification_fields(item_schema: dict, field: str) -> None:
    """Agrega `{field}_verificada` (bool, obligatorio) y `{field}_original_modelo` (string, opcional: solo
    aparece cuando la verificacion falla) a un schema de objeto con additionalProperties: false."""
    item_schema["properties"][f"{field}_verificada"] = {"type": "boolean"}
    item_schema["properties"][f"{field}_original_modelo"] = {"type": "string"}
    if f"{field}_verificada" not in item_schema["required"]:
        item_schema["required"].append(f"{field}_verificada")


def build_record_schema() -> dict:
    llm_schema_wrapper = json.loads(LLM_SCHEMA_PATH.read_text(encoding="utf-8"))
    # El contrato puede venir envuelto como {"name":..., "schema": {...}} (formato de la API) o directo.
    inner = copy.deepcopy(llm_schema_wrapper["schema"] if "schema" in llm_schema_wrapper else llm_schema_wrapper)

    actor_item = inner["properties"]["actores"]["items"]
    inst_item = inner["properties"]["instituciones_mencionadas"]["items"]
    hito_item = inner["properties"]["linea_tiempo"]["items"]

    _add_verification_fields(actor_item, "cita")
    _add_verification_fields(inst_item, "cita")

    hito_item["properties"]["fecha_year_grounded"] = {"type": "boolean"}
    hito_item["properties"]["evidencia_hito_verificada"] = {"type": "boolean"}
    hito_item["properties"]["evidencia_hito_original_modelo"] = {"type": "string"}
    for f in ("fecha_year_grounded", "evidencia_hito_verificada"):
        if f not in hito_item["required"]:
            hito_item["required"].append(f)

    # Un proyecto_asociado que no coincide con ningun proyecto mencionado se limpia (no se descarta el
    # registro): queda marcado `_verificada=false` y el original se conserva en `_original_modelo`.
    for item_schema in (actor_item, inst_item, hito_item):
        _add_verification_fields(item_schema, "proyecto_asociado")

    _add_verification_fields(inner, "evidencia_objeto_disputa")

    # Cada proyecto mencionado lleva el indice de case_mention que eligio el modelo. Un indice fuera de
    # rango se limpia a null, queda `_verificada=false` y el valor crudo se conserva en `_original_modelo`.
    project_item = inner["properties"]["proyectos_mencionados"]["items"]
    project_item["properties"]["case_mention_index_verificada"] = {"type": "boolean"}
    project_item["properties"]["case_mention_index_original_modelo"] = {"type": "integer"}
    if "case_mention_index_verificada" not in project_item["required"]:
        project_item["required"].append("case_mention_index_verificada")
    inner["properties"]["decision_documento_etapa1"] = {"type": ["string", "null"]}

    # Banderas deterministas (len(lista) == maxItems): un arreglo que llega exacto a su tope pudo haber
    # sido cortado. Se calculan en el postprocesamiento; no se le piden al modelo.
    truncation_flags = (
        "actores_posiblemente_truncados", "instituciones_posiblemente_truncadas", "hitos_posiblemente_truncados",
    )
    for flag in truncation_flags:
        inner["properties"][flag] = {"type": "boolean"}
        if flag not in inner["required"]:
            inner["required"].append(flag)

    # Metadata de la corrida que agrega `enrichment_core.process_document` antes de escribir el registro.
    metadata_fields = {
        "url": {"type": "string"},
        "n_case_mentions_etapa1": {"type": "integer"},
        "decision_documento_etapa1": {"type": ["string", "null"]},
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
        "run_id": {"type": "string"},
        "usage": {"type": "object"},
        # Contabilidad de costo: una respuesta HTTP 200 se cobra aunque su JSON sea invalido, asi que
        # `paid_attempt_count` (respuestas cobradas) es distinto de `request_attempt_count` (vueltas del
        # loop, incluye 429/timeouts que no se cobran).
        "retry_cost_usd": {"type": "number"},
        "total_incurred_cost_usd": {"type": "number"},
        "paid_attempt_count": {"type": "integer"},
        "request_attempt_count": {"type": "integer"},
        # Nullables: la mayoria de los proveedores devuelven el razonamiento cifrado u opaco.
        "reasoning": {"type": ["string", "null"]},
        "reasoning_details": {"type": ["array", "object", "null"]},
        "raw_finish_reason": {"type": ["string", "null"]},
    }
    for name, subschema in metadata_fields.items():
        inner["properties"][name] = subschema
        if name not in inner["required"]:
            inner["required"].append(name)

    # Opcionales: trazabilidad adicional que no todas las corridas registran.
    optional_metadata_fields = {
        "record_schema_sha256": {"type": "string"},
        "script_sha256": {"type": "string"},
        "runner_script_sha256": {"type": "string"},
        "core_enrichment_script_sha256": {"type": "string"},
    }
    for name, subschema in optional_metadata_fields.items():
        inner["properties"][name] = subschema

    inner["title"] = "enrichment_record"
    inner["description"] = (
        "Contrato del REGISTRO PERSISTIDO en enrichment.jsonl, distinto del contrato de respuesta del LLM "
        "(enrichment_schema.json). Incluye los campos que agrega el postprocesamiento (verificacion de citas, "
        "metadata de la corrida). Generado por build_enrichment_record_schema.py a partir de "
        "enrichment_schema.json -- no editar a mano, regenerar."
    )
    return inner


OPTIONAL_BY_DESIGN = {"record_schema_sha256", "script_sha256", "runner_script_sha256", "core_enrichment_script_sha256"}


def main() -> int:
    record_schema = build_record_schema()
    RECORD_SCHEMA_PATH.write_text(
        json.dumps(record_schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Escrito: {RECORD_SCHEMA_PATH}")

    import jsonschema
    jsonschema.Draft7Validator.check_schema(record_schema)
    # Los campos `*_original_modelo` son opcionales por diseno (solo aparecen cuando una verificacion falla):
    # figuran en `properties` porque additionalProperties=false los exige explicitos, y no en `required`.
    optional_by_design = {n for n in record_schema["properties"] if n.endswith("_original_modelo")} | OPTIONAL_BY_DESIGN
    unexpected_missing = set(record_schema["properties"]) - set(record_schema["required"]) - optional_by_design
    unexpected_extra = set(record_schema["required"]) - set(record_schema["properties"])
    assert not unexpected_missing and not unexpected_extra, (unexpected_missing, unexpected_extra)
    print(f"Schema valido (Draft7). {len(optional_by_design)} campos opcionales por diseno")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
