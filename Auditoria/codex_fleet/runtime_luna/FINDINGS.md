# Auditoría adversarial de runtime — GPT-5.6 Luna

Fecha: 2026-09-12  
Alcance: solo lectura del runtime real del caso inmobiliario; ejecución de pruebas deterministas únicamente en directorios temporales aislados. No se llamaron APIs, Claude ni procesos de producción, y no se editó código de producción.

## Resumen ejecutivo

Se verificaron cuatro fallos de ejecución/resiliencia. El más grave es la reanudación del discovery: el manifest se escribe por resultado, pero la reanudación decide que una consulta completa está hecha al encontrar una sola línea de esa consulta; un crash a mitad de una respuesta SERP pierde silenciosamente los resultados restantes. También se verificó que un crash duro deja lock y estado `running` sin mecanismo de recuperación, que el mutex de `run_state` deja de ser excluyente cuando supera su timeout fijo, y que la vista materializada de dedupe se escribe de forma no atómica y puede quedar inválida.

Estado observado en disco durante la auditoría: `_FARO/memory-bank/run_state.json` marca `fulltext_acquisition_v2` como `running`, con lock `fulltext_acquisition_v2.lock`; el PID 42408 estaba vivo y respondía en la comprobación, por lo que no se trató ese caso actual como huérfano.

## Hallazgo RL-01 — checkpoint de discovery no es reanudable por crash dentro de una consulta

- **Severidad:** Alta (pérdida silenciosa de cobertura; no es solo duplicación).
- **Archivo/líneas:** `Trabajo/scripts/brightdata_discovery.py:301-314` y `358-390`.
- **Evidencia reproducible:** en un scratchpad temporal se creó un manifest con una sola línea del combo `(Renca, edificio, 2014_2017, comuna)`, simulando que el proceso murió después del primer resultado orgánico. `already_queried_combos()` devolvió el combo como hecho y el filtro de reanudación produjo `pending_same_combo_after_crash: 0`. Salida exacta: `{'combo_seen_after_one_record': True, 'pending_same_combo_after_crash': 0}`.
- **Causa raíz:** los registros se agregan por resultado (`manifest_file.write(...); flush()`), pero el checkpoint de reanudación se infiere de la existencia de cualquier registro del combo. No hay un evento/marker `query_completed` escrito solo después de terminar todo el arreglo `organic`; tampoco se persiste el último `rank` de forma suficiente para continuar.
- **Impacto:** si Bright Data devuelve 10 resultados y el proceso muere tras los primeros 1–9, el siguiente ciclo omite la consulta completa y los resultados restantes nunca entran al corpus. El proceso puede terminar con apariencia normal y sin alerta de pérdida.
- **Corrección recomendada:** separar `query_started/query_completed` en un checkpoint append-only, o reanudar por `(combo, rank)` y considerar terminado el combo únicamente después de recorrer todos los resultados de la respuesta. Validar además que la respuesta SERP fue recibida y serializada completa antes de marcarla completa.
- **Regresión necesaria:** fixture de una consulta con tres resultados; interrumpir después del primer append y relanzar. El segundo ciclo debe recuperar ranks 2–3 y nunca omitirlos. Repetir con crash entre el último resultado y el marker de completitud.

## Hallazgo RL-02 — crash duro deja lock y etapa `running` sin recuperación automática

- **Severidad:** Alta (bloqueo de reanudación tras fallo de proceso; requiere intervención manual).
- **Archivo/líneas:** `Trabajo/scripts/pipeline_lock.py:9-14`, `213-221`, `223-263`; coordinación downstream en `186-194`.
- **Evidencia reproducible:** prueba aislada con un subproceso temporal que entró a `with acquire_lock('crash_stage')` y terminó con `os._exit(7)` (salida sin `finally`). Resultado: `{'child_exit': 7, 'lock_left_after_hard_exit': True, 'state_running_after_hard_exit': 'running'}`.
- **Causa raíz:** `finally` cubre excepciones/salidas normales, pero no terminación dura, kill, pérdida de proceso o apagado. El lock tiene una antigüedad informativa (`LOCK_STALE_HOURS`) pero el código explícitamente no lo rompe; `upstream_stage_is_running()` sigue considerando `running` como señal de productor activo. No existe heartbeat, comprobación de PID vivo, estado `aborted/needs_resume`, ni comando de recuperación seguro.
- **Impacto:** después de un crash, la etapa bloqueada devuelve `LockBusyError`; consumidores como `dedupe_fulltext`, `classify_luna` y `enrich_case` pueden saltar por `running`. El pipeline queda detenido hasta que alguien inspeccione y retire manualmente lock/estado, con riesgo de marcar falsamente una etapa como terminada o borrar un lock de un proceso aún vivo.
- **Corrección recomendada:** mantener el fail-closed para un lock no verificable, pero añadir recuperación explícita: metadata con PID/heartbeat, verificar que el PID no existe (y que el lock no cambió) antes de marcar `failed/needs_resume`, y una operación idempotente de `recover_stage`. Nunca convertir automáticamente un lock viejo en `done`.
- **Regresión necesaria:** subproceso que termina con `os._exit`; el siguiente invocador debe detectar `needs_resume`, no clasificar ni marcar `done`, permitir recuperación segura tras confirmar PID muerto y dejar evidencia de la transición.

