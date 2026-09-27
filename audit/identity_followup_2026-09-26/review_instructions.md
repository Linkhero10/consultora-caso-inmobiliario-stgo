# Revisión de identidad y migración v3.2→v3.3

## Qué contiene este paquete

- `identity_review_bundle.json`: las 68 parejas que siguen abiertas en `project_review_queue`, con IDs, nombres, todas las URLs de origen disponibles por proyecto, menciones estructuradas explícitamente enlazadas y estado actual. Es una exportación de solo lectura del warehouse.
- `migration_review_original.json` y `migration_review_original_summary.md`: el expediente de revisión anterior, incluidos los 119 documentos y sus adjudicaciones por mención. También contiene una opinión preliminar para las 68 parejas abiertas, pero ninguna de esas 68 filas trae URL ni evidencia externa (`urls=0/68`, `external_evidence=0/68`); no la trates como adjudicación verificada.
- `migration_drift_cases.json`: reconciliación reproducible de los cuatro registros etiquetados como `omisión respaldada` en la dirección v3.2→v3.3.
- `typed_project_relation.json`: relación `Ciudad Parque Bicentenario → Plan Maestro`, materializada sin fusionar identidades.

El warehouse usado para generar el bundle tiene SHA-256 `378bf7d7686d676dfb1e08cb5c141a2e5bea29b943ad0de6ef4f58d0900c09db`. El bundle registra también ese hash y el HEAD local que lo produjo.

## Trabajo solicitado

### A. Adjudicar las 68 parejas abiertas, una por una

Para cada `pair_id`, inspecciona las fuentes adjuntas a ambos `project_id`; no basta con leer el nombre ni la razón de la cola. **Haz primero una adjudicación nueva basada en las fuentes, sin consultar `relation_review.unresolved_pairs` del expediente anterior.** Congela esa pasada antes de comparar la recomendación previa. Cuando las URLs no basten, busca fuentes oficiales o primarias. Comprueba en cada lado identidad, geografía, período, desarrollador, etapa y homónimos.

Devuelve una sola conclusión por pareja, con una de estas clases: `same_identity`, `parent_component_phase`, `related_plan_or_instrument`, `distinct_entities` o `unresolved`. Distingue la clase de relación de la acción de datos: solo `same_identity` puede recomendar alias/merge; si lo recomiendas, elige explícitamente un `canonical_project_id` y cita evidencia para ambos IDs. No transfieras una decisión histórica solo porque los nombres se parezcan o compartan `case_id`.

Incluye para cada lado al menos una URL verificable, una cita corta exacta o localizador, la evidencia contraria relevante, confianza y razón. Después registra si coincide con la recomendación preliminar y por qué; discrepancia no significa automáticamente que una de las dos sea correcta. Si no puedes demostrarlo, devuelve `unresolved`; no rellenes el resultado para completar el conteo.

La pareja Google/Cerrillos ya fue promovida en producción mediante la decisión explícita del usuario y el commit `a68aab02ac283443c5a2ae6ff22c458418134145`; aparece como contexto en `migration_review_original.json`, no como una de las 68 filas abiertas. No reviertas esa decisión dentro de esta revisión.

### B. Revisar las 69 adjudicaciones de deriva

En `migration_review_original.json`, recorre todas las adjudicaciones que tienen `classification = "omisión respaldada"`, tanto en `drift_review.focal_priority_89` como en `drift_review.nonfocal_frozen_30`. Son 69 en total: 65 filas del lado v3.3 y 4 del lado v3.2. El rótulo es direccional y no equivale a 69 errores netos. Inspecciona primero el texto fuente y los registros v3.2/v3.3; no uses la etiqueta anterior como conclusión.

Para cada fila, verifica el objeto y su papel en el caso contra la fuente original. Clasifica si es omisión real, compresión legítima de granularidad, alias, componente/etapa, mención contextual, problema de atribución, error de la adjudicación previa o no verificable. Registra `document_id`, versión, nombre literal, URL, evidencia del texto, contraparte v3.2/v3.3 y recomendación aislada. Evita extrapolar un caso a los demás.

Los cuatro casos v3.2 están detallados además en `migration_drift_cases.json`. Tres son componentes descritos en una noticia sobre Línea 7; la versión v3.3 conserva un nombre paraguas y deja su índice de `case_mention` nulo. El cuarto es la mención de Ukamau que aparece en v3.2 pero no en la lista de proyectos v3.3. Son candidatos que requieren adjudicación; no están promovidos.

### C. Verificar la relación tipada

Revisa en `typed_project_relation.json` si `has_plan` describe correctamente el vínculo de Ciudad Parque Bicentenario con su Plan Maestro, usando el documento oficial y el localizador incluidos. La relación conserva ambos `project_id` y `case_id`; no la conviertas en alias ni en una fusión. Si la evidencia respalda otra relación tipada, explica la diferencia y cita la fuente.

## Entrega esperada

Devuelve dos artefactos separados: (1) JSON con exactamente 68 filas de parejas y comparación explícita con la recomendación preliminar; (2) JSON con exactamente 69 adjudicaciones de deriva y comparación con la etiqueta previa; además, una síntesis breve de hallazgos y límites. Añade URLs y citas/localizadores, no solo categorías o consenso. Declara expresamente cualquier caso inaccesible o no verificable.

Esta es una revisión metodológica. **No cambies el warehouse, la cola, IDs, aliases, relaciones ni el dashboard.** Ningún resultado se promoverá automáticamente; la aplicación será una decisión posterior y versionada.
