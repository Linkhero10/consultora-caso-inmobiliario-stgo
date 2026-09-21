# QA Codex — checkpoint 01

**Fecha:** 2026-09-12 12:40 (America/Santiago)  
**Rol:** sweeper; auditoría de solo lectura  
**Regla de aislamiento:** no se ejecutaron llamadas de API ni scripts de producción; no se tocaron manifests, locks ni procesos de Claude.

## Evidencia observada

- FARO_GLOBAL, AGENTS.md, `current-handoff.md`, índice de bitácora y la bitácora del proyecto fueron leídos antes de revisar el pipeline.
- Snapshot activo de este ciclo: `discovery_snapshot_20260912_153729_835.jsonl`; meta reporta **2.687 líneas válidas, 0 descartadas**, SHA-256 `3cf4cd4c...`.
- El manifest de discovery continuaba creciendo durante la inspección; por diseño, el pipeline v2 debe seguir usando el snapshot y no el manifest activo.
- `fulltext_acquisition_v2` llegó a estado `running` bajo lock y luego produjo salida parcial. No se interpretan esos conteos como resultado final.
- Los ocho scripts Python existentes pasaron parseo AST sin escribir artefactos.
- Se verificó propagación del objeto `lineage` en los JSON de `fulltext_v2`, incluyendo query, hash del registro y hash/run del snapshot.

## Hallazgos que requieren cierre antes de declarar el plan completo

1. **Estado contaminado por pruebas (P1).** `_FARO/memory-bank/run_state.json` conserva `test_etapa=done`, `test_etapa2=failed` y `test_etapa3=done`. El fallo `test_etapa2` no tiene explicación asociada en el estado. Antes del cierre hay que retirar o aislar esos registros y dejar evidencia de la prueba fallida/corregida.

2. **Contrato de `run_state` incompleto (P1).** `pipeline_lock.py` escribe solamente `estado`, `actualizado_at` y `pid`. El plan exige registrar `run_id`, `iniciado_at` y `terminado_at` por etapa. La ausencia impide reconstruir un checkpoint de ejecución de forma confiable.

3. **Fingerprint corto no persistente entre ciclos (P1 de calidad).** `dedupe_fulltext.py` usa `fingerprint_seen` local a la corrida. Un artículo nuevo que comparte los primeros 300 caracteres con uno visto en un ciclo anterior no genera `candidato_revision`, porque no existe un índice histórico de fingerprints en los eventos/manifest.

4. **`--dry-run` deja efectos laterales (P2).** `fulltext_acquisition_v2.py` crea `fulltext_v2/content` y abre el manifest aunque no vaya a escribir registros. El modo de prueba debería ser sin mutaciones, o declarar explícitamente esta excepción.

5. **Doble etiqueta posible en dedupe (P2).** En un lote, dos textos idénticos pueden generar simultáneamente `origin_added`/`canonical_elected` y `fingerprint_candidate` para la misma URL. El manifest materializado puede mostrar el mismo duplicado como `duplicado_exacto` y `candidato_revision`; conviene suprimir el candidato cuando ya existe coincidencia exacta.

6. **Documentación de entrada desactualizada (P1 operativo).** El `START_HERE.md` local todavía dice que la Fase 1 está pendiente por credenciales, mientras `active-context.md`, el snapshot y la corrida actual muestran credenciales confirmadas y pipeline en ejecución. No debe usarse ese `START_HERE` para el siguiente handoff sin actualizarlo después de que termine la corrida; hasta entonces, el estado activo y la bitácora son las fuentes actuales.

7. **Benchmark aún no implementa todo su criterio de decisión (P1 pendiente).** `compare_effort.py` ejecuta y compara high/xhigh, pero no valida localmente ambos resultados contra el schema, no verifica durante la corrida `hash_clasificacion` del fixture y no emite un veredicto automático high/xhigh conforme a los umbrales del plan. El archivo de comparación por sí solo no debe presentarse como decisión final.

