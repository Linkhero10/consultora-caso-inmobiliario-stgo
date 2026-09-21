# Revisión Codex del reporte de Claude — 2026-09-12

## Actualización vigente — 2026-09-13

Los matices de la revisión original que aparecen más abajo quedan superados
en estos puntos: `corpus_scope` ya está materializado en las 783 clasificaciones
por `backfill_corpus_scope.py`; `query_hash` y `plan_version` ya se escriben en
discovery y se propagan al lineage de fulltext y de la reparación downstream.
La regresión está cubierta por `test_integrity_fixes.py` (13/13), el fixture de
reanudación (6/6) y AST/YAML (11 scripts). Sigue abierto, por diseño, el estado
del proceso discovery antiguo: aún no tiene `query_completed`, por lo que no se
debe declarar final ni crear snapshot v3 hasta su cierre.

## Revisión original (histórica; conservar para auditoría)

## Resultado

La reconciliación principal está respaldada por los artefactos reales:

- `origin_cleanup_20260912T191739Z.json` informa 1.964 filas de fulltext
  reconciliadas, 24 contenidos/filas modificados, 14 filas de clasificación
  ajustadas y dedupe reconstruido con 783 canónicos, 56 duplicados exactos,
  0 candidatos y 1.125 no elegibles.
- El fulltext actual tiene 1.964 filas JSONL válidas y 355 URLs con más de un
  origen en `lineage.origins`.
- El log de eventos de dedupe conserva lineage en las 1.964 filas y no fue
  reescrito por el cleanup (`source_event_log_unchanged=true`).
- Los tres usos de `os.fsync()` revisados operan sobre el mismo handle de
  escritura; no queda el patrón roto de reabrir en `rb`.
- El scope sidecar tiene 747 `temporal_v2`, 34 `legacy_sin_ventana` y 2
  `temporal_v2_mixed_legacy`. De los 195 `include`, 186 son elegibles y 9
  son legacy puro.

## Matices que quedaron anotados entonces

1. `Auditoria/clasificacion_luna_v2/classifications.jsonl` conserva 783 filas
   sin el campo materializado `corpus_scope`. `enrich_case.py` evita una fuga
   porque recalcula el scope desde `lineage` cuando el campo falta, pero un
   consumidor que lea directamente ese JSONL no debe asumir que el campo está
   presente. El próximo artefacto v2 final debe incluirlo o documentar el
   sidecar como fuente obligatoria.
2. No existe actualmente en el proyecto un archivo persistente llamado
   `backfill_lineage_origins.py`; sí existen backups y el reporte
   `origin_cleanup_20260912T191739Z.json`. No es un fallo de datos, pero limita
   la reproducibilidad exacta del comando de cleanup si no se conserva el
   script o su procedimiento.
3. `run_state.json` sigue registrando la reparación anterior, no una etapa
   separada para `origin_cleanup`; `active-context.md` describe el estado
   general pero no enlaza todavía ese reporte nuevo. Esto es una brecha de
   trazabilidad operativa, no evidencia de corrupción.

## Límites respetados entonces

Esta revisión fue solo lectura: no se detuvo el discovery, no se modificaron
scripts de producción y no se hicieron llamadas API. Los 67 registros legacy
siguen siendo provisionales hasta un snapshot v3 posterior al cierre del
discovery.

## Verificación posterior entonces

- Suite `test_integrity_fixes.py`: **12/12 OK**.
- AST de los 8 scripts críticos: **OK**.
- El manifest de discovery seguía creciendo (6.743.089 bytes, última escritura
  17:57:03); por eso no se tocó su lógica ni se creó todavía el snapshot v3.

## Revisión del fix `query_completed`

El cambio en `brightdata_discovery.py` y `snapshot_discovery.py` es correcto:
una consulta solo queda reanudable como completa después de escribir su evento
de cierre, y el snapshot excluye esos eventos de control. La prueba sintética
quedó finalmente persistida en
`Trabajo/scripts/tests/test_query_completed_resume.py` y pasó sus 3 casos sin
red ni API. La primera observación sobre fixture ausente queda superada por
esta corrección.

Hay una consecuencia operativa que debe quedar explícita: el proceso activo
fue iniciado con el código anterior. El manifest actual tenía 10.218 filas y
**0** eventos `query_completed`. Si se relanza el discovery sin una migración
o estrategia de transición, `already_queried_combos()` considerará todos los
2.336 combos pendientes y repetirá consultas ya ejecutadas. Es conservador
(evita perder rangos), pero implica costo y duplicados adicionales. No se debe
inventar completitud retrospectiva: al cerrar el proceso, conviene congelar el
manifest, medir el costo de reconsulta y decidir explícitamente si se reejecuta
todo bajo el contrato nuevo o se crea un backfill auditado de eventos solo para
consultas demostrablemente completas.

El flag `--trust-legacy-rows-once` reduce el costo de transición, pero no
elimina el riesgo: `legacy_any_row_combos()` vuelve a considerar completa una
consulta con cualquier fila. Además, “once” es una convención documental, no un
guard mecánico: el código no persiste una marca que impida volver a usar el flag
ni rechaza automáticamente un manifest que ya mezcle eventos nuevos y filas
legacy. Antes de usarlo, debe verificarse que el proceso corresponde realmente
al manifest viejo y registrar la decisión; idealmente, una futura versión debe
rechazar el flag después de la primera transición.

## Limitación de identidad de consulta

El marcador `query_completed` y los sets de reanudación identifican una
consulta por `(comuna, termino, periodo, nivel)`, pero no guardan un
`query_id`/hash de la query completa ni de la configuración del plan. Si en un
ciclo futuro cambia `COMUNA_QUERY_ANCHOR`, `EXCLUDE_DOMAINS`, los límites de
fecha o cualquier parte de la construcción de la URL, un marcador antiguo
podría hacer que se salte una consulta semánticamente nueva con la misma
tupla. El guard añadido resuelve la reutilización indebida del modo legacy,
pero no este versionado de identidad; antes de una nueva expansión del plan
conviene incorporar `query_hash` y una huella de configuración al evento.

## Cambios aplicados directamente por Codex

- `brightdata_discovery.py` ahora versiona la identidad completa de la query
  con `query_hash` y la usa en la reanudación estricta; los marcadores nuevos
  incluyen `plan_version`.
- `backfill_corpus_scope.py` materializó `corpus_scope` en las 783
  clasificaciones mediante escritura atómica y lock; reporte:
  `Auditoria/corpus_scope_backfill/scope_backfill_20260913T003022Z.json`.
- `ORIGIN_CLEANUP_PROCEDURE.md` conserva el procedimiento durable, precondiciones,
  backups y comandos de verificación de la reconciliación.
- Fixture extendido: 6 casos pasan sin red/API.
