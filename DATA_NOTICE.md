# Nota sobre los datos

## Datos propios

Los esquemas, identidad resuelta (proyecto/caso/conflicto/actor), clasificaciones, anotaciones y
análisis derivados en `src/`, `config/`, `data/`, `audit/` y `docs/` son trabajo original de
los autores. Ver [LICENSE](LICENSE).

## Datos de terceros

`Fuentes/` contiene texto e imágenes recuperados de fuentes públicas (prensa, actas municipales,
literatura académica, fuentes DS19) mediante scraping para fines de investigación.

**Que una fuente sea de acceso público no implica autorización para redistribuir una copia
completa de su contenido.** Por eso este repositorio **no versiona el texto completo ni los PDFs
de fuentes de terceros**:

- `Fuentes/fulltext/content/` (texto completo extraído de artículos de prensa) y
  `Fuentes/literatura/pdf/` (documentos originales) están excluidos vía `.gitignore` — solo se
  versiona metadata (`document_id`, `url`, `fuente`, `fecha`, `hash`, `lineage`, etiquetas y citas
  breves), que sí vive en el warehouse y en los JSONL de clasificación/enriquecimiento versionados.
- Localmente (fuera de git) esas carpetas siguen existiendo para que el pipeline pueda reprocesar
  el corpus — solo no se distribuyen junto con el repositorio.
- Si se necesita compartir el fulltext completo con un socio o cliente puntual, hacerlo por un
  canal separado (no un repositorio compartido/público), evaluando la fuente y el uso caso a caso.

## Diccionario de topónimos (geocodificación)

`Fuentes/fuentes_externas/raw/F-19/geo_dictionary_bcn.csv` es un gazetteer de 41.358 topónimos
con coordenadas, derivado de capas vectoriales oficiales de la **Biblioteca del Congreso Nacional
de Chile (BCN)** (`Toponimos_BCN`, `Areas_Pobladas_BCN`) más nombres administrativos derivados.
Se usa únicamente como referencia de lectura para `src/geocode_locations.py` (resolución de
texto de lugar a coordenada, sin fuzzy matching); no se redistribuyen los shapefiles BCN
originales, solo este CSV ya derivado. Atribución: Biblioteca del Congreso Nacional de Chile.

## Manzanas censales (Censo 2024, contexto social fino)

`Fuentes/fuentes_externas/raw/F-20/manzanas_censales_provincia_santiago.geojson` (y su copia
publicada `docs/manzanas_censales.geojson`) contiene geometría de manzana censal y variables
poblacionales agregadas (población, hogares, viviendas particulares) de las 32 comunas de la
Provincia de Santiago, derivadas del **Censo de Población y Vivienda 2024** del Instituto Nacional
de Estadísticas (INE) de Chile, vía su servicio público ArcGIS FeatureServer
(`Censo2024_v2`, capa `Manzanas_CPV24`). La geometría fue simplificada
(`shapely.simplify`, tolerancia 0.00005°, ~5.5 m) para reducir el tamaño del archivo publicado;
ver `manzanas_censales_manifest.json` junto al GeoJSON para el detalle exacto (fecha, conteos por
comuna, tolerancia, SHA-256). Atribución: Instituto Nacional de Estadísticas (INE) de Chile.
