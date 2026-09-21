# Auditoría adversarial de datos y lineage — Codex/Luna

**Alcance:** solo lectura sobre `D:\Felipe\Consultora\caso_inmobiliario_stgo`. No se invocaron APIs/Claude y no se modificó producción. La evidencia dinámica se tomó en una sola observación del 2026-09-12; `fulltext_v2` seguía creciendo, por lo que sus conteos son una fotografía y deben repetirse al cerrar la corrida.

## Veredicto corto

El snapshot más reciente es reproducible por hash y la mayoría de los registros `fulltext_v2` sí conserva `query` y `discovery_record_hash`. Sin embargo, la corrida activa no está versionada de forma reproducible, el manifest ya contiene fallos transitorios que el contrato dice que no deben marcarse como procesados, y `fulltext_v2` mezcla 67 resultados heredados de la fase v1 sin `periodo`/`nivel`. Dedupe, clasificación v2 y enrichment v2 todavía no tienen outputs de producción.

## Hallazgos

### DL-01 — P1 alto: corrida activa no atribuible al contrato/código vigente

- **Severidad:** P1 / alto (reproducibilidad e integridad de estado).
- **Path/línea:** `_FARO/memory-bank/run_state.json:7-11`; `Trabajo/scripts/fulltext_acquisition_v2.py:217-219`; `Trabajo/scripts/pipeline_lock.py:118-145,198-261`.
- **Reproducción determinista:** `run_state.json` muestra `fulltext_acquisition_v2.estado=running`, `pid=42408`, pero la entrada carece de `run_id`, `iniciado_at` y `detail`, campos que el contrato de `pipeline_lock.py` exige. El PID 42408 estaba vivo y el lock tenía inicio `2026-09-12T15:38:13Z`. El proceso/lock empezó a las 12:38 local, antes de las últimas escrituras observadas de `fulltext_acquisition_v2.py` (14:06), `pipeline_contract_v2.yaml` (14:08) y `pipeline_lock.py` (14:42).
- **Causa raíz:** proceso de producción de larga duración cargado antes de los últimos parches; no existe un fingerprint de código/contrato en `run_state` que permita distinguir la implementación que produjo cada lote.
- **Impacto:** el manifest actual no puede atribuirse de forma reproducible al código v2 vigente; al terminar, el proceso puede escribir estado con el contrato antiguo y contaminar la lectura de downstream.
- **Fix mínimo:** dejar que termine o aislar la corrida, marcarla como pre-fix, y relanzar desde el código vigente con `run_id`, `iniciado_at`, `terminado_at`, `detail`, hash de scripts/config y snapshot SHA-256 registrados antes de aceptar el output.
- **Test de cierre:** fixture local de una corrida completa debe dejar `running` con esos campos, `done` con `terminado_at`, y un `code_fingerprint` que coincida con los scripts usados; un proceso iniciado antes de cambiar el fingerprint debe quedar `superseded`, no mezclarse.

### DL-02 — P1 alto: fallos transitorios ya quedaron marcados como procesados

- **Severidad:** P1 / alto (pérdida silenciosa de cobertura incremental).
- **Path/línea:** `Fuentes/fulltext_v2/fulltext_manifest_v2.jsonl` (observación: 1.877 filas); `Trabajo/scripts/fulltext_acquisition_v2.py:117-132,278-295`.
- **Reproducción determinista:** el manifest observado contiene `http_error_503` (3), `http_error_429` (2) y `error` (26). La propia función `is_transient_outcome` clasifica 429/5xx como transitorios y el código vigente dice explícitamente que no deben escribirse al manifest; aun así están presentes. En total hay 1.020 filas con `char_count=0`.
- **Causa raíz:** la corrida PID 42408 comenzó antes del parche que separa outcomes transitorios de terminales; el artefacto es pre-fix aunque el contrato v2 lo presente como actual.
- **Impacto:** `already_processed_urls()` toma esas URLs desde el manifest y puede omitirlas en el ciclo siguiente, exactamente la pérdida permanente que el parche pretendía evitar. Las salidas de error vacías también pueden entrar a revisiones de estado como si fueran resultados terminales.
- **Fix mínimo:** separar el intento bruto de la vista de URLs procesadas; reconstruir la vista productiva excluyendo 429/5xx/errores de conexión, y volver a intentar esos URLs bajo el código vigente. No borrar evidencia: conservarla como intento pre-fix con su run_id.
- **Test de cierre:** simular 429/503 persistentes y comprobar que se guarda un intento diagnóstico, no una fila en el manifest productivo, y que la URL reaparece en `pending` en la siguiente corrida.

