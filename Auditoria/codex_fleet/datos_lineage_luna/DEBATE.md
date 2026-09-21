# Debate cruzado de hallazgos — datos/lineage vs arquitectura/runtime

Fecha de contraste: 2026-09-12. Solo lectura; sin APIs, Claude ni cambios de producción. Se compararon `arquitectura_luna/FINDINGS.md`, `runtime_luna/FINDINGS.md`, mis comprobaciones y el estado actual en disco.

## Conclusión ejecutiva

No hay un P0 demostrado, pero sí bloqueadores P1 antes de aceptar el corpus como producción: (a) frontera de snapshot sin validación de contrato, (b) pérdida de orígenes por deduplicación temprana de URL, (c) manifest fulltext producido por una corrida pre-fix que ya contiene 429/503, y (d) reanudación de discovery que confunde “hay una fila” con “consulta completa”. Los mecanismos de lock/mutex agregan P1 de resiliencia para la próxima corrida larga. `evidence_verified` es un defecto semántico P2 latente, no evidencia de contaminación actual: todavía no existe `clasificacion_luna_v2`.

## 1. ¿El snapshot realmente mezcla contratos?

**Confirmado, con una precisión importante.** La inmutabilidad física no falla: el snapshot `20260912_153729_835` mantiene SHA-256 `3cf4cd4c...`, y sus 2.687 líneas coinciden con el `.meta.json`. Lo que falla es la frontera semántica: `snapshot_discovery.py:76-90` valida JSON parseable, no exige los campos v2.

La comprobación actual encontró 2.592 registros con `periodo`/`nivel` y 95 sin ambos. Esos 95 corresponden a 8 queries y 4 comunas legacy; además, sus `record_hash` validan con la forma histórica (sin periodo), mientras los 2.592 nuevos validan con la fórmula v2 (incluye periodo). Por tanto, no es una inferencia basada solo en nombres: son dos contratos de registro dentro de una misma instantánea.

**Causa raíz:** el manifest activo acumuló generaciones y el snapshot no aplica un gate de schema/version/hash-algorithm.

**Síntoma separado:** los 67 documentos legacy que ya llegaron a `fulltext_v2` llevan `snapshot_run_id` y hash correctos, pero `lineage.periodo=""` y `lineage.nivel=""`. La lineage no desaparece completa; pierde dimensiones temporales/nivel.

**Prioridad:** P1 antes de clasificar/enriquecer. La corrección mínima es aislar legacy como `legacy_v1` o rechazarlo al snapshot; no basta con cambiar el nombre a v2.

## 2. ¿Se pierde lineage antes de dedupe?

**Confirmado y más amplio que la pérdida temporal.** `load_unique_discoveries()` (`fulltext_acquisition_v2.py:76-91`) usa `record_hash` y luego `resolved_url` como identidad global. En el snapshot hay 1.964 URLs distintas; 355 tienen más de una combinación de comuna/término/periodo/nivel, abarcando 996 filas. El ejemplo de `infraestructurapublica.cl` tiene cuatro orígenes, pero `fulltext_v2` conserva solo el primero, legacy Las Condes.

La comprobación actual reproduce `load_unique_discoveries()` con 1.964 URLs retenidas y 723 filas de origen descartadas. El fulltext conserva la lineage primaria que ganó, pero no guarda `origins[]` ni un evento de descarte para las demás; dedupe ya no puede recuperar esa información.

**Causa raíz:** se confunden tres identidades distintas: URL física, documento/contenido y origen de discovery. El dedupe por contenido ocurre demasiado tarde para recuperar lineages que nunca se materializaron.

**Corrección mínima:** persistir todos los orígenes del URL en un índice/evento de discovery antes de reducir las descargas físicas, o materializar una fila de origen por lineage junto a una sola extracción de contenido. No es necesario descargar cuatro veces; sí es necesario conservar las cuatro proveniencias.

**Prioridad:** P1. Debe corregirse antes de usar el corpus para atribución comunal/temporal.

## 3. Revisión de los hallazgos de arquitectura

### F-002 y F-003: aceptados, con ajuste de severidad

La pérdida de orígenes (F-002) está directamente verificada y es P1. La idempotencia por URL (F-003) también es real en el código (`already_processed_urls`, `already_classified_urls`, `already_enriched_urls`), pero es un riesgo de futuras corridas, no una pérdida nueva demostrada en el snapshot actual. Se clasifica P2 alto hasta definir la política de refresco: mismo URL con contenido cambiado, nuevo snapshot o nuevo origen.

### F-004: parcialmente refutado, pero queda un defecto real

La afirmación exacta “si se cae después de `canonical_elected` y antes de `origin_added`, el origin se pierde para siempre” no se sostiene para el caso normal: `new_events` agrega primero el canónico, el URL del origin todavía no tiene evento, y en la siguiente corrida queda pendiente y puede producir `origin_added`.

El defecto general sí existe: `append_events()` (`dedupe_fulltext.py:92-98`) no es transaccional ni usa `flush/fsync`; además, los `fingerprint_candidate` se agregan antes de los eventos `canonical_elected` (`241-293`). Un crash después de persistir solo `fingerprint_candidate` hace que `already_eventful_urls()` excluya el URL y puede impedir que se escriba el canónico esperado. La vista `rebuild_manifest()` (`169-172`) también se publica con `write_text()` directo.

**Veredicto:** no aceptar la explicación específica del intervalo canonical/origin, pero aceptar el riesgo de persistencia parcial y publicación no atómica. P2 antes de habilitar dedupe productivo; subir a P1 si se exige recuperación automática tras crash.

