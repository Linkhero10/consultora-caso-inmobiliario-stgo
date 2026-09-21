# Reconciliación de dedupe previa a la integración

Esta carpeta contiene una vista de deduplicación calculada desde los JSON de
contenido vigentes, después de reparaciones de extracción/fulltext. No reemplaza
el historial append-only y no cambia las clasificaciones ya pagadas.

## Artefacto vigente

Usar el `dedupe_manifest_reconciled_*.jsonl` con el `run_id` más reciente y su
`dedupe_reconciliation_*.json` compañero. El reporte incluye hashes de entrada
y salida, conteos, registros `not_eligible` que dejaron de serlo y el impacto
en la clasificación de producción.

## Resultado de la corrida 2026-09-16

- 10.498 archivos/URLs válidos; 0 JSON inválidos.
- 5.722 contenidos elegibles y 4.776 no elegibles.
- 5.421 canónicos, 301 duplicados exactos en 45 grupos y 31 candidatos por
  fingerprint corto.
- La URL CEACGR reparada que antes figuraba con `char_count=0` ahora aparece
  como duplicado exacto del canónico CEACGR con 546 caracteres.
- Solo un duplicado exacto ya estaba en producción; era
  `insufficient_content`, no `include`.

## Política

Antes de usar esta vista para una nueva clasificación, el contrato downstream
debe referenciarla explícitamente y conservar `dedupe_manifest_v2.jsonl` y
`dedupe_origin_events.jsonl` como historial. Los candidatos de fingerprint no
excluyen documentos automáticamente.
