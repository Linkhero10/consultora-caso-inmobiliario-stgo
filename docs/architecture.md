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
    │                     con el mismo vínculo que usa el respaldo de CONFLICT)
    │  publicación (src/build_dashboard.py, luego src/generate_run_manifest.py)
    ▼
DASHBOARD PÚBLICO (docs/index.html) + MANIFIESTO DE AUDITORÍA (audit/run_manifest.json)
```

Orden de ejecución: una sola definición, `src/rebuild.py` (`python src/rebuild.py --list`); README y una
prueba (`tests/test_rebuild.py`) lo verifican. `generate_run_manifest.py` es el último paso que toca el warehouse.

## Niveles de reproducibilidad

| Nivel | Qué es | Dónde vive | Cómo se recupera |
|---|---|---|---|
| Raíz externa | Corpus de terceros, clasificación y extracción por LLM | `intermediate/` y `Fuentes/` (no versionados) | Requiere el corpus y la API (costo real) |
| Raíz publicada | Tablas que esas etapas produjeron | `data/warehouse.sqlite` | `python src/extract_stage_warehouse.py --stage enrichment` |
| Derivado | Proyectos, casos, conflictos, actores, geografía, tablero | `data/`, `audit/`, `docs/` | `python src/rebuild.py` |
| Decisiones humanas | Identidad, unidad de caso, elegibilidad, correcciones de índice | `config/` (llaveadas por ID, con evidencia) | Versionadas |

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
- **Las relaciones tipadas no fusionan identidades.** `project_relation` registra, por
  ejemplo, que un desarrollo urbano tiene un plan maestro asociado; conserva ambos
  `project_id` y `case_id`, y exige URL, localizador y cita de fuente.
- **El vínculo se captura en la extracción.** El modelo declara a qué `case_mention` pertenece cada proyecto
  (`case_mention_index`); `conflict_evidence_backing` conserva la cadena hasta la cita literal y la cobertura del
  conflicto puede ser total, parcial o ninguna. Sin índice no hay respaldo.
- **Las decisiones humanas son datos, no código.** Viven en `config/`, llaveadas por identificador estable, con
  evidencia y validación al cargar.
- **Lo que se muestra se genera.** Cifras, manifiesto y orden de reconstrucción salen del warehouse o de una única
  definición; las pruebas fallan si se desincronizan. Ver [estándares](standards.md).

## Base de datos

`data/warehouse.sqlite` (SQLite, versionado con Git LFS). Tablas principales:

```text
document, evidence, claim              -- corpus y evidencia extraída
project, project_mention_resolved,
  project_phase, project_phase_link,
  project_relation_type, project_relation,
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
release_metadata                      -- versión de la release
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
