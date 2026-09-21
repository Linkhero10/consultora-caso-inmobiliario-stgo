"""Regresiones v5.2.2: geografía compuesta y evidencia geográfica corta.

Estos tests no llaman a la API. Cubren solamente el postprocesamiento
determinista que debe ser seguro de recalcular sobre respuestas ya guardadas.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import classify as target  # noqa: E402


SOURCE = (
    "El proyecto fue impugnado mediante un recurso judicial. "
    "La obra se ubica en Las Condes y Vitacura. "
    "El proyecto Vespucio 345 fue paralizado. "
    "La resolución describe los permisos, las partes, los antecedentes y "
    "la controversia administrativa y judicial de la obra con suficiente "
    "detalle para una revisión documental. "
    "El expediente incluye las actuaciones de las partes, la ubicación, "
    "las decisiones institucionales y el desarrollo de la controversia "
    "en varias etapas, de modo que no se trata de una publicación breve."
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
        "tipo_objeto_norm": "objeto_no_determinado",
        "tipo_objeto_raw": "proyecto Vespucio 345",
        "precision_geografica": "proyecto_exacto",
        "comuna": "Las Condes y Vitacura",
        "tipo_conflicto_norm": "permiso_edificacion",
        "via_legal_norm": "judicial",
        "evidencia_accion_quotes": ["fue impugnado mediante un recurso judicial"],
        "evidencia_objeto_quotes": ["proyecto Vespucio 345"],
        "evidencia_geografica_quotes": ["Las Condes", "Vitacura"],
        "lugares_mencionados": [
            {"nombre": "Las Condes", "tipo": "comuna"},
            {"nombre": "Vitacura", "tipo": "comuna"},
        ],
    }
    mention.update(overrides)
    return mention


def test_composite_in_area_communes_are_not_rejected_as_out_of_area():
    result = target.apply_scope_gate(_mention(), SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "include"
    assert "fuera_del_area_geografica" not in result["gate_reasons"]


def test_short_exact_geography_quote_can_be_sufficient_when_ine_backed():
    mention = _mention(
        comuna="Las Condes",
        lugares_mencionados=[
            {"nombre": "Vespucio 345", "tipo": "proyecto"},
            {"nombre": "Las Condes", "tipo": "comuna"},
        ],
        evidencia_geografica_quotes=["Vespucio 345", "Las Condes"],
    )
    result = target.apply_scope_gate(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "include"
    assert result["case_evidence_sufficient"]["geography"] is True
    assert result["short_geography_quote_accepted"] is True


def test_unknown_object_exception_still_requires_geo_evidence():
    mention = _mention(evidencia_geografica_quotes=["ubicación no citada"])
    result = target.apply_scope_gate(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "uncertain"
    assert result["case_evidence_sufficient"]["geography"] is False


def test_out_of_area_comuna_remains_excluded():
    mention = _mention(
        comuna="Viña del Mar",
        lugares_mencionados=[{"nombre": "Viña del Mar", "tipo": "comuna"}],
        evidencia_geografica_quotes=["Viña del Mar"],
    )
    result = target.apply_scope_gate(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "exclude"
    assert "fuera_del_area_geografica" in result["gate_reasons"]


def test_tangential_depth_is_still_hard_exclude():
    mention = _mention(profundidad_documentacion_caso="mencion_tangencial")
    result = target.apply_scope_gate(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "exclude"
    assert "mencion_tangencial" in result["gate_reasons"]


def test_urban_instrument_object_without_real_estate_project_is_admissible_broad():
    """Regresión: Quilicura (declaración de humedal urbano) era excluido en la
    vista amplia porque el gate exigía es_proyecto_inmobiliario="si" incluso
    para un instrumento urbano puro, contradiciendo la propia definición del
    universo amplio (que incluye "instrumentos de planificación urbana")."""
    mention = _mention(
        tipo_objeto_norm="instrumento_urbano_general",
        tipo_objeto_raw="declaratoria de humedal urbano",
        es_proyecto_inmobiliario="no",
        es_proyecto_vivienda_inmobiliario="no",
        relacion_inmobiliaria_urbana="transformacion_regulacion_uso",
        tipo_accion_contenciosa="recurso_judicial",
        evidencia_objeto_quotes=["la controversia administrativa y judicial de la obra"],
    )
    result = target.apply_scope_gate(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "include"
    assert "objeto_no_admisible" not in result["gate_reasons"]


def test_urban_instrument_object_still_requires_residential_link_for_residential_scope():
    mention = _mention(
        tipo_objeto_norm="instrumento_urbano_general",
        tipo_objeto_raw="declaratoria de humedal urbano",
        es_proyecto_inmobiliario="no",
        es_proyecto_vivienda_inmobiliario="no",
        relacion_inmobiliaria_urbana="transformacion_regulacion_uso",
        tipo_accion_contenciosa="recurso_judicial",
        evidencia_objeto_quotes=["la controversia administrativa y judicial de la obra"],
    )
    result = target.apply_scope_gate(mention, SOURCE, "residencial")
    assert result["decision_final"] == "exclude"


def test_private_non_residential_object_still_requires_real_estate_flag():
    """El bypass es solo para instrumento_urbano_general/equipamiento_urbano/
    infraestructura_no_residencial; un centro comercial privado sigue
    exigiendo es_proyecto_inmobiliario="si"."""
    mention = _mention(
        tipo_objeto_norm="centro_comercial",
        es_proyecto_inmobiliario="no",
        es_proyecto_vivienda_inmobiliario="no",
    )
    result = target.apply_scope_gate(mention, SOURCE, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] != "include"


def test_short_social_post_is_not_promoted_by_a_short_geography_label():
    mention = _mention(
        comuna="La Florida",
        lugares_mencionados=[{"nombre": "La Florida", "tipo": "comuna"}],
        evidencia_geografica_quotes=["La Florida"],
    )
    short_source = "CONSTRUYAN EL SEGUNDO PUENTE. Insistimos hacia Peñalolén."
    result = target.apply_scope_gate(mention, short_source, "inmobiliaria_urbana_amplia")
    assert result["decision_final"] == "uncertain"
    assert result["short_geography_quote_accepted"] is False
