# Auditoría del dashboard piloto y warehouse — 2026-09-13

## Resultado ejecutivo

**Estado: listo dentro del alcance revisado, con cautelas de interpretación.**

Se auditó `Productos/dashboard_contexto/index.html`, su generador
`Trabajo/scripts/build_context_dashboard_v1.py`, la geometría comunal del Censo
2024 y `Fuentes/analisis/case_warehouse_v1.sqlite`. Se corrigieron tres defectos
deterministas y de alta confianza en el generador y se regeneró únicamente el
HTML del dashboard:

1. El mapa comparaba un CUT convertido a texto con CUT numéricos y dejaba las
   32 comunas con población cero. Ahora normaliza ambos lados a código CUT
   entero antes del join.
2. El payload omitía `feed_feed_version` aunque la vista GTFS intentaba
   mostrarlo. Ahora incluye las dos versiones capturadas.
3. La tabla de prensa declaraba todos los registros filtrados como visibles,
   pero renderizaba sólo los primeros 500. Ahora renderiza el conjunto completo.

No se ejecutó scraping, ninguna API, ni el pipeline de prensa. No se modificó
SQLite; el warehouse se abrió en modo sólo lectura durante las comprobaciones.

## Alcance y evidencia inspeccionada

### Artefactos

- Dashboard: `Productos/dashboard_contexto/index.html`.
- Generador: `Trabajo/scripts/build_context_dashboard_v1.py`.
- Warehouse: `Fuentes/analisis/case_warehouse_v1.sqlite`.
- Geometría: `Fuentes/fuentes_externas/raw/F-01/censo2024_provincia_santiago_geometry.geojson`.
- Entradas normalizadas: `Fuentes/fuentes_externas/normalized/censo_2024_comunal_provincia_santiago.csv`, `arclim_hot_days_comunas.csv` y `gtfs_feed_catalog.csv`.
- Clasificación que consume el dashboard: `Auditoria/clasificacion_luna_v2/classifications.jsonl`.

### Grano y conteos actuales

| Componente | Grano observado | Conteo | Resultado |
|---|---|---:|---|
| Censo/payload | una fila por comuna/CUT | 32 | Completo para la Provincia de Santiago |
| Geometría | una feature por comuna/CUT | 32 | 32 CUT únicos, 32 comunas únicas |
| ARClim | fila por ComCod/indicador | 345 | Join contextual completo para las 32 comunas |
| Clasificación | una fila por registro de prensa | 783 | Resumen reconciliado |
| `actor_edge` | una arista derivada de clasificación | 164 | Existe en warehouse; no se muestra |
| `literature_source` / `literature_edge` | fuente/arista bibliográfica | 6 / 15 | Existe; no se muestra |
| GTFS | una fila por snapshot | 2 | Versiones incluidas tras la corrección |

La metadata del warehouse mantiene estado `pilot_provisional` y método
descriptivo, sin causalidad ni join por nombre cuando existe CUT/ComCod.

## Comprobaciones de métricas y joins

### Métricas

Se recalcularon independientemente desde el payload: decisiones, conflictos
incluidos por `tipo_conflicto` e incluidos por comuna. Los tres resultados
coinciden exactamente con `D.summary`. El payload conserva 783 clasificaciones y
32 filas territoriales. La comparación contra `v_context` del warehouse también
coincide en CUT, población, inmigrantes, viviendas hacinadas, viviendas
irrecuperables y días de calor presente/futuro.

Estas métricas son descriptivas. Los campos de Censo son conteos brutos y los
días ARClim son indicadores modelados/escenarios; no deben interpretarse como
tasas de riesgo, efecto causal, demanda de transporte o desempeño ESG.

### Joins

- **Censo ↔ ARClim:** cobertura SQL 32/32, sin huérfanos, usando CUT/ComCod
  canónico. La vista `v_context` devuelve 32 filas.
- **Geometría ↔ Censo:** antes de la corrección, el generador hacía
  `String(f.properties.CUT)` y luego igualdad estricta con `x.CUT` numérico.
  El resultado era cero matches: la geometría se dibujaba, pero todos los
  tooltips mostraban población cero. Tras la corrección: 32/32 matches, 0
  faltantes, 32 poblaciones no cero y 32 valores distintos.
- **Clasificación ↔ resumen:** los contadores del dashboard coinciden con el
  recálculo directo de las 783 filas.
- **GTFS:** el origen contiene `V167.20260829` y `V150.20251213`. Ambos valores
  llegan ahora al payload y a la celda de versión.

No se observó expansión many-to-many en estos joins; la clave cartográfica
esperada es CUT/ComCod, no el nombre de la comuna.

## Límites cartográficos y presentación

La geometría declara EPSG:4326, contiene 32 features de la Provincia de
Santiago y propiedades CUT/COMUNA. El dashboard transforma coordenadas a un SVG
normalizado al bounding box. Por tanto:

- es un mapa administrativo de contexto, no una capa de proyectos, permisos,
  eventos o puntos de conflicto;
- el color representa población censada absoluta, no densidad, tasa ni
  exposición por superficie;
- no hay escala, norte, leyenda cuantitativa continua ni CRS visible en la
  interfaz;
- los límites son los de la captura Censo 2024 y no prueban localización ni
  área de influencia de un proyecto;
- mezclar población, calor, transporte y prensa en una lectura causal sería una
  inferencia no sustentada por este artefacto.

