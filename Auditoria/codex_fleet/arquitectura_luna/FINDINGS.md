# Auditoría arquitectónica adversarial — Codex/Luna

Fecha: 2026-09-12  
Rol: `sweeper` (solo lectura)  
Alcance: `discovery -> snapshot -> fulltext -> dedupe -> classify -> enrich`  
Restricciones respetadas: no Claude, no APIs, no procesos caros, no edición de producción. Se ejecutaron únicamente lecturas y comprobaciones deterministas aisladas.

## Veredicto breve

El pipeline no puede considerarse arquitectónicamente cerrado. La frontera de snapshot acepta y mezcla registros de generaciones distintas sin validar contrato; después `fulltext_v2` reduce múltiples orígenes del mismo URL a una sola lineage. La idempotencia posterior también está definida por URL, no por contenido/versión. Dedupe tiene una ventana de pérdida permanente si el proceso cae durante el append de eventos. Clasificación no valida localmente el schema que sí valida enriquecimiento. En el estado observado no existen todavía salidas v2 de clasificación, dedupe ni enriquecimiento, por lo que el E2E real termina en fulltext.

## Hallazgos

### F-001 — BLOQUEANTE: el snapshot mezcla generaciones y no hace cumplir el contrato de lineage

- **Archivo/línea:** `Trabajo/scripts/snapshot_discovery.py:76-90`; consumidor `Trabajo/scripts/fulltext_acquisition_v2.py:98-108`; contrato `Trabajo/config/pipeline_contract_v2.yaml:34-42`.
- **Evidencia real:** `Fuentes/discovery_snapshots/discovery_snapshot_20260912_153729_835.jsonl` contiene 2.687 filas: 2.592 tienen `periodo`/`nivel`, pero 95 no tienen ninguno. La misma instantánea se consume como v2. La lineage generada para `https://www.elperiodista.cl/2020/09/vecinos-de-las-condes-piden-desechar-proyecto-inmobiliario-de-lavin/` conserva `snapshot_run_id` y hash, pero deja `periodo=""` y `nivel=""`.
- **Causa raíz:** el snapshot solo prueba que cada línea es JSON parseable; no exige campos requeridos, `contract_version`, hash del manifest fuente ni compatibilidad de generación. El manifest activo es reutilizado por corridas históricas y nuevas.
- **Impacto:** se pierden dimensión temporal y nivel comuna/sector; un análisis posterior puede tratar evidencia histórica como v2 completa. La afirmación contractual de lineage “completa” no es reproducible desde los artefactos reales.
- **Prueba de regresión:** checker determinista que recorra cada snapshot y falle si falta `{record_hash,query,comuna,termino,periodo,nivel}` o `contract_version`; sobre el snapshot observado debe fallar exactamente con 95 filas. El snapshot debe rechazar la mezcla o separar automáticamente por contrato.

### F-002 — ALTA: `load_unique_discoveries()` descarta orígenes de discovery antes de dedupe

- **Archivo/línea:** `Trabajo/scripts/fulltext_acquisition_v2.py:76-91` y `233-236`.
- **Evidencia real:** el snapshot tiene 355 URLs con más de una combinación distinta de query/comuna/periodo/nivel. La URL `https://www.infraestructurapublica.cl/fin-del-conflicto-las-condes-recibira-dinero-para-viviendas-sociales-y-vitacura-tendra-parque/` aparece cuatro veces: Las Condes (registro legacy sin periodo), Vitacura 2018-2020 y Santiago 2018-2020, además de una repetición legacy. El `fulltext_manifest_v2.jsonl` conserva una sola fila, con lineage Las Condes legacy; el texto sí fue extraído (`trafilatura`, 3.343 caracteres).
- **Causa raíz:** `seen_urls` convierte URL en identidad global antes de conservar `origins[]`; el primer registro gana y los restantes jamás llegan a dedupe. Dedupe solo puede comparar archivos ya materializados y no puede reconstruir queries/comunas descartadas.
- **Impacto:** cobertura y atribución quedan subcontadas; la misma noticia no puede relacionarse con todas las comunas/ventanas que la descubrieron y el clasificador recibe una hipótesis de origen arbitraria.
- **Prueba de regresión:** fixture con dos discovery records del mismo URL y lineage distinto; exigir una extracción física y una lista persistida de todos los orígenes, o un evento explícito de `origin_added` antes de descartar. El comportamiento actual pierde al menos una lineage.

### F-003 — ALTA: idempotencia incremental por URL oculta cambios de contenido y nuevas versiones

- **Archivo/línea:** `fulltext_acquisition_v2.py:94-95,233-235`; `classify_luna.py:110-111,317-319`; `enrich_case.py:117-119,279-281`.
- **Evidencia real:** fulltext materializa 1.941 URLs únicas desde el snapshot, aunque el snapshot tiene 1.964 URLs únicas y múltiples lineages por URL. Todas las etapas de reanudación mantienen conjuntos `done_*_urls`; ninguna usa hash de texto, hash de clasificación, `snapshot_sha256` o versión de contrato como clave de procesamiento.
- **Causa raíz:** URL se usa simultáneamente como identidad de fuente, unidad de reanudación y clave de clasificación/enriquecimiento. No hay contrato para “misma URL, contenido cambiado” ni para “misma URL, nuevo origen/ventana”.
- **Impacto:** un nuevo snapshot no actualiza texto, clasificación o enriquecimiento si la URL ya apareció; resultados viejos pueden sobrevivir silenciosamente a cambios de contenido y lineage.
- **Prueba de regresión:** ejecutar dos snapshots sintéticos con la misma URL y distinto `snapshot_sha256`/hash de texto; exigir dos versiones explícitas o una decisión documentada de no re-procesar. La lógica actual la excluye en `already_processed_urls()` y en las tres etapas downstream.

