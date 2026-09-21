# Arquitectura del pipeline

```text
FUENTE (prensa, actas, DS19)
    │  scraping (brightdata_discovery.py, external_source_acquisition_v1.py)
    ▼
DOCUMENTO (3.884 documentos, con lineage y hash de origen)
    │  clasificación LLM (classify_v5*.py)
    ▼
EVIDENCIA (citas verificadas como substring literal de la fuente)
    │  enriquecimiento LLM sobre el subconjunto incluido (enrich_case_v3*.py, 934 documentos)
    ▼
MENCIÓN DE PROYECTO (nombre de proyecto tal como aparece en el texto)
    │  resolución de identidad (build_case_project_bridge.py + resolve_project_review_queue.py)
    ▼
PROYECTO / CASO (990 proyectos → 862 casos; homónimos y variantes de escritura fusionados con
    │              evidencia revisada, nunca por coincidencia de substring)
    │  agrupación sociológica (build_conflict_registry_v1.py)
    ▼
CONFLICTO (839 conflictos; puede agrupar 2+ casos cuando corresponde al mismo litigio,
    │        nunca al revés — conflict_id es una función many-to-one de case_id)
    │  resolución de identidad de actor (build_actor_registry_v1.py)
    ▼
ACTOR / ENTIDAD (institución nacional consolidada cuando la evidencia lo permite;
                  el resto conserva su identidad textual sin resolver)
```

## Principios de diseño

- **Cada capa es una decisión de identidad separada.** Un documento, un proyecto físico y un
  conflicto sociológico no son la misma unidad — fusionarlos prematuramente pierde información
  (ej. un mismo proyecto con dos litigios distintos, o un mismo conflicto que involucra varios
  proyectos).
- **La fusión siempre requiere evidencia, nunca solo coincidencia de nombre.** Homónimos conocidos
  (ej. dos proyectos distintos llamados "El Colorado", uno un centro de esquí y otro una vivienda
  social) están explícitamente protegidos contra fusión automática.
- **Vistas `safe` vs. `extended`.** Cada capa expone una vista conservadora (evidencia con rol
  focal/co-focal, revisada) y una extendida (agrega menciones contextuales) — el análisis parte de
  la conservadora y usa la extendida solo como prueba de sensibilidad.
- **Todo cambio de fusión/separación queda en una cola de revisión con razón explícita**, no en un
  script que decide en silencio.
