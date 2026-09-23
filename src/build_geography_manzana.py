#!/usr/bin/env python3
"""Fase C: capa de contexto social fino por manzana censal (Censo 2024, INE).

## Qué es y qué no es esta capa

`manzana_censal` agrega, a nivel de manzana (la unidad geográfica más fina
del Censo, muchísimo más pequeña que una comuna), población total, hogares
y viviendas particulares de las 32 comunas de la Provincia de Santiago.
Sirve para dar contexto socioeconómico fino alrededor de los conflictos ya
registrados a nivel de comuna -- nunca para pretender ubicar un conflicto
en una manzana específica.

Se investigó explícitamente si el warehouse permite ubicar conflictos con
esa precisión (join espacial punto-en-polígono contra `geocoded_location`,
que ya tiene lat/lon resueltas para algunos lugares). Resultado: las únicas
7 filas de `geocoded_location` con coordenadas resueltas Y vinculadas a un
conflicto (`geocoded_location_conflict`) están marcadas
`relation_type='contextual_location'` -- es decir, por diseño de Fase B
(ver docstring de `build_geography.py`), esas coordenadas son "un lugar
mencionado en el documento", NO una determinación curada de que ahí ocurre
el conflicto. Tratar esas 7 coordenadas como si fueran el sitio exacto del
conflicto violaría el mismo principio que motivó esa distinción en primer
lugar ("ausencia de resolución > relación inventada"). Por eso esta fase
NO hace ese join: el mapa por manzana es un mapa de contexto social, el
mapa por comuna sigue siendo el único nivel al que se le atribuyen
conflictos.

## Fuente de datos

INE, Censo 2024, ArcGIS FeatureServer `Censo2024_v2` capa 6 ("Manzanas_CPV24"),
descargado para las 32 comunas de la Provincia de Santiago (paginado, sin
comunas vacías) en `Fuentes/fuentes_externas/raw/F-20/`. La geometría del
GeoJSON fue simplificada (`shapely.simplify`, tolerancia 0.00005 grados,
~5.5 m en la latitud de Santiago, `preserve_topology=True`) para que el
archivo publicado quede bajo 25 MB; el detalle exacto de esa simplificación
queda documentado en `manzanas_censales_manifest.json` junto al GeoJSON.

## Qué hace este script

1. Copia el GeoJSON (ya simplificado) a `docs/manzanas_censales.geojson`
   -- servido estático por GitHub Pages, cargado por el navegador vía
   `fetch()` en `build_dashboard.py`, nunca embebido en el payload principal
   del dashboard (22+ MB no deben viajar en cada carga de página).
2. Construye la tabla `manzana_censal` (atributos, sin geometría -- la
   geometría vive solo en el GeoJSON publicado, para no duplicar ~20 MB
   dentro de `data/warehouse.sqlite`) para que los conteos/sumas por comuna
   sean auditables por SQL igual que el resto del pipeline.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE_PATH = PROJECT_ROOT / "data" / "warehouse.sqlite"
GEOJSON_SOURCE = PROJECT_ROOT / "Fuentes" / "fuentes_externas" / "raw" / "F-20" / "manzanas_censales_provincia_santiago.geojson"
GEOJSON_PUBLISHED = PROJECT_ROOT / "docs" / "manzanas_censales.geojson"

SCHEMA = """
CREATE TABLE IF NOT EXISTS manzana_censal (
    manzana_id TEXT PRIMARY KEY,
    codigo_comuna_ine TEXT NOT NULL,
    comuna TEXT NOT NULL,
    cod_distrito TEXT,
    distrito TEXT,
    area_c TEXT,
    tipo_mz TEXT,
    poblacion INTEGER,
    hogares INTEGER,
    viviendas_particulares INTEGER
);
CREATE INDEX IF NOT EXISTS idx_manzana_censal_comuna ON manzana_censal(codigo_comuna_ine);
"""


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)


def publish_geojson(source: Path = GEOJSON_SOURCE, target: Path = GEOJSON_PUBLISHED) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(f"GeoJSON de manzanas no encontrado: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"source": str(source), "published": str(target), "size_bytes": target.stat().st_size}


def load_manzana_censal(con: sqlite3.Connection, geojson_path: Path = GEOJSON_SOURCE) -> dict[str, Any]:
    with geojson_path.open(encoding="utf-8") as f:
        data = json.load(f)
    features = data["features"]

    con.execute("DELETE FROM manzana_censal")
    rows = []
    for feat in features:
        p = feat["properties"]
        rows.append(
            (
                str(p["MANZENT"]),
                str(p["CUT"]),
                p.get("COMUNA"),
                str(p.get("COD_DISTRITO")) if p.get("COD_DISTRITO") is not None else None,
                p.get("DISTRITO"),
                p.get("AREA_C"),
                p.get("TIPO_MZ"),
                p.get("n_per"),
                p.get("n_hog"),
                p.get("n_vp"),
            )
        )
    con.executemany(
        "INSERT OR REPLACE INTO manzana_censal (manzana_id, codigo_comuna_ine, comuna, cod_distrito, distrito, "
        "area_c, tipo_mz, poblacion, hogares, viviendas_particulares) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()

    por_comuna = dict(
        con.execute(
            "SELECT codigo_comuna_ine, COUNT(*) FROM manzana_censal GROUP BY codigo_comuna_ine"
        ).fetchall()
    )
    return {
        "n_manzanas_total": len(rows),
        "n_comunas_con_manzanas": len(por_comuna),
        "poblacion_total": con.execute("SELECT SUM(poblacion) FROM manzana_censal").fetchone()[0],
    }


def main(warehouse_path: Path = WAREHOUSE_PATH) -> int:
    publish_report = publish_geojson()
    con = _connect(warehouse_path)
    try:
        ensure_schema(con)
        load_report = load_manzana_censal(con)
    finally:
        con.close()

    print("geojson publicado:", publish_report)
    print("manzana_censal:", load_report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
