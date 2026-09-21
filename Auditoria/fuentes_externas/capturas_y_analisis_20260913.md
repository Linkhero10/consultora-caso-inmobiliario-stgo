# Capturas y análisis de fuentes externas - 2026-09-13

## Estado de la ronda

Esta ronda hizo una **captura controlada y reproducible**, no un crawler
indiscriminado. Se conservaron los bytes originales, URL solicitada y final,
fecha, tipo de contenido, tamaño, SHA-256 y estado en:

- `Auditoria/fuentes_externas/external_manifest_v1.jsonl`
- `Fuentes/fuentes_externas/raw/<source_id>/`

Resultado materializado: **108 registros de adquisición; 105 respuestas guardadas
como OK y 3 errores HTTP; 105 archivos raw; 73.062.736 bytes**. Los resultados
siguen separados del snapshot de prensa y ninguna fuente pasa automáticamente
a producción.

El inventario quedó enganchado a `stage_2_arcos` mediante el deliverable
`Inventario estratégico de fuentes y decisiones de incorporación por arco` y
el gate bloqueante `source_inventory_reviewed` en
`Trabajo/config/stage_roadmap.yaml`. La etapa actual sigue siendo
`stage_1_corpus`; esta captura no la cierra ni habilita por sí sola los arcos.

## Productos derivados creados

La normalización se ejecuta sin red con
`Trabajo/scripts/normalize_external_sources_v1.py` y produce:

- `Fuentes/fuentes_externas/normalized/censo_2024_layer_catalog.csv`
- `Fuentes/fuentes_externas/normalized/censo_2024_comunal_provincia_santiago.csv`
- `Fuentes/fuentes_externas/normalized/censo_2024_provincial_santiago.csv`
- `Fuentes/fuentes_externas/normalized/censo_2024_manzana_entidad_sample_santiago.csv`
- `Fuentes/fuentes_externas/normalized/casen_2024_file_catalog.csv`
- `Fuentes/fuentes_externas/normalized/casen_2024_provincia_comuna.csv`
- `Fuentes/fuentes_externas/normalized/gtfs_feed_catalog.csv`
- `Fuentes/fuentes_externas/normalized/arclim_layers.csv`
- `Fuentes/fuentes_externas/normalized/arclim_indicators.csv`
- `Fuentes/fuentes_externas/normalized/arclim_hot_days_comunas.csv`
- `Fuentes/fuentes_externas/normalized/arclim_hot_days_series_santiago.csv`

Las exclusiones deliberadas y su condición de desbloqueo están en
`Auditoria/fuentes_externas/acquisition_exclusions_20260913.json`. Las probes
ArcGIS iniciales con respuesta HTML se marcan explícitamente en
`Auditoria/fuentes_externas/content_quality_exceptions_20260913.json` y no se
usan como datos.

## Hallazgos por fuente

### F-01 - INE, Censo 2024

La página oficial expone dashboard comunal, experiencia geográfica,
visualizador manzana-entidad y Redatam. El dashboard ArcGIS contiene servicios
públicos que se pudieron identificar y consultar:

`https://services5.arcgis.com/hUyD8u3TeZLKPe4T/arcgis/rest/services/Censo2024_v2/FeatureServer`

Se capturaron metadatos del servicio y de sus 13 capas, y conteos válidos:

| Capa | Nombre | Geometría | Registros | Campos |
|---:|---|---|---:|---:|
| 0 | Toponimos_Localidad_CPV24 | punto | 9.378 | 3 |
| 1 | Etiquetado_CPV24 | línea | 70.359 | 4 |
| 2 | Zonal_CPV24 | polígono | 4.911 | 212 |
| 3 | Regional_CPV24 | polígono | 16 | 211 |
| 4 | Provincial_CPV24 | polígono | 56 | 196 |
| 5 | Manzanas_Entidades_CPV24 | polígono | 244.756 | 233 |
| 6 | Manzanas_CPV24 | polígono | 216.341 | 216 |
| 7 | Localidades_CPV24 | polígono | 9.736 | 202 |
| 8 | Limite_Urbano_CPV24 | polígono | 592 | 208 |
| 9 | Entidades_CPV24 | polígono | 28.415 | 212 |
| 10 | Distrital_CPV24 | polígono | 2.758 | 202 |
| 11 | Comunal_CPV24 | polígono | 345 | 215 |
| 12 | Aldeas_CPV24 | polígono | 725 | 203 |