### F-004 — ALTA: append de eventos de dedupe no es transaccional y puede perder orígenes para siempre

- **Archivo/línea:** `Trabajo/scripts/dedupe_fulltext.py:77-80,92-98,241-321`.
- **Evidencia estática:** una corrida genera en memoria un `canonical_elected` y uno o más `origin_added`, pero `append_events()` escribe línea por línea directamente al JSONL, sin `fsync`, archivo temporal, transaction id ni marcador de batch. `already_eventful_urls()` considera procesada cualquier URL que tenga un evento. `read_jsonl_tolerant()` descarta una última línea truncada, pero no reconstituye el evento esperado.
- **Causa raíz:** persistencia de eventos y checkpoint de unidad lógica no están coordinados. Si el proceso cae después del canonico y antes de un origin, el próximo ciclo excluye ese URL por el evento parcial y no lo reintenta.
- **Impacto:** pérdida permanente de `origins[]`, manifest materializado incompleto y lineage irrecuperable aunque el texto siga en disco.
- **Prueba de regresión:** fixture con un grupo de dos URLs idéntico; simular fallo después de escribir el primer evento y volver a ejecutar. Debe recuperar ambos orígenes o marcar el batch incompleto. El diseño actual no lo hace.

### F-005 — MEDIA/ALTA: clasificación acepta respuestas JSON válidas pero incompatibles con `classification_schema_v2`

- **Archivo/línea:** `Trabajo/scripts/classify_luna.py:166-203,206-257` (contraste: `enrich_case.py:215-225` sí usa `jsonschema.validate`).
- **Evidencia estática:** `classify_document()` hace `json.loads(content)` y entrega el resultado a `postprocess_result()`; no hay validación local contra `SCHEMA_PATH`. `postprocess_result()` solo corrige algunos campos (`decision`, comuna/tipo y cita), y puede escribir un registro al que le faltan `sentiment`, `confidence`, `via_legal` u otros campos requeridos.
- **Causa raíz:** se confía en `response_format` del proveedor para una etapa, mientras la etapa siguiente aplica validación formal; productores equivalentes no comparten el mismo gate.
- **Impacto:** `classifications.jsonl` puede contener registros estructuralmente inválidos que parecen resultados finales; enriquecimiento y métricas posteriores pueden interpretar ausencias como valores válidos o fallar tarde.
- **Prueba de regresión:** inyectar una respuesta `{"decision":"include"}` y exigir rechazo antes de escribir. El código actual la degrada a `uncertain`, pero todavía puede persistirla sin las propiedades requeridas del schema.

### F-006 — MEDIA: `run_state` no tiene gate de liveness/versionado y puede bloquear o dejar pasar etapas incorrectamente

- **Archivo/línea:** `Trabajo/scripts/pipeline_lock.py:173-194,213-226`.
- **Evidencia real:** `_FARO/memory-bank/run_state.json` contiene entradas legacy (`snapshot_discovery` con `actualizado_at`, sin `run_id/iniciado_at/terminado_at`) junto a entradas nuevas; `upstream_stage_is_running()` solo evalúa `estado == "running"`. El estado persistido de `fulltext_acquisition_v2` es `running` y existe un lock, pero no existe validación de PID vivo, edad del lock, versión de contrato o coherencia entre lock y estado.
- **Causa raíz:** el archivo de estado se trata como semáforo sin schema migratorio ni prueba de vida. La detección de lock stale solo registra advertencia y no alimenta el gate productor/consumidor.
- **Impacto:** un proceso muerto puede dejar consumidores bloqueados indefinidamente; un `run_state` truncado/legacy puede hacer que un consumidor avance sin evidencia suficiente de que el productor terminó.
- **Prueba de regresión:** dejar `estado=running` con PID inexistente y lock ausente; exigir `stale/failed` o atención manual explícita. El predicado actual devuelve `True` sin distinguir proceso vivo, stale o generación incompatible.

## Tres trazas end-to-end observadas

1. **`jurischile.com`** — discovery `record_hash=e4530870...`, query de comuna Santiago, `periodo=2014_2017`, `nivel=comuna`; snapshot `20260912_153729_835`, fulltext `trafilatura`, 13.036 caracteres, lineage preservada. No existe clasificación v2 posterior.
2. **`elperiodista.cl`** — discovery legacy `record_hash=98e0c781...`, query Las Condes; snapshot lo acepta sin `periodo/nivel`; fulltext `trafilatura`, 5.961 caracteres, pero lineage ya queda con ambos campos vacíos. Es evidencia concreta de F-001.
3. **`infraestructurapublica.cl`** — cuatro descubrimientos con comunas/periodos distintos; fulltext `trafilatura`, 3.343 caracteres; manifest conserva solo la primera lineage legacy Las Condes. Es evidencia concreta de F-002. Dedupe, clasificación y enriquecimiento aún no tienen artefactos v2 reales para continuar la traza.

## Comprobaciones deterministas ejecutadas

- Conteo de campos del snapshot: 2.687 filas; 95 sin `periodo`; 95 sin `nivel`.
- Conteo de orígenes: 355 URLs con más de una combinación de lineage.
- Join snapshot/fulltext: 1.941 URLs en manifest v2; se verificaron tres contenidos y sus lineages, sin llamadas de red.
- Inspección estática de contratos, scripts y `run_state.json`; no se ejecutaron APIs, LLM, dedupe de producción ni clasificación.

