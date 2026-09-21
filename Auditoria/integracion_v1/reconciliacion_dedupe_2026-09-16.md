# Reconciliación de dedupe previa a las tablas de entidades (2026-09-16)

## Resumen

El `dedupe_manifest_v2.jsonl` histórico (10.526 filas) quedó desactualizado
respecto al estado real de `Fuentes/fulltext_v2/content/` porque
`dedupe_fulltext.py` trata `not_eligible_for_dedupe` como un evento terminal
(`already_eventful_urls()`, `dedupe_fulltext.py:78-101`) — un rerun normal
del script no reabre esos registros aunque su contenido haya cambiado
después. 15 documentos pasaron de `not_eligible` a tener texto suficiente
(`char_count >= 200`) tras reextracciones posteriores, y 4 de esos 15 ya
habían sido clasificados con `classify_v5_2_3.py` sin que el dedupe lo
supiera.

Luna (Codex) construyó una reconciliación independiente desde el estado
actual de `content/` (sin depender del log de eventos viejo):
`Fuentes/fulltext_v2/dedupe_manifest_reconciled_20260916_122759_683890.jsonl`,
reporte en
`Auditoria/dedupe_reconciliation/dedupe_reconciliation_20260916_122759_683890.json`.
Verificado por Claude, cifras exactas:

| tipo | manifiesto histórico | manifiesto reconciliado |
|---|---|---|
| canonico | 5.408 | 5.421 |
| duplicado_exacto | 300 | 301 |
| candidato_revision | 27 | 31 |
| not_eligible_for_dedupe | 4.791 | 4.776 |

## Delta sobre el corpus clasificado

- 3.885 documentos clasificados con `classify_v5_2_3.py`.
- 3.884 entran al corpus canónico reconciliado (`build_corpus_canonico_v1.py`).
- 1 queda excluido: `https://revista.ceacgr.cl/revista/issue/download/vol4/VOLUMEN%204`,
  detectado como `duplicado_exacto` del par CEACGR (mismo `content_sha256`
  que `https://revista.ceacgr.cl/index.php/ceacgr` una vez ambas URLs
  tuvieron contenido real). Ambas URLs del par tienen
  `decision_documento == "insufficient_content"` en `classifications.jsonl`
  — el duplicado no infló ningún caso `include`, pero sí fue clasificado (y
  pagado) dos veces.

## Qué NO se tocó

`dedupe_origin_events.jsonl`, `dedupe_manifest_v2.jsonl` y
`classifications.jsonl` quedan intactos como historial. El corpus canónico
vive en un artefacto nuevo aparte
(`Auditoria/integracion_v1/corpus_canonico_v1.json`), con hash y ruta del
manifiesto reconciliado usado como insumo, para trazabilidad completa.

## Próxima vez que se reabra la reconciliación

Si se reextraen más documentos en el futuro, repetir el mismo patrón de
Luna (reconciliación independiente desde `content/` actual con su propio
`run_id`), nunca editar el log de eventos viejo ni el manifiesto histórico.
