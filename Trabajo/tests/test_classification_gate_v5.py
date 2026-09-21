import importlib.util
import json
from pathlib import Path

import jsonschema


SCRIPT = Path(__file__).parents[1] / "scripts" / "classify_v5.py"
spec = importlib.util.spec_from_file_location("classify_v5_under_test", SCRIPT)
classify_v5 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(classify_v5)


def _base(**overrides):
    value = {
        "decision": "include",
        "accion_contenciosa": "confirmada",
        "tipo_accion_contenciosa": "recurso_judicial",
        "profundidad_documentacion_caso": "caso_principal",
        "es_proyecto_inmobiliario": "si",
        "es_proyecto_vivienda_inmobiliario": "si",
        "tipo_objeto_norm": "edificio_residencial",
        "tipo_objeto_raw": "edificio residencial",
        "precision_geografica": "proyecto_exacto",
        "evidencia_accion_quote": "La junta interpuso un recurso judicial.",
        "evidencia_objeto_quote": "El proyecto contempla viviendas.",
        "evidencia_geografica_quote": "El proyecto se ubica en Peñalolen.",
        "evidence_quote": "La junta interpuso un recurso judicial.",
    }
    value.update(overrides)
    return value


def test_residential_scope_includes_residential_case():
    result = classify_v5.apply_scope_gate(
        _base(),
        "La junta interpuso un recurso judicial. El proyecto contempla viviendas. El proyecto se ubica en Peñalolen.",
        "residencial",
    )
    assert result["decision_final"] == "include"
    assert result["gate_reasons"] == []


def test_broad_scope_includes_non_residential_real_estate_case():
    result = classify_v5.apply_scope_gate(
        _base(
            es_proyecto_vivienda_inmobiliario="no",
            tipo_objeto_norm="centro_comercial",
            tipo_objeto_raw="mall",
            evidencia_objeto_quote="El proyecto contempla un centro comercial.",
        ),
        "La junta interpuso un recurso judicial. El proyecto contempla un centro comercial. El proyecto se ubica en Peñalolen.",
        "inmobiliaria_urbana_amplia",
    )
    assert result["decision_final"] == "include"


def test_same_document_gets_separate_scope_decisions_for_multiple_mentions():
    mentions = [
        _base(),
        _base(
            es_proyecto_vivienda_inmobiliario="no",
            tipo_objeto_norm="centro_comercial",
            tipo_objeto_raw="mall",
            evidencia_objeto_quote="El proyecto contempla un centro comercial.",
        ),
    ]
    result = classify_v5.derive_document_decisions(
        mentions,
        "La junta interpuso un recurso judicial. El proyecto contempla viviendas. El proyecto contempla un centro comercial. El proyecto se ubica en Peñalolen.",
    )
    assert result["decision_residencial"] == "include"
    assert result["decision_inmobiliaria_urbana_amplia"] == "include"
    assert len(result["case_mentions"]) == 2


def test_non_residential_case_is_not_residential_but_remains_broad_candidate():
    mention = _base(
        es_proyecto_vivienda_inmobiliario="no",
        tipo_objeto_norm="centro_comercial",
        tipo_objeto_raw="mall",
        evidencia_objeto_quote="El proyecto contempla un centro comercial.",
    )
    result = classify_v5.derive_document_decisions(
        [mention],
        "La junta interpuso un recurso judicial. El proyecto contempla un centro comercial. El proyecto se ubica en Peñalolen.",
    )
    assert result["decision_residencial"] == "exclude"
    assert result["decision_inmobiliaria_urbana_amplia"] == "include"


def test_unverified_quote_degrades_to_uncertain():
    result = classify_v5.apply_scope_gate(
        _base(evidencia_objeto_quote="Esta frase no aparece."),
        "La junta interpuso un recurso judicial. El proyecto contempla viviendas. El proyecto se ubica en Peñalolen.",
        "residencial",
    )
    assert result["decision_final"] == "uncertain"
    assert "evidencia_objeto_no_verificada" in result["gate_reasons"]


def test_out_of_area_case_is_excluded_in_both_scopes():
    result = classify_v5.apply_scope_gate(
        _base(precision_geografica="fuera_de_area", evidencia_geografica_quote="El proyecto se ubica en Valparaiso."),
        "La junta interpuso un recurso judicial. El proyecto contempla viviendas. El proyecto se ubica en Valparaiso.",
        "inmobiliaria_urbana_amplia",
    )
    assert result["decision_final"] == "exclude"
    assert "fuera_del_area_geografica" in result["gate_reasons"]


def test_v5_schema_accepts_a_minimal_multiple_case_payload():
    schema_path = Path(__file__).parents[1] / "config" / "classification_schema_v5.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))["schema"]
    mention = _base()
    mention.update({
        "rol_en_documento": "caso_principal",
        "decision_reason": "Caso documentado.",
        "es_proyecto_inmobiliario": "si",
        "tipo_objeto_norm": "edificio_residencial",
        "tipo_objeto_raw": "edificio residencial",
        "comuna": "Peñalolén",
        "codigo_comuna_ine": "13122",
        "tipo_conflicto_norm": "densidad_altura",
        "tipo_conflicto_raw": "conflicto por altura",
        "via_legal_norm": "judicial",
        "via_legal_raw": "recurso judicial",
        "lugares_mencionados": [],
        "actores": [],
        "confidence": "alta",
    })
    payload = {
        "decision": "include",
        "decision_reason": "Existe al menos una mención documentada.",
        "case_mentions": [mention, {**mention, "rol_en_documento": "caso_secundario_documentado"}],
        "sentiment": "neutral",
        "source_type": "prensa",
        "confidence": "alta",
    }
    jsonschema.validate(payload, schema)