### DL-03 — P1 alto: mezcla v1/v2 y lineage temporal incompleto

- **Severidad:** P1 / alto (contrato temporal y trazabilidad semántica).
- **Path/línea:** `Fuentes/discovery_snapshots/discovery_snapshot_20260912_153729_835.jsonl`; `Fuentes/fulltext_v2/fulltext_manifest_v2.jsonl`; `Trabajo/scripts/fulltext_acquisition_v2.py:98-107`; `Trabajo/config/pipeline_contract_v2.yaml:36-49`.
- **Reproducción determinista:** el snapshot tiene 2.687 filas; 95 (8 queries, 4 comunas originales) carecen de `periodo` y `nivel`. En `fulltext_v2`, 67 filas heredadas tienen `lineage.periodo=""` y `lineage.nivel=""`. Esas filas usan el esquema/hash de la fase antigua (95 registros se validan con la forma antigua de `record_hash`; las 2.592 restantes con la forma v2 que incluye `periodo`).
- **Causa raíz:** el manifest activo histórico fue reutilizado para construir el snapshot ampliado; no hubo una frontera de migración que rechazara registros sin `periodo`/`nivel` ni un campo de versión/hash-algorithm por registro.
- **Impacto:** análisis por ventana temporal, dedupe y agrupación por nivel no pueden distinguir esos 67 documentos; `snapshot_run_id` y `snapshot_sha256` son correctos pero no compensan lineage semántico faltante.
- **Fix mínimo:** tratar los 67 como `legacy_v1` explícitos y fuera del corpus v2, o migrarlos con metadatos verificables; incorporar `record_schema_version` y `record_hash_algorithm` al contrato y hacer fallar el snapshot si faltan campos v2.
- **Test de cierre:** validar que todo registro v2 tenga `periodo`, `nivel`, versión de hash y que el número de legacy sea cero (o esté aislado en una partición declarada).

### DL-04 — P1 alto: dedupe y clasificación/enrichment v2 no representan producción

- **Severidad:** P1 / alto (linaje downstream inexistente).
- **Path/línea:** `Trabajo/scripts/dedupe_fulltext.py:56-59,182-205`; `Trabajo/scripts/classify_luna.py:53-61,81-107`; `Trabajo/scripts/enrich_case.py:48-60`; `_FARO/memory-bank/run_state.json:1-23`.
- **Reproducción determinista:** no existen `Fuentes/fulltext_v2/dedupe_origin_events.jsonl`, `Fuentes/fulltext_v2/dedupe_manifest_v2.jsonl`, `Auditoria/clasificacion_luna_v2/` ni `Auditoria/enriquecimiento_v2/`. `run_state.json` solo registra `snapshot_discovery`, `fulltext_acquisition_v2` y el benchmark `compare_effort`; no registra una corrida productiva de dedupe/classify/enrich.
- **Causa raíz:** las etapas downstream fueron implementadas/probadas en scratchpad pero están bloqueadas por el upstream aún activo; el benchmark existente usa explícitamente fixture legacy v1.
- **Impacto:** no es válido afirmar que el corpus actual ya tiene dedupe canónico/origins ni clasificaciones/enrichment v2 trazables. Cualquier dashboard/resultado derivado de esos outputs sería de test o de la fase histórica.
- **Fix mínimo:** ejecutar cada etapa sobre un snapshot cerrado y un manifest final, registrando `run_id`, `input_snapshot_sha256`, `input_manifest_sha256`, schema/prompt y conteos; publicar outputs solo cuando la etapa tenga estado `done` verificable.
- **Test de cierre:** exigir la cadena `snapshot -> fulltext_final -> dedupe_events/materialized -> classification_v2 -> enrichment_v2`, con hashes de entrada en cada artefacto y URLs/canonicals reconciliables.

### DL-05 — P2 medio: benchmark high/xhigh es reproducible internamente, pero no es evidencia de producción v2

