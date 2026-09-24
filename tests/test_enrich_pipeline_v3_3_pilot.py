import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _enrich_pipeline_v3_3_pilot import (
    _case_mentions_context_block,
    sanitize_project_associations_v3_3,
)


def test_context_block_lists_case_mentions_with_index_objeto_comuna_decision():
    case = {
        "case_mentions": [
            {
                "tipo_objeto_raw": "construccion de dos torres de 38 pisos",
                "evidencia_objeto_quotes": ["la construccion de dos torres de 38 pisos con mas de mil departamentos"],
                "comuna": "Estacion Central",
                "decision": "include",
            },
            {"tipo_objeto_raw": "", "evidencia_objeto_quotes": [], "comuna": "Estacion Central", "decision": "exclude"},
        ]
    }
    block = _case_mentions_context_block(case)
    assert "[0]" in block and "[1]" in block
    assert "construccion de dos torres de 38 pisos" in block
    assert "comuna=Estacion Central" in block
    assert "decision=include" in block
    assert "decision=exclude" in block


def test_context_block_handles_no_case_mentions():
    block = _case_mentions_context_block({"case_mentions": []})
    assert "ninguna" in block.lower()


def test_sanitize_keeps_valid_index_and_marks_verificado_true():
    parsed = {
        "proyectos_mencionados": [{"nombre": "Torre A", "case_mention_index": 0}],
        "actores": [], "instituciones_mencionadas": [], "linea_tiempo": [],
    }
    out = sanitize_project_associations_v3_3(parsed, n_case_mentions=2)
    assert out["proyectos_mencionados"][0]["case_mention_index"] == 0
    assert out["proyectos_mencionados"][0]["case_mention_index_verificada"] is True


def test_sanitize_clears_out_of_range_index_but_preserves_original():
    parsed = {
        "proyectos_mencionados": [{"nombre": "Torre B", "case_mention_index": 5}],
        "actores": [], "instituciones_mencionadas": [], "linea_tiempo": [],
    }
    out = sanitize_project_associations_v3_3(parsed, n_case_mentions=2)
    item = out["proyectos_mencionados"][0]
    assert item["case_mention_index"] is None
    assert item["case_mention_index_original_modelo"] == 5
    assert item["case_mention_index_verificada"] is False


def test_sanitize_clears_negative_index():
    parsed = {
        "proyectos_mencionados": [{"nombre": "Torre C", "case_mention_index": -1}],
        "actores": [], "instituciones_mencionadas": [], "linea_tiempo": [],
    }
    out = sanitize_project_associations_v3_3(parsed, n_case_mentions=2)
    item = out["proyectos_mencionados"][0]
    assert item["case_mention_index"] is None
    assert item["case_mention_index_original_modelo"] == -1


def test_sanitize_null_index_stays_null_and_not_verificado():
    parsed = {
        "proyectos_mencionados": [{"nombre": "Torre D", "case_mention_index": None}],
        "actores": [], "instituciones_mencionadas": [], "linea_tiempo": [],
    }
    out = sanitize_project_associations_v3_3(parsed, n_case_mentions=3)
    item = out["proyectos_mencionados"][0]
    assert item["case_mention_index"] is None
    assert "case_mention_index_original_modelo" not in item
    assert item["case_mention_index_verificada"] is False


def test_sanitize_still_validates_proyecto_asociado_against_new_object_shaped_names():
    parsed = {
        "proyectos_mencionados": [{"nombre": "Torre A", "case_mention_index": 0}],
        "actores": [
            {"nombre": "Juan", "proyecto_asociado": "Torre A"},
            {"nombre": "Pedro", "proyecto_asociado": "Torre Inexistente"},
        ],
        "instituciones_mencionadas": [], "linea_tiempo": [],
    }
    out = sanitize_project_associations_v3_3(parsed, n_case_mentions=1)
    actores = out["actores"]
    assert actores[0]["proyecto_asociado"] == "Torre A"
    assert actores[0]["proyecto_asociado_verificada"] is True
    assert actores[1]["proyecto_asociado"] == ""
    assert actores[1]["proyecto_asociado_original_modelo"] == "Torre Inexistente"
    assert actores[1]["proyecto_asociado_verificada"] is False
