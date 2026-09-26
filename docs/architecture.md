# Arquitectura del pipeline

```text
FUENTE (prensa, actas, DS19)
    │  scraping (src/discovery.py, src/fulltext_acquisition.py)
    ▼
DOCUMENTO (con lineage y hash de origen)
    │  clasificación LLM (src/classify.py)
    ▼
EVIDENCIA (citas verificadas como substring literal de la fuente)
    │  enriquecimiento LLM sobre el subconjunto incluido (src/enrich.py)
    ▼
MENCIÓN DE PROYECTO (nombre de proyecto tal como aparece en el texto)
    │  resolución de identidad (src/build_projects.py + src/resolve_project_review.py)
    ▼
PROYECTO / CASO (homónimos y variantes de escritura fusionados solo con evidencia revisada,
    │              nunca por coincidencia de substring)
    │  agrupación sociológica (src/build_conflicts.py)
    ▼
CONFLICTO (puede agrupar 2+ casos cuando corresponde al mismo litigio, nunca al revés —
    │        conflict_id es una función many-to-one de case_id)
    │  resolución de identidad de actor (src/build_actor_registry.py)
    ▼
ACTOR / ENTIDAD (institución nacional consolidada cuando la evidencia lo permite;
    │              el resto conserva su identidad textual sin resolver)
    │  geografía derivada (src/build_geography.py, src/build_geography_manzana.py)
    ▼
COMUNA / MANZANA CENSAL (comuna resuelta de forma determinista por case_mention;
    │                     project_mention_geography vincula proyecto→case_mention→comuna
    │                     con el mismo mecanismo que Fix 1D usa para el respaldo de CONFLICT)
    │  publicación (src/build_dashboard.py, luego src/generate_run_manifest.py)
    ▼
DASHBOARD PÚBLICO (docs/index.html) + MANIFIESTO DE AUDITORÍA (audit/run_manifest.json)
```

Orden real de ejecución (ver README.md para el bloque de comandos completo):
`build_enrichment_tables.py` → `build_projects.py` → `resolve_project_review.py` →
`build_conflicts.py` → `build_actor_registry.py` → `build_actor_network.py` →
`apply_actor_registry_to_network.py` → `build_geography.py` → `build_geography_manzana.py` →
`build_dashboard.py` → `generate_run_manifest.py` (siempre el último paso que toca el warehouse).

Ver `docs/methodology.md` para los criterios de cada capa, el gate documental y qué queda
deliberadamente sin resolver.

## Principios de diseño

- **Cada capa es una decisión de identidad separada.** Un documento, un proyecto físico y un
  conflicto sociológico no son la misma unidad — fusionarlos prematuramente pierde información.
- **La fusión siempre requiere evidencia, nunca solo coincidencia de nombre.**
- **Vistas `_safe` vs. `_extended`.** Cada capa expone una vista conservadora (evidencia con rol
  focal/co-focal, revisada) y una extendida (agrega menciones contextuales) — el análisis parte de
  la conservadora y usa la extendida solo como prueba de sensibilidad.
- **Todo cambio de fusión/separación queda en una cola de revisión con razón explícita**
  (`project_review_queue`), nunca en un script que decide en silencio.
- **El respaldo documental no se confunde con un vínculo directo ausente.** `conflict_evidence_backing`
  registra coincidencias verificadas a nivel de documento/case_mention; cuando el documento contiene
  varios casos se conserva una señal explícita de ambigüedad y la cobertura del conflicto puede ser
  total, parcial o ninguna.

## Base de datos

`data/warehouse.sqlite` (SQLite, versionado con Git LFS). Tablas principales:

```text
document, evidence, claim              -- corpus y evidencia extraída
project, project_mention_resolved,
  project_phase, project_phase_link,
  project_review_queue                 -- identidad de proyecto
conflict, conflict_case,
  conflict_project, conflict_relation,
  conflict_episode, document_conflict  -- identidad de conflicto
actor_registry, actor_alias,
  actor_event_project_link             -- identidad de actor
enrichment_document, enrichment_actor,
  enrichment_institution, enrichment_event,
  enrichment_evidence,
  enrichment_project_mention           -- salida cruda del enriquecimiento LLM
territory, geocoded_location,
  geocoded_location_conflict,
  project_mention_geography,
  manzana_censal                       -- geografia: comuna (agregado) y manzana censal (contexto)
```

`manzana_censal` (Censo 2024, INE) es contexto social fino, no ubicación de conflictos -- ver
"Capa de contexto social fino" en `docs/methodology.md`. Su geometría vive en
`docs/manzanas_censales.geojson` (servido estático, cargado bajo demanda por el mapa), no en el
SQLite, para no duplicar ~20 MB de polígonos.

Vistas de referencia para construir la red actor↔conflicto:
`actor_event_project_link_conflict_safe` (conservadora) y `..._conflict_extended` (con menciones
contextuales, para análisis de sensibilidad).