## Hallazgo RL-03 — el mutex de `run_state` pierde exclusión al superar 5 segundos

- **Severidad:** Alta (puede corromper el estado de coordinación y las decisiones productor/consumidor bajo I/O lento).
- **Archivo/líneas:** `Trabajo/scripts/pipeline_lock.py:81-115`.
- **Evidencia reproducible:** prueba aislada con `RUN_STATE_MUTEX_MAX_WAIT_S=0.02`: un hilo sostuvo `_run_state_mutex()` durante 0.10 s y otro hilo, al expirar el timeout, eliminó el mutex y entró simultáneamente. Salida exacta: `{'holder_and_contender_overlap': True, 'mutex_exists_after': False}`.
- **Causa raíz:** tras el timeout, el contendor ejecuta `RUN_STATE_MUTEX_PATH.unlink()` sin ownership token/lease y vuelve al bucle. Puede borrar el mutex de un escritor legítimo que sigue dentro de la sección crítica. El comentario reconoce el riesgo, pero el mecanismo deja de ser un mutex real precisamente durante una escritura lenta.
- **Impacto:** dos read-modify-write pueden solaparse; una actualización de etapa puede perderse, quedar con `run_id`/estado de otra ejecución o hacer que un consumidor observe un estado incorrecto. Eso puede habilitar lectura prematura o bloquear una etapa equivocadamente.
- **Corrección recomendada:** no romper el mutex automáticamente; usar un lock de sistema/handle con liberación por proceso o un lease con token único, timestamp y renovación. Si se requiere recuperación, solo eliminar un lease cuyo owner PID esté muerto y cuyo token siga coincidiendo; de lo contrario devolver estado de recuperación requerida.
- **Regresión necesaria:** mantener un escritor dentro de la sección crítica más allá del timeout configurado y confirmar que el segundo escritor no entra ni pierde actualizaciones. Añadir prueba multiproceso, no solo threads, porque el archivo es compartido entre procesos.

## Hallazgo RL-04 — la vista materializada de dedupe se escribe directamente y puede quedar JSONL inválida

- **Severidad:** Media-Alta (artefacto de coordinación inconsistente; puede ocultar exclusiones de duplicados al reanudar manualmente).
- **Archivo/líneas:** `Trabajo/scripts/dedupe_fulltext.py:92-98` y `169-172`; lector tolerante en `Trabajo/scripts/pipeline_lock.py:143-170`.
- **Evidencia reproducible:** se ejecutó `rebuild_manifest()` contra eventos temporales, sustituyendo únicamente `MANIFEST_PATH.write_text` por una escritura parcial seguida de una excepción para simular crash. Resultado: `{'manifest_exists_after_crash': True, 'manifest_jsonl_valid': False, 'bytes_written': 76}`.
- **Causa raíz:** `append_events()` tampoco hace `flush/fsync`; la vista completa se reemplaza con `write_text()` directo, sin archivo temporal + `os.replace()` ni marker de generación. `read_jsonl_tolerant()` evita que una línea truncada derribe todo, pero descarta esa línea; no repara ni asegura que la vista materializada conserve el canon/exclusiones.
- **Impacto:** un crash durante la reconstrucción puede dejar un manifest parcial. Si se fuerza una reanudación o se corrige manualmente el estado sin reconstruir primero desde `dedupe_origin_events.jsonl`, la clasificación puede no ver `duplicado_exacto` y procesar un documento que debía excluirse. La tolerancia evita el crash del lector, pero convierte una pérdida de estado en una omisión silenciosa.
- **Corrección recomendada:** construir la vista en `dedupe_manifest_v2.jsonl.tmp.<run_id>`, hacer `flush + os.fsync`, y publicar con `os.replace`; escribir/validar metadata de generación y reconstruir siempre desde eventos antes de permitir al consumidor avanzar. Para JSONL append-only, hacer `flush + fsync` por checkpoint relevante o documentar la ventana de pérdida.
- **Regresión necesaria:** simular terminación durante la publicación y verificar que el manifest anterior permanece íntegro; simular truncamiento de la última línea de eventos y confirmar que la reconstrucción produce una vista completa y verificable antes de `classify_luna`.

## Comprobaciones adicionales

- El runtime FARO pasó `PASS FARO runtime`.
- El proceso de `fulltext_acquisition_v2` observado durante la revisión estaba vivo (`PID 42408`, `python`, `Responding=True`); no se alteró ni se trató como lock huérfano.
- No se ejecutaron llamadas Bright Data/OpenRouter ni se tocaron artefactos de producción. Las pruebas fueron importación de módulos y simulaciones temporales, con limpieza del scratchpad al finalizar.
- No se tomó `CLAUDE_RESPONSE.md` ni los checkpoints QA previos como fuente de verdad; los cuatro hallazgos se derivan de código, estado/logs actuales y pruebas propias.