Además se capturó una consulta comunal de la provincia de Santiago: **32
comunas, 215 variables por comuna**, y una consulta provincial de una fila.
La muestra de manzanas/entidades contiene 10 registros de la comuna de
Santiago, sin geometría, para validar campos antes de pedir lotes mayores.

El registro comunal incluye población, estructura etaria, migración,
pertenencia a pueblos originarios, discapacidad, educación, trabajo,
transporte, hogares, tenencia, internet, tipo de vivienda, hacinamiento,
déficit cuantitativo, materiales, agua, saneamiento, electricidad y basura.
Como comprobación de escala, la fila de Santiago trae `n_per=438856`,
`n_inmigrantes=176956`, `n_hog=206458`, `n_viv_hacinadas=19640`,
`n_viv_irrecuperables=708` y `n_hog_allegados=6672`. Son valores de fuente,
no estimaciones nuestras.

Uso analítico recomendado: denominadores territoriales y estratificación
social para los conflictos; no inferir causalidad ni mezclar niveles
comunal/manzana sin documentar el cambio de unidad.

### F-03 - CASEN 2024

Se capturaron la página, **15 libros temáticos**, dos libros de códigos, la
programación CEPAL, y las representaciones provincia/comuna en DTA, RData y
SPSS. Los 17 XLSX suman **1.563 hojas**. El catálogo de archivos conserva URL,
hash, tamaño y número/nombres de hojas.

La base `casen_2024_provincia_comuna` contiene **218.367 filas y 6 columnas**
(`folio`, `id_persona`, `expp`, `expc`, `provincia`, `comuna`): es una base de
enlace geográfico, no el microdato temático completo.

Los libros cubren pobreza, pobreza multidimensional y severa, ingreso,
trabajo, educación, salud, vivienda, inseguridad alimentaria, NNA, personas
mayores, población nacida fuera de Chile, pueblos indígenas, discapacidad y
resultados regionales. El codebook exige respetar factores de expansión,
pseudoestratos y pseudoconglomerados cuando se estimen indicadores.

No se descargaron los microdatos nacionales DTA (~1,6 GB), SAV (~750 MB) ni
RData (~47 MB). Tampoco se inventó una ruta para la programación IPM cuyo URL
requiere resolver encoding. La decisión y las condiciones para desbloquearla
están en `acquisition_exclusions_20260913.json`.

Uso analítico recomendado: primero usar los resultados temáticos y la base
provincia/comuna como contexto/denominador; sólo abrir el microdato nacional
si existe un estimando concreto, presupuesto, revisión de PII/licencia y un
flujo reanudable.

### F-13 - DTPM GTFS

Se capturaron dos feeds, que no forman todavía un panel histórico comparable:

| Feed | Paradas | Rutas | Viajes | stop_times | Calendario | Vigencia | Versión |
|---|---:|---:|---:|---:|---|---|---|
| `GTFS_20260829.zip` | 18.445 | 427 | 26.137 | 1.097.285 | 6 + 18 excepciones | 2026-08-29 a 2026-12-31 | V167.20260829 |
| `GTFS PO06dic+2vuelta.zip` | 13.054 | 428 | 20.293 | 1.168.426 | 4 + 8 excepciones | 2025-12-13 a 2026-01-31 | V150.20251213 |

El uso inmediato es calcular accesibilidad/transporte alrededor de eventos o
proyectos, conservando la versión del feed. No se debe comparar directamente
ambos archivos como si fueran mediciones de la misma ventana.

### F-14 - ARClim

La documentación PDF capturada (14 páginas, diciembre de 2025) confirma una
API JSON/CSV para capas, indicadores, atributos, series por entidad y series
diarias. La API declara **29 capas geográficas, 69 indicadores climáticos y
162 atributos para la capa comunas**. Las capas incluyen comunas, provincias,
regiones, asentamientos, censo 2017, cuencas, glaciares, parques, SNASPE y
otros objetos territoriales.

La tabla comunal capturada contiene 345 comunas. Para `hot_days` anual en
Santiago (`ComCod=13101`) devuelve **63,0 días en el periodo histórico
1980-2010** y **109,1 en el escenario futuro SSP2-4.5 (2035-2065)**. La serie
capturada para Santiago tiene 100 años (1970-2069), 20 simulaciones GCM y una
media anual que parte en 52,4 (1970) y termina en 116,2 (2069). No se presenta
eso como pronóstico observado: son salidas de simulación.

