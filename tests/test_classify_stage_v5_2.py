import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "src" / "classify.py"
spec = importlib.util.spec_from_file_location("classify_under_test_v5_2", SCRIPT)
classify_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(classify_module)


def _base(**overrides):
    value = {
        "rol_en_documento": "caso_principal",
        "decision": "include",
        "decision_reason": "Caso documentado.",
        "accion_contenciosa": "confirmada",
        "tipo_accion_contenciosa": "otra_accion_verificable",
        "profundidad_documentacion_caso": "caso_principal",
        "es_proyecto_inmobiliario": "si",
        "es_proyecto_vivienda_inmobiliario": "si",
        "relacion_inmobiliaria_urbana": "inmueble_existente_relevancia_urbana",
        "tipo_objeto_norm": "uso_mixto_residencial",
        "tipo_objeto_raw": "casa existente y centro cultural",
        "precision_geografica": "proyecto_exacto",
        "comuna": "Santiago",
        "tipo_conflicto_norm": "ocupacion_propiedad",
        "tipo_conflicto_raw": "ocupación de inmueble",
        "via_legal_norm": "sin_via_identificada",
        "via_legal_raw": "No se identifica causa formal",
        "lugares_mencionados": [],
        "actores": [],
        "evidencia_accion_quotes": ["Los ocupantes cambian la cerradura."],
        "evidencia_objeto_quotes": ["una casa colonial abandonada"],
        "evidencia_geografica_quotes": ["en Barrio Yungay"],
        "evidence_summary": "Ocupación de una casa existente.",
        "confidence": "media",
    }
    value.update(overrides)
    return value


def _source():
    return "Los ocupantes cambian la cerradura. Ocurre en una casa colonial abandonada en Barrio Yungay."


def test_existing_property_occupation_without_formal_urban_link_is_excluded():
    mention = _base()
    result = classify_module._apply_scope_gate_v2(mention, _source(), "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "exclude"
    assert "inmueble_existente_sin_intervencion_urbana_formal" in result["gate_reasons"]


def test_uncertain_model_decision_is_not_overridden_by_boundary_gate():
    mention = _base(decision="uncertain")
    result = classify_module._apply_scope_gate_v2(mention, _source(), "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "uncertain"


def test_same_boundary_does_not_enter_residential_view():
    mention = _base()
    result = classify_module._apply_scope_gate_v2(mention, _source(), "residencial")
    assert result["decision_final"] == "exclude"
    assert "inmueble_existente_sin_intervencion_urbana_formal" in result["gate_reasons"]


def test_existing_property_with_patrimonial_intervention_remains_broad_candidate():
    mention = _base(
        es_proyecto_vivienda_inmobiliario="no",
        tipo_objeto_norm="inmobiliario_privado_no_residencial",
        tipo_conflicto_norm="patrimonio",
        via_legal_norm="administrativa",
        via_legal_raw="Solicitud formal de protección patrimonial",
        evidencia_action_quotes=None,
    )
    mention["evidencia_accion_quotes"] = ["La organización presentó una solicitud formal de protección patrimonial."]
    source = "La organización presentó una solicitud formal de protección patrimonial. El inmueble es una casa colonial abandonada ubicada en Barrio Yungay."
    result = classify_module._apply_scope_gate_v2(mention, source, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "include"
    assert "inmueble_existente_sin_intervencion_urbana_formal" not in result["gate_reasons"]


def test_pressenza_yungay_regression_is_not_admitted_as_residential_occupation_case():
    artifact = Path(__file__).parents[1] / "Auditoria" / "muestras_control" / "review_sample_v5_1_amplio.json"
    if not artifact.exists():
        pytest.skip("artefacto v5.1 no disponible fuera del checkout del piloto")
    review = json.loads(artifact.read_text(encoding="utf-8"))
    case = next(case for case in review["cases"] if "pressenza" in case["url"])
    mention = case["model_record"]["case_mentions"][0]
    source_text = case["source"]["text"]
    for scope in ("residencial", "inmobiliaria_urbana_amplia"):
        result = classify_module._apply_scope_gate_v2(mention, source_text, scope)
        assert result["decision_final"] == "exclude"
        assert "inmueble_existente_sin_intervencion_urbana_formal" in result["gate_reasons"]
