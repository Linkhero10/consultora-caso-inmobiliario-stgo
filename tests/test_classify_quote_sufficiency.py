import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "src" / "classify.py"


def test_quote_sufficiency_gate_layer_exists_as_a_distinct_composition_step():
    """La capa de suficiencia/limpieza de citas debe seguir existiendo como
    funcion propia dentro de classify.py, separada de la capa final
    (apply_scope_gate)."""
    assert SCRIPT.exists(), "falta classify.py"
    assert hasattr(target, "_apply_scope_gate_v3")


sys.path.insert(0, str(SCRIPT.parent))
import classify as target  # noqa: E402


SOURCE = (
    "El proyecto inmobiliario fue impugnado mediante un recurso judicial. "
    "Se ubica en Vitacura y contempla departamentos."
)


def _mention(**overrides):
    mention = {
        "rol_en_documento": "caso_principal",
        "decision": "include",
        "accion_contenciosa": "confirmada",
        "tipo_accion_contenciosa": "recurso_judicial",
        "profundidad_documentacion_caso": "caso_principal",
        "es_proyecto_inmobiliario": "si",
        "es_proyecto_vivienda_inmobiliario": "si",
        "relacion_inmobiliaria_urbana": "desarrollo_proyecto",
        "tipo_objeto_norm": "uso_mixto_residencial",
        "tipo_objeto_raw": "departamentos",
        "precision_geografica": "proyecto_exacto",
        "comuna": "Vitacura",
        "tipo_conflicto_norm": "permiso_edificacion",
        "via_legal_norm": "judicial",
        "evidencia_accion_quotes": ["fue impugnado mediante un recurso judicial"],
        "evidencia_objeto_quotes": ["contempla departamentos"],
        "evidencia_geografica_quotes": ["Se ubica en Vitacura"],
    }
    mention.update(overrides)
    return mention


def test_one_valid_quote_and_one_invalid_quote_remains_include_with_quality_flag():
    mention = _mention(evidencia_geografica_quotes=["Se ubica en Vitacura", "en Santiago centro"])
    result = target._apply_scope_gate_v3(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "include"
    assert result["case_evidence_sufficient"]["all"] is True
    assert result["quote_set_fully_clean"]["geography"] is False
    assert "geografica_quote_set_not_fully_clean" in result["quality_flags"]
    assert "evidencia_geografica_contrato_invalido" not in result["gate_reasons"]


def test_category_without_any_valid_quote_remains_uncertain():
    """La limpieza relajada no puede convertir evidencia ausente en include."""
    mention = _mention(evidencia_geografica_quotes=["una ubicación no citada"])
    result = target._apply_scope_gate_v3(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["case_evidence_sufficient"]["geography"] is False
    assert result["decision_final"] == "uncertain"
    assert "evidencia_geografica_no_verificada" in result["gate_reasons"]


def test_broad_scope_accepts_explicit_project_without_subtype_but_residential_does_not():
    mention = _mention(
        es_proyecto_vivienda_inmobiliario="incierto",
        tipo_objeto_norm="objeto_no_determinado",
        tipo_objeto_raw="proyecto inmobiliario con departamentos",
    )
    broad = target._apply_scope_gate_v3(mention, SOURCE, "inmobiliaria_urbana_amplia")
    residential = target._apply_scope_gate_v3(mention, SOURCE, "residencial")
    assert broad["decision_final"] == "include"
    assert broad["object_gate_exception"] == "broad_explicit_project_without_subtype"
    assert residential["decision_final"] == "uncertain"
    assert "objeto_no_determinado" in residential["gate_reasons"]


def test_uncertain_model_decision_is_preserved():
    mention = _mention(decision="uncertain")
    result = target._apply_scope_gate_v3(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "uncertain"


def test_existing_property_boundary_remains_hard_exclude():
    mention = _mention(
        tipo_conflicto_norm="ocupacion_propiedad",
        relacion_inmobiliaria_urbana="inmueble_existente_relevancia_urbana",
        via_legal_norm="none",
        tipo_objeto_norm="centro_comercial",
        tipo_objeto_raw="inmueble existente",
        evidencia_objeto_quotes=["contempla departamentos"],
    )
    result = target._apply_scope_gate_v3(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "exclude"
    assert "inmueble_existente_sin_intervencion_urbana_formal" in result["gate_reasons"]
