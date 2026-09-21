# Implementación Codex — enrichment v3.2

Fecha: 2026-09-16  
Rol: `builder`  
Modelo: `gpt-5.6-luna`  
API: no se realizaron llamadas nuevas.

## Problemas corregidos

1. El ETL v3.1 descartaba `proyectos_mencionados`, `proyecto_asociado` y
   varios campos analíticos. Se creó `Trabajo/scripts/build_enrichment_tables_v3_2.py`.
2. El contrato usaba nombres v3 para contenido ya v3.2. Se crearon rutas
   explícitas para prompt, schema y record schema v3.2; el runner de piloto y
   producción ahora las importa.
3. La regla de proyecto focal podía confundir un proyecto contextual con el
   proyecto del documento. El prompt v3.2 ahora permite
   `nombre_proyecto=""` con `proyectos_mencionados[]` no vacío.
4. Se añadió un gate determinista de integridad referencial y semántica:
   asociaciones deben pertenecer a `proyectos_mencionados`; una revisión
   `ninguno` no puede traer campos/motivo; una cita/evidencia verificada no
   puede estar vacía. Las violaciones se cuarentenan en el runner.
5. Se detectó que el piloto heredado no tenía `record_schema_sha256`. Se
   agregó como campo requerido para nuevos registros y se hizo backfill
   determinista de los 10 existentes, preservando sus hashes históricos de
   prompt/schema; se dejó copia `.pre_backfill.jsonl`.

## Artefactos

- Contrato: `Trabajo/config/enrichment_contract_v3_2.yaml`.
- Prompt/schema/record schema: `Trabajo/prompts/enrichment_system_v3_2.md`,
  `Trabajo/config/enrichment_schema_v3_2.json`,
  `Trabajo/config/enrichment_record_schema_v3_2.json`.
- Runner: `Trabajo/scripts/enrich_case_v3.py` y
  `Trabajo/scripts/enrich_case_v3_production.py`.
- ETL: `Trabajo/scripts/build_enrichment_tables_v3_2.py`.
- Congelamiento: `Auditoria/enriquecimiento_v3_2_934/universo_congelado_934.json`.

## Verificación

- Prueba focalizada de contrato/ETL: **4/4**.
- Suite completa del proyecto: **82/82**.
- JSON/YAML válidos y `py_compile` sin errores.
- Preflight `--dry-run --limit 20`: 934/934 `include` `temporal_v2`,
  934/934 fulltext, 0 faltantes, `universe_freeze_ok=true`, 934 pendientes.
  Estimación actual desde el piloto: USD 21,86 para los 934 y USD 0,47 para
  un lote de 20; son estimaciones, no gasto realizado.
- ETL sobre piloto real: `Auditoria/integracion_v1/warehouse_v3_2_piloto10.sqlite`:
  10 documentos, 17 proyectos, 102 actores, 41 instituciones, 35 eventos,
  184 evidencias, 0 unmatched, 0 duplicados y 0 asociaciones inválidas.
- `warehouse_v1.sqlite` permanece intacto (38 eventos históricos).
- FARO quality gate: score 100.

## No ejecutado

La corrida pagada de producción sobre los 934 documentos no fue lanzada. Sigue
requiriendo autorización explícita (`--confirm-production-run`) y revisión del
gate humano vigente. La segunda pasada selectiva para documentos con
`actores_posiblemente_truncados=true` queda como pendiente posterior, no se
resuelve elevando globalmente el máximo de actores.