- **Severidad:** P2 / medio (riesgo de interpretación).
- **Path/línea:** `Trabajo/scripts/compare_effort.py:4-5,40-44,76-109`; `Auditoria/effort_comparison/sample_effort_test.jsonl`; `Auditoria/effort_comparison/veredicto_20260912_171211_744_12docs.json`.
- **Reproducción determinista:** los 12 hashes `hash_texto` y `hash_clasificacion` del fixture verifican PASS; los 12 registros declaran `schema_version=v1`, `prompt_version=v1` y apuntan a `Fuentes/fulltext_v1/content`. El veredicto dice `MANTENER_XHIGH` y `confirmado_manualmente=false`.
- **Causa raíz:** el comparador está diseñado para un fixture legacy de 12 `include`, no para el corpus ampliado ni para `classification_schema_v2`/`classifier_system_v2`.
- **Impacto:** el veredicto sirve para esa muestra v1 y no autoriza inferir el esfuerzo por defecto de enrichment v2 ni la calidad del corpus nuevo.
- **Fix mínimo:** conservar el benchmark como histórico y ejecutar una muestra congelada v2 con lineage, schema/prompt versionados y revisión manual contra texto fuente antes de promover cualquier decisión.
- **Test de cierre:** fixture v2 debe rechazar entradas v1, exigir hash de snapshot/manifest y publicar explícitamente `confirmado_manualmente`/cobertura de omisiones.

### DL-06 — P2 medio: `evidence_verified=true` es vacuamente verdadero en no-include

- **Severidad:** P2 / medio (semántica de contrato downstream; el gate de `include` sí está separado y funciona).
- **Path/línea:** `Trabajo/scripts/classify_luna.py:118-125,224-255`.
- **Reproducción determinista:** `quote_is_grounded("", "texto cualquiera")` devuelve `True` por diseño. Al pasar un resultado `decision=exclude` con `evidence_quote=""` por `postprocess_result`, el registro emitido queda con `evidence_verified=true`, `evidence_quote=""` y `decision=exclude`.
- **Causa raíz:** un booleano que debiera significar “la cita existente fue verificada” se usa para representar también la propiedad vacía “no hay cita que verificar”. El control de `include` evita el caso bloqueante porque exige 15 caracteres antes de publicar `include`, pero no corrige la semántica del campo en las demás decisiones.
- **Impacto:** consumidores que filtren `evidence_verified=true` pueden interpretar falsamente que un `exclude`, `uncertain` o `insufficient_content` tiene evidencia textual verificada; esto puede contaminar métricas de calidad, auditoría o dashboards aunque la clasificación no incluya el documento.
- **Fix mínimo:** separar `evidence_present`/`evidence_verified` o definir `evidence_verified = decision == "include" and len(evidence_quote.strip()) >= MIN_EVIDENCE_QUOTE_CHARS and quote_is_grounded(...)`; para no-include emitir `false` (o `null` si el contrato distingue “no aplica”).
- **Test de cierre:** tabla determinista para include válido, include vacío/corto, include cita no grounded y cada decisión no-include; solo el primer caso puede tener `evidence_verified=true`.

## Controles positivos verificados

- Ambos snapshots pasan SHA-256 y el número de líneas coincide con su `.meta.json` (`2591` y `2687`).
- Las filas observadas de `fulltext_v2` tienen `snapshot_run_id=20260912_153729_835`, `snapshot_sha256` correcto, `discovery_record_hash` y `query`; la comparación contenido/manifest no mostró discrepancias de URL, lineage ni `char_count`.
- El fixture del benchmark no tiene deriva de hashes y está correctamente rotulado v1; eso evita confundir reproducibilidad interna con validez de producción.
- La prueba estática de `postprocess_result` confirma que `exclude + evidence_quote=""` publica `evidence_verified=true`; el gate de include no queda comprometido, pero el campo sí es semánticamente engañoso para downstream.

## Condición observable de término

No cerrar el corpus como producción hasta que el proceso activo tenga un estado versionado verificable y se haya reconstruido la cadena con snapshot cerrado, fallos transitorios fuera de la vista procesada, legacy v1 aislado, dedupe materializado y outputs v2 con hashes de entrada.
