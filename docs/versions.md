# Qué hay en este repositorio (v1.0)

A partir de la versión 1.0, este repositorio conserva solo el pipeline que efectivamente corre
hoy — no todas las iteraciones que llevaron hasta acá. Las versiones intermedias, correcciones
puntuales y paquetes de auditoría siguen existiendo en el entorno de desarrollo local, pero no se
versionan públicamente.

## Clasificación (documento → include/exclude/uncertain)

- **Punto de entrada**: [`Trabajo/scripts/classify_v5_2_3.py`](../Trabajo/scripts/classify_v5_2_3.py),
  schema [`Trabajo/config/classification_schema_v5_2_3.json`](../Trabajo/config/classification_schema_v5_2_3.json),
  prompt [`Trabajo/prompts/classifier_system_v5_2_4.md`](../Trabajo/prompts/classifier_system_v5_2_4.md)
  (el script mantiene el nombre `v5_2_3` porque la lógica de esquema/gate no cambió; el texto del
  prompt sí se afinó una vez más después).
- **Nota técnica real, no genealogía**: `classify_v5_2_3.py` importa como módulo, y reutiliza
  funciones de, `classify_v5_2_2.py` → `classify_v5_2_1.py` → `classify_v5_2.py` →
  `classify_v5_1.py` → `classify_v5.py` → `classify_luna.py`. No son versiones históricas
  archivadas — son dependencias de código reales; el script vigente no funciona sin ellas. Se
  mantienen los 6 en el repositorio por esa razón, cada uno con su propio prompt/schema.

## Enriquecimiento (documento incluido → proyecto/actor/evento/evidencia)

- **Punto de entrada**: [`Trabajo/scripts/enrich_case_v3_production.py`](../Trabajo/scripts/enrich_case_v3_production.py),
  que envuelve a [`enrich_case_v3.py`](../Trabajo/scripts/enrich_case_v3.py) (dependencia real, no
  histórica) con locking de ejecución (`pipeline_lock.py`) para correr en producción de forma
  segura e incremental.
- Contrato: [`Trabajo/config/enrichment_contract_v3_2.yaml`](../Trabajo/config/enrichment_contract_v3_2.yaml),
  schema del registro: [`Trabajo/config/enrichment_record_schema_v3_2.json`](../Trabajo/config/enrichment_record_schema_v3_2.json)
  (generado por `build_enrichment_record_schema_v3_2.py`), schema de la respuesta del LLM:
  [`Trabajo/config/enrichment_schema_v3_2.json`](../Trabajo/config/enrichment_schema_v3_2.json)
  (generado por `build_enrichment_tables_v3_2.py`).

## Identidad de proyecto/caso/conflicto/actor

`build_case_project_bridge.py` → `resolve_project_review_queue.py` →
`build_conflict_registry_v1.py` → `build_actor_registry_v1.py` →
(`build_actor_network_comparison_v1.py` como utilidad compartida) →
`build_actor_conflict_network_v1.py` → `build_actor_registry_network_impact_v1.py`.

Esta capa es nueva y no reemplaza nada anterior — ver [`docs/architecture.md`](architecture.md)
para el diagrama completo.

## Scraping / adquisición

`brightdata_discovery.py` (descubrimiento) y `external_source_acquisition_v1.py` (extracción de
texto completo) — paso 1 del pipeline, documentado en `docs/architecture.md`.

## Warehouse SQLite

**Vigente**: `Auditoria/integracion_v1/warehouse_v3_2_bridge.sqlite` (el único versionado en este
repo, vía Git LFS). Otras copias/snapshots intermedios del warehouse no se versionan.