La documentación advierte que muchas capas geográficas provienen de IDE y que
ARClim no es necesariamente la fuente primaria oficial de esas geometrías.
La serie diaria usa calendario de 365 días sin años bisiestos; esa decisión
debe preservarse en cualquier derivado.

### F-04, F-05, F-06, F-08, F-09, F-10 y F-12

Se capturaron las páginas y algunos metadatos/servicios vinculados, pero aún no
se incorporaron datasets completos:

- **MINVU IPT (F-04):** página accesible; siguiente piloto es una comuna y una
  modificación concreta, no un barrido de PDFs.
- **MINVU permisos (F-05):** página de repositorio y servicio de campamentos
  capturados; falta seleccionar tablas/periodos y verificar definiciones.
- **IDE Chile (F-06):** portal accesible; falta elegir capas, CRS, versión y
  licencia por capa.
- **SMA/SNIFA (F-08):** página de datos abiertos accesible y enlaces públicos
  detectados; falta registrar formatos y campos antes de descargar.
- **BCN LeyChile (F-09):** portal accesible; se debe seleccionar un conjunto
  normativo y conservar versión/vigencia.
- **Diario Oficial (F-10):** portal accesible; falta definir mecanismo de
  consulta y condiciones de reutilización.
- **CMN (F-12):** geoportal e indicadores accesibles; falta confirmar el
  recurso geográfico concreto y sus términos.

### F-02, F-07, F-11, F-15, F-16, F-17 y F-18

- **INE geodatos abiertos (F-02):** la página primaria respondió y enlaza
  visores ArcGIS, Redatam, banco de datos y otros productos. Todavía no se
  tomó una capa histórica de permisos/recepciones: primero hay que elegir
  producto, periodo, unidad y licencia.
- **SEA/e-SEIA (F-07):** la ruta ArcGIS probada redirigió a login. Se conserva
  la evidencia, pero no se trata como JSON público válido.
- **Transparencia/DOM (F-11):** el portal devolvió HTTP 403 sin credenciales;
  no se intentó evadirlo. Se requiere un piloto focalizado por municipio o
  solicitudes/documentos permitidos, con control de PII.
- **ChileCompra (F-15):** la página capturada describe acceso en tiempo real a
  licitaciones, órdenes, organismos compradores y proveedores, con ticket y
  ClaveÚnica. Sus condiciones exigen atribuir la fuente y deslindan a
  ChileCompra de proyectos o cobros de terceros; no se llamó la API sin ticket
  ni revisión de términos.
- **Ley de Lobby (F-16):** además del portal se capturaron el código de buenas
  prácticas (7 páginas) y el manual de uso 2025 (37 páginas). El manual
  documenta perfiles de sujetos pasivos, asistentes, digitadores, auditores,
  administradores y ciudadanía; el endpoint masivo de datos sigue sin estar
  demostrado. Dos URLs de manuales enlazadas en la página devolvieron 404 y
  quedaron registradas como errores, no como ausencia de la fuente.
- **SINIM (F-17):** la página captura explícitamente que la información puede
  usarse sin fines comerciales y exige citar a SINIM/SUBDERE/Ministerio del
  Interior. Por eso permanece bloqueada para una consultora comercial hasta
  obtener autorización o limitar el uso a análisis interno no comercial.
- **Listado comunitario de APIs (F-18):** se usa como índice de descubrimiento;
  no como fuente sustantiva. Las entradas marcadas deprecated requieren volver
  al organismo propietario.

## Qué tenemos realmente al cierre

Tenemos una capa raw verificable y una primera capa normalizada de alto valor
para Censo, CASEN, GTFS y ARClim. No tenemos todavía “absolutamente todos los
datos” de las 18 fuentes: varias requieren selección metodológica, ticket,
licencia, autenticación o un piloto de descarga. Declarar lo contrario sería
confundir alcance de captura con cobertura de datos.

El siguiente trabajo seguro es aceptar o rechazar fuentes una por una para
cada arco, con una muestra humana y un contrato de variables. La integración
con el corpus de prensa queda prohibida hasta que el inventario marque la
fuente como `accepted` y se documenten unidad espacial, periodo, licencia,
transformaciones y límites.
