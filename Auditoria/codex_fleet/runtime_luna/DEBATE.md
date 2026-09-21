# Debate cruzado de auditorías — runtime Luna

Fecha: 2026-09-12  
Participantes contrastados: `arquitectura_luna/FINDINGS.md`, `datos_lineage_luna/FINDINGS.md` y la auditoría runtime de esta carpeta.  
Método: lectura de código/artefactos actuales y pruebas deterministas aisladas; sin APIs, Claude ni ediciones de producción.

## Estado observado al contrastar

`run_state.json` ya refleja `fulltext_acquisition_v2=done` y `dedupe_fulltext=done`; el dedupe produjo `dedupe_origin_events.jsonl` y `dedupe_manifest_v2.jsonl` (1.964 líneas cada uno). `classify_luna` terminó una corrida con `detail.es_produccion=false` y salida `Auditoria/muestras_control/clasificacion_sample_10.jsonl`; no equivale a clasificación v2 productiva. No existe salida productiva de enrichment v2. El snapshot sigue teniendo 2.687 filas y el fulltext manifest 1.964 filas.

## Veredictos por afirmación

### 1. F-001 / DL-03 — mezcla de generaciones y lineage incompleta

**Veredicto: confirmado y bloqueante para cerrar el corpus como v2.**

El snapshot acepta cualquier línea JSON parseable (`snapshot_discovery.py:76-90`) y no exige `contract_version`, `periodo` ni `nivel`. Recuento independiente actual: `2687` filas, `95` sin `periodo`, `95` sin `nivel`, `0` con `contract_version`. El fulltext conserva esas ausencias en la `lineage` de los registros heredados. Esto no es solo una etiqueta histórica: el contrato v2 declara cuatro ventanas y exige trazabilidad a la query exacta. Debe separarse como `legacy_v1` o rechazarse antes de cualquier afirmación de cobertura v2.

La duplicación entre los dos informes se debe tratar como una sola causa raíz (frontera de snapshot sin validación) con dos consecuencias: snapshot impuro y output downstream semánticamente incompleto.

### 2. F-002 — `load_unique_discoveries()` elimina orígenes antes de dedupe

**Veredicto: confirmado y bloqueante para la trazabilidad de origen.**

La comprobación independiente contó `355` URLs con más de una combinación de comuna/término/período/nivel, frente a `1.964` URLs únicas tanto en snapshot deduplicado como en fulltext. `fulltext_acquisition_v2.py:76-91` usa `seen_urls` y conserva solo el primer registro; `lineage` no tiene `origins[]`. Dedupe posterior no puede reconstruir queries que nunca llegaron al archivo de contenido. Una extracción física por URL puede ser razonable, pero debe persistir todos los orígenes antes de descartar duplicados físicos.

### 3. F-003 — idempotencia incremental basada solo en URL

**Veredicto: confirmado como riesgo alto/condicional, no como bug universal.**

`already_processed_urls()` y sus equivalentes de clasificación/enrichment usan URL como clave. Eso evita repetir una fuente histórica, pero también ignora una nueva `snapshot_sha256`, cambio de contenido o nueva combinación de lineage. Si la política del proyecto declara una URL como fuente inmutable, puede aceptarse para el texto; no puede aceptarse para la trazabilidad completa exigida por v2. La corrección mínima es definir explícitamente la política y versionar por URL + hash de contenido/snapshot cuando el origen o texto cambie.

### 4. DL-01 — corrida activa sin fingerprint de código/contrato

**Veredicto: confirmado como riesgo de reproducibilidad; parcialmente mitigado, no resuelto.**

La entrada nueva de `run_state` sí registra `run_id`, timestamps y `detail`, pero no registra hash de scripts, contrato, prompt ni snapshot en el estado de etapa. Además, los registros de fulltext no llevan `run_id` de ejecución ni fingerprint de código. El hecho de que la corrida previa comenzara antes de parches no puede probarse solo desde el output, pero precisamente esa atribución falta. No debe mezclarse un output generado por proceso pre-fix con una conclusión de contrato vigente. Es bloqueo de cierre reproducible, aunque no impide inspeccionar el proceso actual.

### 5. DL-02 — fallos transitorios ya presentes en el manifest

**Veredicto: confirmado y bloqueante para completitud; el código vigente sí cubre nuevas corridas, pero no repara el artefacto anterior.**

El manifest actual contiene `http_error_429=2`, `http_error_503=3` y `error=27`; hay `1.079` filas con `char_count=0`. El código vigente evita escribir 429/5xx/transitorios, pero `already_processed_urls()` no distingue filas antiguas y las omite en la siguiente corrida. El fix de código no retroactúa sobre el manifest. Debe reconstruirse una vista de procesados excluyendo esos outcomes y reintentarse con un run nuevo, conservando el intento antiguo como evidencia.

### 6. DL-04 — ausencia de outputs v2 downstream

**Veredicto: parcialmente superado.**

Ya existe dedupe productivo según `run_state` y sus dos artefactos tienen 1.964 líneas. Por tanto, la afirmación literal “no existe dedupe” ya no es vigente. Sí permanece la parte crítica: no hay clasificación v2 productiva ni enrichment v2; la salida observada de clasificación está marcada `es_produccion=false`, y el E2E no está cerrado.

