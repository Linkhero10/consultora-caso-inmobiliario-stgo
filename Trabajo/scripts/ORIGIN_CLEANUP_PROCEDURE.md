# Procedimiento durable de reconciliación de lineage

Este documento conserva el procedimiento que produjo
`Auditoria/lineage_repair/origin_cleanup_20260912T191739Z.json`. Su objetivo es
evitar que una reconciliación de `origins[]` dependa de un comando efímero.

## Precondiciones

1. No debe existir lock activo de `fulltext_acquisition_v2`,
   `dedupe_fulltext`, `classify_luna`, `enrich_case` ni otro cleanup.
2. El snapshot debe identificarse por `run_id` y tener
   `record_schema_version=discovery_snapshot_v3`.
3. Leer todos los JSONL en modo estricto; una línea inválida bloquea la
   operación.
4. Crear backups con el mismo `run_id` antes de escribir.

## Operación

`repair_fulltext_lineage.py --snapshot-run-id <run_id> --apply` reconstruye el
lineage por URL sin llamar a APIs. Después, `dedupe_fulltext.py` reconstruye la
vista desde `dedupe_origin_events.jsonl`. La deduplicación de
`lineage.origins` debe conservar todos los `discovery_record_hash` distintos,
junto con `query_hash` y `plan_version` para identificar la consulta completa y
el contrato que la generó, y
no cambiar decisiones de clasificación.

Para materializar el alcance temporal en clasificaciones ya existentes:

```powershell
python Trabajo/scripts/backfill_corpus_scope.py
python Trabajo/scripts/backfill_corpus_scope.py --apply
```

El segundo comando usa lock, escritura atómica y produce un reporte bajo
`Auditoria/corpus_scope_backfill/`. Solo agrega `corpus_scope`; no llama al
modelo ni modifica `decision`, `evidence_quote` o `lineage`.

## Evidencia de la corrida ya realizada

- Reporte: `Auditoria/lineage_repair/origin_cleanup_20260912T191739Z.json`.
- Backups: `Auditoria/lineage_repair/*pre_origin_cleanup_20260912T191739Z`.
- Resultado: 1.964 filas fulltext, 355 URLs con múltiples orígenes; dedupe
  783/56/0/1.125; scope 747 temporal, 34 legacy puro, 2 mixto.
- Backfill de scope: `Auditoria/corpus_scope_backfill/scope_backfill_20260913T003022Z.json`.

No declarar el corpus final hasta cerrar discovery y crear un snapshot v3 nuevo.