### F-005: aceptado como defecto de contrato, no como output contaminado actual

`classify_document()` hace `json.loads()` pero no `jsonschema.validate()`, a diferencia de `enrich_case.py`. `postprocess_result()` puede persistir un objeto incompleto si el proveedor devuelve JSON válido pero incompatible. `response_format` es una ayuda del proveedor, no un gate local reproducible.

No hay `clasificacion_luna_v2` en disco, por lo que no se demuestra contaminación actual. P2 antes de publicar clasificación v2.

### F-001: aceptado como el mismo problema de frontera contractual

F-001 y DL-03 no son dos causas distintas: la causa es el snapshot sin gate de contrato; la lineage vacía es el síntoma downstream. Mantenerlos separados en el reporte ayuda a evidenciar ambos, pero el fix debe ser uno: schema/version gate en snapshot más partición legacy.

## 4. Revisión de los hallazgos de runtime

### RL-01: aceptado como P1 de cobertura

`already_queried_combos()` considera completo un combo al encontrar cualquier fila (`brightdata_discovery.py:301-314`). La escritura por resultado (`358-390`) no deja `query_completed`. La simulación del peer es suficiente y el mecanismo es determinista: un crash después del rank 1 hace que ranks 2+ no vuelvan a solicitarse.

Esto es distinto de la mezcla v1/v2: una consulta puede estar en el contrato correcto y aun así quedar truncada sin señal. Debe corregirse antes de declarar completo un discovery reanudado.

### RL-02: aceptado como P1 de recuperación, no como incidente actual

Un `os._exit()` puede dejar lock y estado `running`; el `finally` no puede ejecutarse ante terminación dura. El PID 42408 observado estaba vivo durante esta auditoría, por lo que no se debe etiquetar el lock actual como huérfano. El defecto es la ausencia de recuperación explícita (`needs_resume`/heartbeat/PID liveness) para futuras caídas.

### RL-03: aceptado como P1 de coordinación

`_run_state_mutex()` borra el archivo compartido al superar el timeout (`pipeline_lock.py:94-106`) sin token de ownership. La prueba de solapamiento demuestra que deja de ser mutex bajo I/O lento. El comentario reconoce el riesgo, pero “riesgo aceptable” no es suficiente para un estado que decide si las etapas pueden avanzar.

### RL-04: aceptado parcialmente como P2

La vista materializada se escribe de forma directa y puede quedar parcial; `read_jsonl_tolerant()` evita el crash, pero puede convertir la pérdida de la última línea en omisión silenciosa. El problema no es que toda caída entre canonical/origin pierda necesariamente un origin —ver F-004—, sino que no existe publicación atómica ni generación verificable de la vista.

## 5. `evidence_verified`: ¿engaño semántico o falso positivo actual?

**Es semánticamente engañoso, pero todavía no es contaminación de producción.** `quote_is_grounded("", texto)` devuelve `True` deliberadamente para permitir citas vacías en decisiones no `include`. Eso, aislado, es un predicado razonable: “no hay cita que verificar”.

El problema aparece en `postprocess_result()` (`classify_luna.py:234-255`): el booleano se copia sin condición al campo `evidence_verified`. La prueba estática produjo `decision=exclude`, `evidence_quote=""`, `evidence_verified=true`. Un consumidor que filtre por ese campo puede interpretar que existe evidencia verificada, cuando solo se cumplió una verdad vacía.

El gate bloqueante de `include` sí está separado (`len(evidence_quote) >= 15` y substring literal), por lo que no refuto ese fix. Lo que debe cambiar es el contrato del campo: `false`/`null` para no-include, o separar `evidence_present` de `evidence_verified`.

**Prioridad:** P2 antes de generar clasificación v2; no requiere retro-limpieza porque no existe output v2 actual.

## 6. Orden de corrección antes de seguir

1. **P1 inmediato — congelar y etiquetar el proceso actual:** no consumir `fulltext_v2` como final mientras PID 42408 siga activo; conservar su salida como corrida pre-fix y reconciliar 429/503 antes de downstream.
2. **P1 — cerrar snapshot/discovery:** agregar marcador `query_completed`, gate de schema/version/hash y partición legacy; conservar todos los orígenes de cada URL.
3. **P1 — endurecer runtime de coordinación:** recuperación explícita de crash/lock y mutex con ownership/lease; no avanzar consumidores con estado `running` incompatible o stale.
4. **P1 — reconstruir fulltext bajo un run_id/código/snapshot fingerprint:** excluir transitorios del manifest procesado y probar incrementalidad con fixtures.
5. **P2 — antes de clasificar/enriquecer:** validar localmente classification schema, corregir `evidence_verified`, y decidir política de re-fetch/reclasificación por hash de contenido/versionado.
6. **P2 — antes de dedupe productivo:** publicar eventos y materialized view con checkpoint/generación atómica; conservar evento de batch incompleto.

## Evidencia de control

- Snapshot SHA-256 y conteo de líneas pasan contra `.meta.json`.
- En el estado observado, `fulltext_v2` pasó de 1.877 a 1.964 filas mientras seguía corriendo; el cambio confirma que los conteos son fotografías, no un cierre.
- No existen todavía `dedupe_origin_events.jsonl`, `dedupe_manifest_v2.jsonl`, `clasificacion_luna_v2` ni `enriquecimiento_v2`; por ello las conclusiones downstream son de contrato/código y no falsos positivos sobre outputs inexistentes.
