import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "src" / "_classify_pipeline" / "classify_luna.py"
spec = importlib.util.spec_from_file_location("classify_luna_under_test", SCRIPT)
classify_luna = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(classify_luna)


def _base(**overrides):
    value = {
        "decision": "include",
        "es_proyecto_vivienda_inmobiliario": "si",
        "tipo_objeto": "edificio_residencial",
        "precision_geografica": "proyecto_exacto",
        "accion_contenciosa": "confirmada",
        "tipo_accion_contenciosa": "recurso_judicial",
        "profundidad_documentacion_caso": "caso_principal",
        "evidencia_accion_quote": "La junta interpuso un recurso de proteccion.",
        "evidencia_objeto_quote": "El proyecto contempla viviendas sociales.",
        "evidencia_geografica_quote": "El proyecto se ubica en Peñalolen.",
        "evidence_quote": "La junta interpuso un recurso de proteccion.",
    }
    value.update(overrides)
    return value


def test_opinion_without_contentious_action_is_excluded():
    result = classify_luna.apply_deterministic_gate(
        _base(
            accion_contenciosa="no",
            tipo_accion_contenciosa="ninguna",
            evidencia_accion_quote="El director cuestiona la tardanza.",
        ),
        "El director cuestiona la tardanza.",
    )

    assert result["decision_final"] == "exclude"
    assert "sin_accion_contenciosa" in result["gate_reasons"]


def test_tangential_out_of_area_mention_cannot_be_included():
    result = classify_luna.apply_deterministic_gate(
        _base(
            precision_geografica="fuera_de_area",
            profundidad_documentacion_caso="mencion_tangencial",
            evidencia_accion_quote="#TomasVodanovich en contra del proyecto.",
            evidencia_objeto_quote="#AvdaPajaritos",
            evidencia_geografica_quote="Parque Pumpin en Valparaiso.",
        ),
        "Parque Pumpin en Valparaiso. #TomasVodanovich en contra del proyecto. #AvdaPajaritos",
    )

    assert result["decision_final"] == "exclude"
    assert "fuera_del_area_geografica" in result["gate_reasons"]
    assert "mencion_tangencial" in result["gate_reasons"]


def test_action_without_explicit_residential_object_is_uncertain():
    result = classify_luna.apply_deterministic_gate(
        _base(
            tipo_objeto="objeto_no_determinado",
            es_proyecto_vivienda_inmobiliario="incierto",
            evidencia_objeto_quote="La inmobiliaria impugno la declaracion de humedal urbano.",
        ),
        "La inmobiliaria impugno la declaracion de humedal urbano.",
    )

    assert result["decision_final"] == "uncertain"
    assert "objeto_no_determinado" in result["gate_reasons"]


def test_include_requires_all_positive_gates_and_literal_quotes():
    result = classify_luna.apply_deterministic_gate(
        _base(),
        "La junta interpuso un recurso de proteccion. El proyecto contempla viviendas sociales. El proyecto se ubica en Peñalolen.",
    )

    assert result["decision_final"] == "include"
    assert result["gate_reasons"] == []
    assert result["evidence_action_verified"] is True
    assert result["evidence_object_verified"] is True
    assert result["evidence_geo_verified"] is True


def test_postprocess_persists_model_and_final_decisions_separately():
    doc = {
        "url": "https://example.test/costanera",
        "text": "El director cuestiona la tardanza en obras de mitigacion.",
        "lineage": {"comuna": "Santiago"},
    }
    parsed = _base(
        accion_contenciosa="no",
        tipo_accion_contenciosa="ninguna",
        evidencia_accion_quote="El director cuestiona la tardanza en obras de mitigacion.",
        evidence_quote="El director cuestiona la tardanza en obras de mitigacion.",
        comuna="Santiago",
        tipo_conflicto="vial_transito",
    )
    decision, record = classify_luna.postprocess_result(
        doc,
        {"parsed": parsed, "usage": {}, "reasoning": "test"},
    )

    assert decision == "exclude"
    assert record["decision_modelo"] == "include"
    assert record["decision"] == "exclude"
    assert "sin_accion_contenciosa" in record["gate_reasons"]


def test_original_v3_false_positive_records_cannot_pass_v4_gate():
    report = Path(__file__).parents[1] / "Auditoria" / "muestras_control" / "reporte_falsos_positivos_v3.json"
    if not report.exists():
        import pytest

        pytest.skip("artefacto de auditoria no disponible fuera del checkout de desarrollo")
    data = __import__("json").loads(report.read_text(encoding="utf-8"))
    for case in data["casos"]:
        old_record = case["respuesta_completa_del_modelo"]
        gated = classify_luna.apply_deterministic_gate(
            old_record,
            case["texto_completo_del_articulo"],
        )
        assert gated["decision_final"] != "include", case["url"]

    limit_case = data["caso_3_limite_no_confirmado"]
    gated_limit = classify_luna.apply_deterministic_gate(
        limit_case["respuesta_completa_del_modelo"],
        limit_case["texto_completo_del_articulo"],
    )
    assert gated_limit["decision_final"] != "include"


def test_production_release_requires_explicit_human_approval():
    assert classify_luna.classification_release_allowed({
        "status": "pendiente_revision_humana",
        "review_policy": {
            "human_review_completed": False,
            "production_allowed": False,
        },
    }) is False
    assert classify_luna.classification_release_allowed({
        "status": "aprobado_revision_humana",
        "review_policy": {
            "human_review_completed": True,
            "production_allowed": True,
        },
    }) is True
