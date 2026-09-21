# Guía técnica del repositorio

Ver primero [README.md](README.md) para una descripción general del proyecto.

## Qué es

Análisis de conflictividad inmobiliaria/urbana en las 32 comunas de la Provincia de Santiago,
2014-2026. Cubre DS19 (Programa de Integración Social y Territorial, MINVU) y también
densidad/altura, patrimonio, especulación y legalidad administrativa.

## Estructura

- `Fuentes/` — datos crudos scrapeados (prensa, actas municipales, DS19) y fuentes externas de
  referencia. Ver [DATA_NOTICE.md](DATA_NOTICE.md) antes de redistribuir cualquier archivo de aquí.
- `Trabajo/` — scripts, prompts, configuración y contratos de pipeline.
- `Productos/` — dashboards, informes y entregables.
- `Auditoria/` — clasificaciones, enriquecimiento, validaciones humanas y matrices de evidencia.
- `docs/` — planes de arcos analíticos y documentación de arquitectura.

## Genealogía técnica del pipeline

1. **Descubrimiento y scraping** (`Trabajo/scripts/brightdata_discovery.py`,
   `external_source_acquisition_v1.py`) → `Fuentes/fulltext_v2/`.
2. **Clasificación** (familia `classify_v5*.py`) sobre el corpus completo (3.884 documentos) →
   tablas `case_mention` / `entity` / `event` (capa de clasificación).
3. **Enriquecimiento** (familia `enrich_case*.py`, contrato vigente en
   `Trabajo/config/enrichment_contract_v3_2.yaml`) sobre el subconjunto incluido (934 documentos) →
   tablas `enrichment_*_v3_2`.
4. **Puente documento → proyecto/caso** (`build_case_project_bridge.py`,
   `resolve_project_review_queue.py`) → identidad de proyecto y caso resuelta.
5. **Capa CONFLICT** (`build_conflict_registry_v1.py`) → unidad sociológica de disputa, separada de
   la identidad física/histórica de proyecto.
6. **Resolución de identidad de actor** (`build_actor_registry_v1.py`) → instituciones nacionales
   fusionadas de forma conservadora.
7. **Red actor↔conflicto** (`build_actor_conflict_network_v1.py`,
   `build_actor_registry_network_impact_v1.py`).

Cada script tiene su test correspondiente en `Trabajo/tests/`. Ver
[docs/arcos/plan_arcos_analiticos.md](docs/arcos/plan_arcos_analiticos.md) para el plan de análisis
sobre esta base, y
[`Auditoria/integracion_v1/entrega_dario_2026-09-18/ENTREGA_DARIO_red_actor_conflict.md`](Auditoria/integracion_v1/entrega_dario_2026-09-18/ENTREGA_DARIO_red_actor_conflict.md)
para el detalle de tablas/vistas listo para análisis.

## Correr los tests

```bash
git lfs pull
python -m venv .venv
source .venv/bin/activate  # o .venv\Scripts\activate en Windows
pip install -e .[dev]
pytest
```

Algunos tests dependen de `Auditoria/integracion_v1/warehouse_v3_2_bridge.sqlite` (vía Git LFS) y se
saltan automáticamente si el archivo no está disponible en el entorno.