### 7. F-004 — pérdida permanente de `origin_added` tras crash de append

**Veredicto: refutado en su forma fuerte; queda riesgo de durabilidad no transaccional.**

La prueba aislada hizo que `append_events()` escribiera solo el primer evento (`canonical_elected`) y fallara. En la segunda corrida, la URL sin evento se mantuvo pendiente, se generó `origin_added`, y la vista terminó con `canonico` + `duplicado_exacto` para ambas URLs. Esto se explica por `already_eventful_urls()` por URL y el orden actual de eventos. Por tanto, no hay evidencia de pérdida permanente de un origin completo bajo ese patrón.

Sí queda el hallazgo runtime RL-04: `append_events()` no hace `fsync` y `rebuild_manifest()` usa `write_text()` directo. Una terminación durante la publicación puede dejar la vista materializada inválida o perder una línea durable hasta el siguiente ciclo; debe endurecerse con temp + `os.replace` y metadata de generación. No debe describirse como pérdida irrecuperable de origins sin reproducir un caso distinto.

### 8. F-005 — clasificación sin validación local contra schema v2

**Veredicto: confirmado, riesgo medio-alto downstream.**

`classify_document()` parsea JSON y `postprocess_result()` solo corrige algunos campos; no llama `jsonschema.validate`, a diferencia de `enrich_case.py`. Una prueba determinista con `{"decision":"include"}` produjo `decision_after_postprocess=uncertain` pero dejó ausentes siete campos requeridos. El gate de cita para `include` está cubierto; la forma estructural completa no. Debe añadirse validación antes de escribir el registro y una regresión de respuesta parcial.

### 9. F-006 / RL-02 — liveness y recuperación de locks

**Veredicto: confirmado y bloqueante ante crash duro; parcialmente cubierto para salidas normales.**

`try/finally` libera locks en excepciones/salidas normales, pero no en `os._exit`, kill o apagado. La prueba aislada dejó `lock_left_after_hard_exit=True` y `state_running_after_hard_exit=running`. El código no valida PID vivo ni tiene estado `needs_resume`; downstream solo consulta `estado == running`. Esto se solapa con RL-02 y debe resolverse con recuperación explícita, nunca marcando automáticamente `done`.

### 10. RL-01 — checkpoint de discovery por consulta incompleto

**Veredicto: confirmado y bloqueante para reanudación.**

`brightdata_discovery.py` escribe cada resultado, pero `already_queried_combos()` considera completa una consulta al encontrar una sola línea del combo. La prueba aislada con un solo resultado produjo `combo_seen_after_one_record=True` y `pending_same_combo_after_crash=0`. Es un fallo independiente de los problemas de snapshot: aunque el contrato de campos fuera correcto, un crash dentro de una respuesta SERP aún pierde los ranks restantes.

### 11. RL-03 — timeout del mutex `run_state` rompe exclusión

**Veredicto: confirmado, riesgo alto bajo I/O lento; no observado como causa del estado actual.**

Con timeout aislado de 0,02 s, un hilo sostuvo el mutex 0,10 s y otro entró simultáneamente tras borrar el archivo. La salida fue `holder_and_contender_overlap=True`. El caso nominal de escrituras rápidas funciona, pero el mecanismo deja de ser mutex durante un stall de disco/proceso. Debe sustituirse el borrado ciego por ownership/lease verificable o un lock de sistema; no se debe presentar como una carrera ya ocurrida en producción.

## Clasificación final

### Bloqueantes antes de declarar producción v2

- Aislar/rechazar los 95 registros legacy del snapshot y completar la frontera de contrato/versionado.
- Preservar los 355 conjuntos de orígenes múltiples antes de deduplicar físicamente por URL.
- Reprocesar las 5 filas transitorias 429/503 y las 27 filas `error` que ya contaminan la vista de URLs procesadas.
- Corregir el checkpoint por consulta de discovery.
- Definir recuperación segura después de crash duro; mientras tanto un lock/estado `running` debe bloquear con atención explícita.
- No aceptar clasificación/enrichment v2 como E2E hasta que existan outputs productivos y hashes de entrada.

### Riesgos altos a resolver antes de declarar resiliencia

- Fingerprint de código/contrato/snapshot por corrida.
- Idempotencia versionada cuando cambia contenido o lineage.
- Mutex `run_state` sin borrado ciego tras timeout.
- Publicación atómica de la vista materializada y durabilidad de eventos JSONL.

### Riesgos aceptables solo si se documentan

- `evidence_verified=true` para decisiones no-include es semánticamente ambiguo, pero no rompe el gate de `include`; debe separarse antes de usarlo como métrica downstream.
- Mantener una extracción física por URL puede ser aceptable para costo, siempre que se persista `origins[]` completo y se declare la política de contenido/versiones.
- El benchmark high/xhigh v1 es reproducible internamente, pero no evidencia calidad ni esfuerzo para v2.

## Condición de cierre propuesta

No declarar “pipeline resiliente/producción v2” hasta que exista una cadena observable `snapshot validado -> fulltext versionado y sin transitorios procesados -> origins completos -> dedupe atómico -> clasificación v2 validada -> enrichment v2`, con cada etapa registrando `run_id`, hashes de entradas/contrato y recuperación comprobable tras crash.