8. **Primer caso ya muestra desacuerdo sustantivo.** El log del benchmark reporta `institucion_decisora igual=False` para el caso de Las Condes, aunque coinciden revisión manual, tipo de evidencia y número de actores. Por tanto, no corresponde cambiar el default a `high` por ahorro sin resolver cuál institución es correcta contra el texto fuente y dejar esa adjudicación registrada.

9. **El benchmark no reproduce todavía el payload de producción.** `build_case()` deja `comuna=None` y `tipo_conflicto=None`, aunque el fixture sí conserva `hash_clasificacion`. Las llamadas high/xhigh son comparables entre sí, pero no equivalen exactamente al enriquecimiento real sobre un `include` clasificado; conviene cargar y verificar el registro v1 correspondiente antes de usar el resultado para cambiar el default.

## Estado de esta auditoría

El diseño corregido va en la dirección correcta y ya hay evidencia de snapshot, lineage y locks en uso. Este archivo es un checkpoint, no una aprobación final: faltan observar la corrida completa y verificar los artefactos de comparación de esfuerzo, deduplicación, muestras congeladas, contrato v2 y trazabilidad final.

## Actualización checkpoint 02

- La adquisición fulltext v2 seguía en ejecución, alrededor de **275/1.962** documentos observados en el log; no se evalúan todavía sus conteos como finales.
- El benchmark high/xhigh llevaba **9/12** casos. En esos nueve: tres desacuerdos en `institucion_decisora` y una diferencia de actores de **8 vs 5** (fuera de la tolerancia ±1). Esto basta para mantener `xhigh` provisionalmente, aunque high sea más barato.
- Aún no existen salidas finales de `dedupe`, `clasificacion_luna_v2`, `enriquecimiento_v2`, muestras control ni `pipeline_contract_v2`.
- Claude limpió las entradas `test_etapa*` de `run_state.json`; ese problema puntual queda resuelto. Persisten los locks de las dos etapas largas y la ausencia de actualización intermedia no se interpreta como finalización.
- `active-context.md` sigue describiendo el pipeline viejo de 16 queries/67 documentos y dice que la Fase 1 está completa, aunque la corrida actual corresponde al discovery ampliado y a `fulltext_v2`. Debe actualizarse al cierre con conteos reales y el snapshot/run_id vigente.

## Actualización checkpoint 03 — correcciones verificadas y pendientes nuevos

- Verifiqué que Claude sí corrigió `pipeline_lock.py`, fingerprints históricos, `--dry-run`, doble etiquetado, `START_HERE.md` y el payload/hash/veredicto del benchmark.
- **Estado engañoso:** `run_state.json` marca `dedupe_fulltext` como `done` (run_id `3b8870fcd7e0`), pero no existen `dedupe_origin_events.jsonl` ni `dedupe_manifest_v2.jsonl`. Además, `fulltext_v2` sigue incompleto (último registro observado: 485/1.962). Ese `done` parece una prueba/smoke run y no debe presentarse como deduplicación productiva.
- **Artefactos ambiguos:** `comparison_12docs.json` (13:08) es de la corrida anterior al fix; `veredicto_1docs.json` (13:11) es solo el dry-run corregido y dice `ADOPTAR_HIGH`. El rerun corregido de 12 recién está en curso y reutiliza nombres, por lo que hay riesgo de leer un resultado viejo como final. Conviene guardar cada corrida bajo `run_id`.
- **Benchmark aún incompleto como gate:** `compare_effort.py` omite pares donde falla una de las dos llamadas, no valida formalmente el JSON contra el schema y no incorpora como condición obligatoria la revisión manual contra el texto fuente. Un resultado parcial podría pasar a un veredicto favorable.

## Actualización checkpoint 04 — estado tras la última ronda de Claude

**Fecha:** 2026-09-12 13:35 (America/Santiago). Auditoría de solo lectura.

### Correcciones confirmadas

