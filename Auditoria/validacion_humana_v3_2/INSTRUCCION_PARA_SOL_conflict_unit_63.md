# Instrucción para Sol: clasificación de 63 documentos "caso_unico" con >1 case_id

## Contexto

La auditoría determinista (`audit_caso_unico_documents_multiple_case_ids.py`) encontró que 63/147 documentos de la vista conservadora, marcados `unidad_caso_tipo='caso_unico'`, tienen actores/instituciones que resuelven a más de 1 `project.case_id`.

Tu propio análisis identificó que esto no se resuelve con similitud de nombres: `project.case_id` resuelve identidad física/histórica de **proyecto**, no necesariamente la unidad de **conflicto** narrativo del documento. El heurístico anterior (Jaccard de nombres) solo hace triage lexical, no puede distinguir un conflicto genuinamente multi-proyecto de un alias sin fusionar.

## Archivo de trabajo (v2, ajustado tras tu segunda revisión)

`Auditoria/validacion_humana_v3_2/paquete_revision_conflict_unit_63_para_sol.json` — 63 documentos, cada uno con:
- Contexto ya extraído (`objeto_disputa_norm/raw`, `explicacion_tipo_conflicto`, `explicacion_actores`, `evidencia_objeto_disputa`).
- Cada grupo de `case_id` involucrado, con **todos** los `canonical_name` que agrupa (no solo el primero) y las citas verificadas de los actores/instituciones asociados a ese grupo. Cobertura de citas: **1096/1130 (97%)** — subió desde 785/1130 tras agregar el backfill de `actor_second_pass_v2` (0/316 → 311/316), que faltaba porque esa tabla no está copiada en el warehouse de la red; se cruzó por URL+nombre contra el jsonl de producción. Los 34 restantes sin cita quedan con `"cita": null` — verificar contra el documento original si el caso es dudoso.
- 4 campos para llenar: `clasificacion_sol`, `justificacion_sol`, `relaciones_case_groups_sol` (opcional), `conflict_id_sugerido`.

## Qué hacer

Para cada documento, clasificar en `clasificacion_sol` con **una letra** como clasificación **general** del documento:

- **A** — mismo conflicto, múltiples proyectos legítimos (ej. cementerio vs. trazado de teleférico).
- **B** — mismo proyecto/caso, alias no fusionado en la cola de revisión. **Definición estricta** (tu corrección): B es solo cuando los 2+ `case_id` deberían ser la MISMA identidad de proyecto ya existente (alias de escritura, nombre parcial, sigla). B **no** cubre proyecto matriz↔subproyecto, proyecto↔fase, complejo↔instalación específica, ni barrio↔intervención puntual dentro del barrio — esas son relaciones jerárquicas reales, no el mismo proyecto (repetiría el error que `PROJECT_PHASE` ya resolvió de otra forma).
- **C** — proyecto focal + proyecto contextual/secundario mencionado de paso.
- **D** — en realidad son conflictos distintos mezclados en un documento; `unidad_caso_tipo` debería reconsiderarse.
- **E** — incierto, evidencia insuficiente.

Llenar `justificacion_sol` con 1-2 frases.

**Para documentos con 3+ `case_id`** (13/63: 10 con 3, 2 con 4, 1 con 5) **donde una sola letra no describe bien la estructura** — ej. 2 de los grupos son el mismo conflicto y un 3ro es solo contextual — usar además `relaciones_case_groups_sol` para describir cada subconjunto por separado, en vez de forzar una categoría única que borre esa distinción:

```json
"relaciones_case_groups_sol": [
  {"case_ids": ["X", "Y"], "relacion": "mismo_conflicto"},
  {"case_ids": ["Z"], "relacion": "contextual"}
]
```

`project_relation` es un campo opcional dentro de cada entrada (`alias | parent_subproject | phase | distinct_conflict_objects | contextual | unknown`) para precisar la relación ontológica entre los proyectos, si aplica.

Si la categoría es **A**, `conflict_id_sugerido` es un **label provisional humano** (string libre) — **no** una semilla técnica: el mismo conflicto puede aparecer en varios documentos (ej. Emol + T13 sobre cementerio/teleférico) y no asumas que dos labels distintos para el mismo conflicto se van a unificar solos. El `conflict_id` real se generará después desde un registro determinista (`document_conflict_mentions` → clustering → `conflict_registry`), no desde este texto libre.

## Qué NO hacer

- No fusionar `project_id` ni `case_id` como efecto de esta clasificación — eso sigue siendo una decisión separada, explícita y auditada, igual que el resto de `project_review_queue`.
- No releer los 934 documentos completos ni rehacer enrichment — son solo estos 63 casos de frontera.
- No tratar `conflict_id_sugerido` como si ya fuera un identificador estable entre documentos.

## Al terminar

Devolver el mismo JSON con los campos llenos para los 63 documentos, más un resumen de conteos por categoría (A/B/C/D/E), la lista de documentos que usaron `relaciones_case_groups_sol`, y la lista de `conflict_id_sugerido` propuestos (marcados como provisionales), siguiendo el mismo formato de trazabilidad usado para la corrección de los 934.