La inspección visual directa del archivo `file://` fue bloqueada por la política
de seguridad del navegador. Se hizo, en sustitución, validación estructural del
HTML/JS, parseo del payload y comprobación de resultados renderizables; la
revisión visual de layout, hover y desplazamiento queda pendiente de una apertura
local autorizada.

## Utilidad para los tres arcos

### Felipe — scraping, clasificación, tópicos, mapa y dashboard

**Utilidad actual: contextual y de demostración.** Permite mostrar 32 comunas,
Censo, ARClim, dos snapshots GTFS y el resumen de clasificación provisional.
Es apto para explicar trazabilidad básica y alcance del piloto. No incluye
resultados de tópicos/sentimiento, geocodificación de proyectos, puntos de
eventos ni mapa de conflictos; no sustituye el pipeline ni prueba cobertura
territorial del corpus.

### Darío — SNA, ERGM, SAOM y red de actores

**Utilidad actual: baja y sólo contextual.** `actor_edge` contiene 164 aristas y
el warehouse contiene 15 aristas bibliográficas, pero ninguna se embebe ni se
visualiza. No hay métricas de red, definición temporal, panel longitudinal ni
insumos suficientes para afirmar ERGM/SAOM. Tipos genéricos como `otro` requieren
validación antes de usarse como atributos de actor.

### Nicolás — institucional, regulatorio, entrevistas y decisión

**Utilidad actual: baja.** La tabla de prensa ofrece decisión de inclusión,
comuna, tipo de conflicto, confianza y `evidence_verified`, pero no presenta
actos administrativos, expediente, autoridad decisora, estado regulatorio,
entrevistas ni secuencia documento → evidencia → evento → caso/conflicto. No se
debe leer `include` como decisión institucional o jurídica.

### Christian — ESG, evidencia y anti-greenwashing

**Utilidad actual: baja.** `evidence_verified` indica verificación de la cita
literal según el esquema vigente; no equivale a validar la verdad completa,
indicador ESG, adicionalidad, impacto o cumplimiento. No hay registro de claim,
definición, denominador, período, fuente primaria y contraevidencia.

### Cierre comercial

Sirve como demo prudente de contexto territorial y disciplina de fuentes: muestra
qué existe, qué no existe y qué permanece provisional. No es todavía un producto
integrado de los tres arcos ni un instrumento de decisión comercial sin una ficha
de caso reconstruible y revisión humana.

## Priorización

### P0 — corregido en esta auditoría

- Normalización del CUT en el join geometría↔Censo.
- Inclusión de `feed_feed_version` en el payload GTFS.
- Eliminación del recorte silencioso de 500 filas en la tabla de prensa.

### P1 — siguiente trabajo acotado

- Añadir pruebas de contrato para CUT/ComCod canónico, cobertura de geometría,
  reconciliación de `D.summary`, campos GTFS y ausencia de truncamiento no
  declarado.
- Etiquetar unidad, período y denominador de cada indicador; distinguir conteo
  bruto de tasa o proporción.
- Diseñar, sólo con aprobación de alcance, una vista de eventos/casos y otra de
  claims/evidencia que mantengan lineage hasta el documento fuente.

### P2 — diferido

- Puntos de proyecto/conflicto, geocodificación y overlays temporales.
- Vista de actores y exportación de red para SNA; cualquier ERGM/SAOM requiere
  panel temporal, reglas de observación y validación de sesgo.
- Módulo institucional/regulatorio con expediente y actor decisor.
- Registro ESG/anti-greenwashing con claim, evidencia primaria, período,
  denominador, contraevidencia y estado de verificación.
- Predicción, causalidad, simulación, fuentes sociales/satelitales y
  automatización SaaS: fuera del alcance actual.

## Criterios de aceptación aplicados

- 32/32 features geográficas tienen CUT resoluble a una fila Censo y población
  no cero en el payload corregido.
- El payload conserva dos versiones GTFS no vacías.
- El número mostrado por la tabla de prensa coincide con el filtro y no se
  descartan filas por un límite implícito; el snapshot tiene 783 filas.
- Resumen de decisiones, conflictos y comunas coincide con recálculo directo.
- Contexto HTML y `v_context` coinciden en claves y valores revisados.
- El JavaScript embebido pasa parseo mediante `new Function`.
- No se ejecuta scraping/API, no se modifica SQLite y no se modifica el pipeline
  de prensa.

Queda fuera de aceptación: validez sustantiva de cada noticia, calidad jurídica
de una clasificación, inferencia causal, validez de actores para modelos de red,
cumplimiento ESG y revisión visual manual en navegador.

## Cambios y hashes de cierre

Cambios realizados por un único escritor:

- `Trabajo/scripts/build_context_dashboard_v1.py`: correcciones de payload,
  render de prensa y normalización del join cartográfico.
- `Productos/dashboard_contexto/index.html`: regenerado desde el generador.
- Este informe: única salida documental de la auditoría.

SHA-256 posteriores a la regeneración:

```text
build_context_dashboard_v1.py  36dbc43680bf117ca91082f72067fd85bc3cc2012e44de5dbb31a6c4fcf5adbe
Productos/dashboard_contexto/index.html  a5e089d44ad1e2168aef8153334e3ee0cf7f74ad4c79e521aab54bf7b1349a7c
Fuentes/analisis/case_warehouse_v1.sqlite  ef0be9fbce948db365b760312c73a24b74217eaa5189fe45fbe004e0b36a8fc9
```

El hash del warehouse se registra como evidencia de lectura; el warehouse no
fue escrito durante esta auditoría.