- `enrich_case.py` ahora reintenta errores de red/429 y valida la respuesta con `jsonschema`.
- `compare_effort.py` registra `omitted`, incluye el conteo de omitidos y etiqueta el veredicto como candidato/no definitivo con `confirmado_manualmente=false`.
- `active-context.md` ahora separa explícitamente estado actual e histórico superado.
- `classify_luna.py` acepta `detail` en el lock, `--urls-file` y `--output-file`.

### Pendientes o límites aún observables

1. **La corrida que está en curso no prueba los fixes nuevos.** El proceso `compare_effort` empezó a las 13:11:55; `compare_effort.py` fue modificado a las 13:27:22 y `enrich_case.py` a las 13:26:34. Python ya había cargado el código anterior. Por tanto, el progreso 11/12, los omitidos por SSL y el desacuerdo de `tipo_evidencia` no pueden presentarse como verificación de la versión corregida. Hace falta una corrida completa relanzada después de las modificaciones.
2. **Metadato de esfuerzo mal rotulado.** En `enrich_case.py`, el registro de salida todavía escribe `"reasoning_effort": REASONING_EFFORT` en vez del parámetro `effort`. Una llamada `effort="high"` puede quedar registrada como `xhigh`; no altera necesariamente el payload, pero rompe la trazabilidad del benchmark.
3. **Locks sin detalle en dos scripts.** `compare_effort.py` y `dedupe_fulltext.py` siguen llamando `acquire_lock(...)` sin `detail`. El mecanismo acepta el detalle, pero esos runs continuarán siendo ambiguos en `run_state.json`. `classify_luna.py` sí lo pasa, aunque el estado `done` observado fue creado antes del cambio y por eso no contiene `detail`.
4. **Artefactos reutilizan nombres fijos.** `comparison_{n}docs.json` y `veredicto_{n}docs.json` pueden sobrescribir una corrida anterior (incluido el `comparison_12docs.json` viejo). Para auditoría, cada corrida debe usar `run_id`/timestamp o un subdirectorio inmutable, y el veredicto debe declarar el fixture y los omitidos.
5. **La deduplicación aún no tiene artefactos reales.** No existen `dedupe_origin_events.jsonl` ni `dedupe_manifest_v2.jsonl`; no corresponde tratar cualquier estado histórico de dedupe como producción hasta correrla sobre el `fulltext_v2` completo.

**Conclusión:** esta ronda arregla varios defectos de código y documentación, pero todavía no es un cierre verificable. El siguiente checkpoint debe basarse en una nueva ejecución post-fix y en artefactos versionados; no en el proceso que ya estaba vivo cuando se editaron los scripts.

## Actualización checkpoint 05 — tercera ronda adversarial

- `CLAUDE_RESPONSE.md` registra una tercera auditoría vía `codex:codex-rescue`, esfuerzo `xhigh`, solo lectura. El registro no contiene un identificador verificable de modelo (`gpt-5.6-luna`); por tanto, solo puede afirmarse la ruta/subagente y el esfuerzo, no que fuera Luna.
- La ronda detectó y corrigió problemas importantes: coordinación productor/consumidor entre etapas, carrera de `run_state`, lock huérfano, JSONL truncado, checkpoint incremental de compare, gate de citas de actores y contrato v2.
- El comparativo post-fix sigue ejecutándose. En el log v3 ya aparecen regresiones de citas en high y una diferencia de evidencia/actores; no corresponde anunciar adopción de `high` antes del cierre. El resultado terminado anterior mantiene `xhigh`.
- `dedupe_fulltext: done` ahora tiene `detail` apuntando a un directorio temporal de prueba (`D:\Temp\...\scratchpad\dedupe_final_check`), no a `Fuentes/fulltext_v2`; esto es más transparente, pero no equivale a deduplicación productiva.
- `fulltext_acquisition_v2` continúa con el proceso iniciado antes de los últimos cambios. Al finalizar, su salida debe validarse y la etapa debe relanzarse o reconciliarse si se necesita probar específicamente el código post-fix.
