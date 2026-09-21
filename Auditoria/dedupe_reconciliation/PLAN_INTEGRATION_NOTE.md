# Correcciones necesarias al plan `twinkling-hatching-meteor.md`

La Fase A0 del plan debe consumir la vista reconciliada vigente y no volver a
ejecutar `dedupe_fulltext.py` "tal cual" como si el log histórico pudiera
reabrirse solo. El evento existente para la URL CEACGR reparada es únicamente
`not_eligible`; por tanto, `already_eventful_urls()` la considera finalizada y
el rerun original no la detecta automáticamente.

## Sustitución recomendada

1. Usar como entrada autorizada el último
   `Fuentes/fulltext_v2/dedupe_manifest_reconciled_*.jsonl` y su reporte
   compañero en `Auditoria/dedupe_reconciliation/`.
2. Construir `corpus_canonico_v1.json` filtrando `tipo == "canonico"` y por
   URLs presentes en `classifications.jsonl`.
3. Mantener intactos `dedupe_origin_events.jsonl`, `dedupe_manifest_v2.jsonl`
   y `classifications.jsonl`; son historial, no una vista que deba editarse
   para cerrar el stage.

## Conteos verificados para este corpus

- 10.498 contenidos actuales.
- 5.421 canónicos, 301 duplicados exactos, 4.776 no elegibles y 31 candidatos
  por fingerprint corto.
- 3.884 URLs clasificadas entran al corpus canónico; una queda fuera por ser
  el duplicado exacto CEACGR. El duplicado era `insufficient_content`, no
  `include`.
- Los 15 `not_eligible` históricos con texto recuperado están enumerados en
  el reporte de reconciliación; solo uno de ellos es el duplicado exacto ya
  clasificado y los demás son canónicos actuales.

La lista de archivos del plan debe quitar la edición de los dos manifests
históricos y referenciar explícitamente el manifest reconciliado como insumo
de la Fase A0.
