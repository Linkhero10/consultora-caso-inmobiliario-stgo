# Instrucción para Sol — corrección completa del enrichment (934 documentos)

## Contexto

En la validación humana de la muestra de 50 documentos, encontraste 12/50 (24%) con `error_grave`,
concentrados en una causa común: el documento no se puede reducir a "un caso, un proyecto" sin más
(documentos panorámicos/comparativos, casos secundarios capturados como focales, actores/comunidades
confundidos con "proyecto", casos fuera del universo de Santiago). Recomendaste explícitamente un gate
`documento → unidad(es) de caso` con 5 categorías, antes de tocar el extractor de actores.

## Qué se te pide ahora

Aplicar ese criterio a **los 934 documentos enriquecidos completos** (no solo la muestra de 50): corregir
el 24% de error conocido y cualquier otro error real que encuentres al revisar el universo completo.

Archivo: `Auditoria/validacion_humana_v3_2/paquete_correccion_completo_934_para_sol.json`

## Qué hacer por cada documento

1. Leer `title` + `url` (y el artículo original si hace falta más contexto) y los campos `original` ya
   extraídos (`nombre_proyecto`, `proyectos_mencionados`, `ubicacion_especifica`, actores, instituciones).
2. Clasificar `unidad_caso_tipo` con una de las 5 categorías:
   `caso_unico / multiples_casos_documentados / documento_comparativo_panoramico /
   contexto_sin_caso_individualizable / caso_focal_fuera_del_universo`.
3. Si algún campo está mal (`nombre_proyecto`, `proyectos_mencionados`, `ubicacion_especifica`), llenar el
   `correccion_*` correspondiente con el valor correcto y explicar por qué en `nota_sol`.
4. **Nunca modificar el bloque `original`** — solo agregar en los campos de corrección. Si todo está bien,
   dejar los 3 campos de corrección en `null` y `tiene_error=false`.
5. Si el volumen es demasiado grande para una sola pasada, se puede hacer en lotes — lo importante es que
   ningún documento quede con `unidad_caso_tipo=null` al terminar.

## Traceabilidad

El propio archivo es el registro de auditoría: cada corrección queda junto al valor original, con la razón
explícita. Si al final agregas un resumen (`resumen_revision_sol` con conteos y criterio, como en las
rondas anteriores), mejor — así queda igual de auditable que las revisiones previas.

## Lo que NO se te pide

No se te pide tocar el extractor ni rediseñar el pipeline — solo corregir los datos ya extraídos con tu
criterio de lectura, exactamente como ya hiciste con la muestra de 50 y con la cola de 253/259 pares.
