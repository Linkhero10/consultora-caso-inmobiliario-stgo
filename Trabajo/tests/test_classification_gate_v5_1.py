import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "classify_v5_1.py"
spec = importlib.util.spec_from_file_location("classify_v5_1_under_test", SCRIPT)
classify_v5_1 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(classify_v5_1)


def _base(**overrides):
    value = {
        "rol_en_documento": "caso_principal",
        "decision": "include",
        "decision_reason": "Caso documentado.",
        "accion_contenciosa": "confirmada",
        "tipo_accion_contenciosa": "recurso_judicial",
        "profundidad_documentacion_caso": "caso_principal",
        "es_proyecto_inmobiliario": "si",
        "es_proyecto_vivienda_inmobiliario": "si",
        "tipo_objeto_norm": "edificio_residencial",
        "tipo_objeto_raw": "edificio residencial",
        "relacion_inmobiliaria_urbana": "desarrollo_proyecto",
        "precision_geografica": "proyecto_exacto",
        "comuna": "Peñalolén",
        "tipo_conflicto_norm": "densidad_altura",
        "tipo_conflicto_raw": "conflicto por altura",
        "via_legal_norm": "judicial",
        "via_legal_raw": "recurso judicial",
        "evidencia_accion_quotes": ["La junta interpuso un recurso judicial."],
        "evidencia_objeto_quotes": ["El proyecto contempla viviendas."],
        "evidencia_geografica_quotes": ["El proyecto se ubica en Peñalolén."],
        "evidence_summary": "La junta interpuso un recurso judicial por un proyecto de viviendas.",
        "lugares_mencionados": [],
        "actores": [],
        "confidence": "alta",
    }
    value.update(overrides)
    return value


def test_multiple_literal_quotes_are_verified_independently_and_include():
    mention = _base(
        evidencia_accion_quotes=["La junta interpuso un recurso judicial.", "La Corte suspendió las obras."],
    )
    result = classify_v5_1.apply_scope_gate(
        mention,
        "La junta interpuso un recurso judicial. La Corte suspendió las obras. El proyecto contempla viviendas. El proyecto se ubica en Peñalolén.",
        "residencial",
    )
    assert result["decision_final"] == "include"
    assert result["evidence_action_quotes_verified"] == [True, True]


def test_invalid_extra_quote_is_exposed_without_discarding_valid_evidence():
    mention = _base(evidencia_accion_quotes=["La junta interpuso un recurso judicial.", "Texto inventado."])
    result = classify_v5_1.apply_scope_gate(
        mention,
        "La junta interpuso un recurso judicial. El proyecto contempla viviendas. El proyecto se ubica en Peñalolén.",
        "residencial",
    )
    assert result["decision_final"] == "uncertain"
    assert result["evidence_action_quotes_verified"] == [True, False]
    assert "evidencia_accion_contrato_invalido" in result["gate_reasons"]


def test_summary_is_not_used_as_literal_evidence():
    mention = _base(
        evidencia_accion_quotes=["La junta interpuso un recurso judicial."],
        evidence_summary="Síntesis inventada que no aparece literalmente.",
    )
    result = classify_v5_1.apply_scope_gate(
        mention,
        "La junta interpuso un recurso judicial. El proyecto contempla viviendas. El proyecto se ubica en Peñalolén.",
        "residencial",
    )
    assert result["decision_final"] == "include"


def test_ine_code_is_deterministic_and_existing_property_boundary_is_explicit():
    assert classify_v5_1.derive_ine_code("San Joaquín") == "13129"
    mention = _base(
        es_proyecto_inmobiliario="si",
        es_proyecto_vivienda_inmobiliario="no",
        tipo_objeto_norm="inmobiliario_privado_no_residencial",
        relacion_inmobiliaria_urbana="ocupacion_propiedad_sin_desarrollo",
        evidencia_objeto_quotes=["Una casa colonial abandonada."],
    )
    result = classify_v5_1.apply_scope_gate(
        mention,
        "La junta interpuso un recurso judicial. Una casa colonial abandonada. El proyecto se ubica en Peñalolén.",
        "inmobiliaria_urbana_amplia",
    )
    assert result["decision_final"] == "exclude"
    assert "objeto_existente_sin_vinculo_urbano" in result["gate_reasons"]


def test_v5_1_schema_requires_arrays_and_summary():
    schema_path = Path(__file__).parents[1] / "config" / "classification_schema_v5_1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))["schema"]
    mention = _base()
    payload = {
        "decision": "include",
        "decision_reason": "Caso documentado.",
        "case_mentions": [mention],
        "sentiment": "neutral",
        "source_type": "prensa",
        "confidence": "alta",
    }
    jsonschema.validate(payload, schema)
    with pytest.raises(jsonschema.ValidationError):
        bad = json.loads(json.dumps(payload))
        bad["case_mentions"][0]["evidencia_accion_quotes"] = "una cadena"
        jsonschema.validate(bad, schema)
