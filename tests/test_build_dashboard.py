import json
import re
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import build_dashboard as target  # noqa: E402

WAREHOUSE_PATH = Path(__file__).parents[1] / "data" / "warehouse.sqlite"

VERSION_LEAK_PATTERNS = [
    r"\bv\d+(\.\d+)+\b",
    r"\bv\d+_\d+\b",
    r"depende del snapshot",
]

# Campos snake_case internos conocidos que nunca deberían aparecer crudos en la UI.
KNOWN_RAW_FIELDS = [
    "tipo_conflicto_norm",
    "tipo_objeto_norm",
    "decision_final_amplio",
    "decision_final_residencial",
    "via_legal_norm",
]


@pytest.fixture(scope="module")
def dataset():
    if not WAREHOUSE_PATH.exists():
        pytest.skip("data/warehouse.sqlite no disponible")
    return target.build_dashboard_dataset()


@pytest.fixture(scope="module")
def labels():
    return target._load_labels()


@pytest.fixture(scope="module")
def html(dataset, labels):
    return target.build_html(dataset, labels)


def test_four_tabs_present_and_no_pilot(html):
    for tab in ("Inicio", "Contexto", "Metodología", "Arquitectura"):
        assert tab in html
    # No confundir con la palabra "piloto" que puede aparecer legítimamente en
    # datos reales (ej. un conflicto sobre un "plan piloto de drones"): lo que
    # se elimina es el dashboard de piloto de Estación Central en sí.
    assert "piloto_integracion" not in html.lower()
    assert "piloto de integración" not in html.lower() and "piloto de integracion" not in html.lower()
    assert "warehouse_v1" not in html.lower()


def test_no_internal_version_text_visible(html):
    for pattern in VERSION_LEAK_PATTERNS:
        matches = re.findall(pattern, html, flags=re.IGNORECASE)
        assert not matches, f"Fuga de version detectada ({pattern}): {matches[:5]}"


def test_no_raw_snake_case_field_names_in_ui_strings(html):
    # Los nombres de campo pueden aparecer como *claves* dentro del JSON de datos
    # (eso es inevitable e inocuo); lo que no debe pasar es que se rendericen
    # como texto plano fuera del bloque de datos.
    script_start = html.index("<script>")
    ui_html = html[:script_start]
    for field in KNOWN_RAW_FIELDS:
        assert field not in ui_html


def test_embedded_dataset_is_valid_json(html):
    start = html.index("const DATA = ") + len("const DATA = ")
    end = html.index(";\nconst D = ")
    payload = html[start:end]
    parsed = json.loads(payload)
    assert "dataset" in parsed and "labels" in parsed


def test_basemap_attribution_present(html):
    assert "OpenStreetMap" in html
