import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import build_geography_manzana as target  # noqa: E402


def _fixture_geojson(path: Path) -> None:
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "CUT": 13101, "COMUNA": "SANTIAGO", "PROVINCIA": "SANTIAGO", "REGION": "METROPOLITANA",
                    "MANZENT": 13101011001008, "COD_MANZANA": 8, "COD_DISTRITO": 1, "DISTRITO": "HUELEN",
                    "AREA_C": "URBANO", "TIPO_MZ": "URBANO", "n_per": 188, "n_hog": 123, "n_vp": 144,
                },
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
            },
            {
                "type": "Feature",
                "properties": {
                    "CUT": 13114, "COMUNA": "LAS CONDES", "PROVINCIA": "SANTIAGO", "REGION": "METROPOLITANA",
                    "MANZENT": 13114000000001, "COD_MANZANA": 1, "COD_DISTRITO": 2, "DISTRITO": "APOQUINDO",
                    "AREA_C": "URBANO", "TIPO_MZ": "URBANO", "n_per": 50, "n_hog": 20, "n_vp": 22,
                },
                "geometry": {"type": "Polygon", "coordinates": [[[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]]]},
            },
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_manzana_censal_populates_table_and_summary(tmp_path):
    geojson_path = tmp_path / "manzanas.geojson"
    _fixture_geojson(geojson_path)
    db_path = tmp_path / "warehouse.sqlite"
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    target.ensure_schema(con)
    report = target.load_manzana_censal(con, geojson_path=geojson_path)

    assert report["n_manzanas_total"] == 2
    assert report["n_comunas_con_manzanas"] == 2
    assert report["poblacion_total"] == 238

    row = con.execute("SELECT * FROM manzana_censal WHERE manzana_id = '13101011001008'").fetchone()
    assert dict(row) == {
        "manzana_id": "13101011001008",
        "codigo_comuna_ine": "13101",
        "comuna": "SANTIAGO",
        "cod_distrito": "1",
        "distrito": "HUELEN",
        "area_c": "URBANO",
        "tipo_mz": "URBANO",
        "poblacion": 188,
        "hogares": 123,
        "viviendas_particulares": 144,
    }
    con.close()


def test_load_manzana_censal_is_idempotent_on_rerun(tmp_path):
    geojson_path = tmp_path / "manzanas.geojson"
    _fixture_geojson(geojson_path)
    db_path = tmp_path / "warehouse.sqlite"
    con = sqlite3.connect(str(db_path))
    target.ensure_schema(con)
    target.load_manzana_censal(con, geojson_path=geojson_path)
    report = target.load_manzana_censal(con, geojson_path=geojson_path)
    assert report["n_manzanas_total"] == 2
    con.close()


def test_publish_geojson_copies_file_and_reports_size(tmp_path):
    source = tmp_path / "source.geojson"
    _fixture_geojson(source)
    target_path = tmp_path / "docs" / "manzanas_censales.geojson"
    report = target.publish_geojson(source=source, target=target_path)
    assert target_path.exists()
    assert report["size_bytes"] == source.stat().st_size


def test_publish_geojson_missing_source_raises(tmp_path):
    import pytest

    missing = tmp_path / "does_not_exist.geojson"
    with pytest.raises(FileNotFoundError):
        target.publish_geojson(source=missing, target=tmp_path / "out.geojson")


def test_real_manzanas_geojson_covers_all_32_comunas():
    """Contra el archivo real: sin comunas vacias, con la geometria
    esperada (Maipu >2000 manzanas confirma que la paginacion funciono)."""
    import pytest

    if not target.GEOJSON_SOURCE.exists():
        pytest.skip("GeoJSON de manzanas no disponible en este entorno")
    with target.GEOJSON_SOURCE.open(encoding="utf-8") as f:
        data = json.load(f)
    cuts = {str(feat["properties"]["CUT"]) for feat in data["features"]}
    assert len(cuts) == 32
    maipu_count = sum(1 for feat in data["features"] if str(feat["properties"]["CUT"]) == "13119")
    assert maipu_count > 2000  # confirma paginacion mas alla del limite de 2000 de ArcGIS
