# Plan paso a paso — 3 arcos analíticos

Base de datos disponible para los tres: `data/warehouse.sqlite`
(990 `project_id` → 862 `case_id`, 839 conflictos, ~17.200 vínculos actor/institución/evento→proyecto).
Ver el [README](../../README.md) y [`docs/methodology.md`](../methodology.md) para el detalle de
capas, tablas y vistas.

Bloqueante común antes de sacar conclusiones publicables: la validación muestral del enrichment
(ver [`audit/validation_summary.json`](../../audit/validation_summary.json), n=50: 21 ok, 17 error
menor, 12 error grave) ya identificó errores reales de unidad de caso, motivando el gate
documental descrito en la metodología. Una muestra más grande sobre el corpus completo sigue
pendiente. Los tres arcos pueden empezar a construir metodología y código sobre los datos ya
existentes, pero ningún hallazgo debería publicarse sin ampliar esa validación.

Los tres arcos son estructuralmente paralelos — cada uno parte de una tabla distinta del mismo
warehouse y ninguno necesita el resultado de otro para arrancar.

---

## Arco Darío — red de actores, SNA y ERGM

**Pregunta que responde**: ¿qué estructura tiene la red de actores del conflicto inmobiliario en
Santiago — quién son los nodos centrales/puentes, hay coaliciones, y qué predice que dos actores
coincidan en el mismo caso?

### Paso a paso

1. **Construir el grafo desde el warehouse, no desde cero.** Nodos = actores/instituciones
   (`enrichment_actor` + `enrichment_institution` + `actor_second_pass_v2` vía
   `actor_event_project_link`), aristas = co-ocurrencia en el mismo conflicto (`conflict_id`, no
   `project_id` fino, para no fragmentar artificialmente el mismo caso real en variantes de
   redacción). Usar `resolution_status` para decidir qué vínculos entran con certeza
   (`resolved_explicit`, `resolved_single_project`) vs. cuáles serían un supuesto adicional
   (`unresolved_ambiguous` — un actor de un documento con 2+ proyectos, sin saber a cuál
   corresponde: si se incluye, debe marcarse con menor peso/confianza, nunca tratarse igual que un
   vínculo resuelto).
2. **Nivel de nodo**: ya existe una resolución de identidad conservadora para 6 instituciones
   nacionales (`actor_registry`/`actor_alias`, ver README) — el resto de los actores no está
   deduplicado entre documentos. Antes de correr métricas de centralidad, decidir si conviene ampliar
   esa resolución a otros actores recurrentes o aceptar que la red sobrecuenta variantes de
   redacción no resueltas.
3. **Red base** con NetworkX (bipartita actor↔conflicto, proyectada a actor↔actor por co-membresía)
   y métricas descriptivas primero: distribución de grado, componente gigante, densidad — antes de
   asumir qué métricas de centralidad tienen sentido usar en esta red en particular.
4. **Detección de comunidades/coaliciones**: aplicar Louvain/Infomap sobre la proyección
   actor↔actor. Al interpretar una comunidad detectada como una coalición real, verificar contra los
   metadatos del caso (no asumir alineación automática entre estructura topológica y significado
   sustantivo).
5. **Dimensión temporal**: los eventos (`enrichment_event.fecha`) permiten construir la red
   como secuencia temporal, no solo agregada — un actor puede entrar/salir de un conflicto en
   momentos distintos. Útil si la pregunta de investigación es sobre velocidad de propagación o quién
   se involucra primero.
6. **ERGM**: no hay librería Python instalada en este repo. `ergm` maduro es de R
   (paquete `statnet`/`ergm`); en Python la opción es `PyERGM` o llamar R desde Python. Decidir si el
   ERGM es indispensable para el primer entregable o si las métricas descriptivas + comunidades ya
   bastan para una primera demo comercial.
7. Al construir cualquier salida de grafo grande, usar un patrón de 3 capas (resumen → reporte →
   detalle puntual) para no volcar el grafo completo en un solo informe.
8. **Producto concreto**: un "Stakeholder Intelligence Map" con métricas de centralidad/brokerage
   sobre un caso real del corpus.

## Arco Nicolás — institucionalidad y regulación

**Pregunta que responde**: ¿qué instrumento normativo/vía institucional se usó en cada caso, con qué
resultado, y hay patrones de captura regulatoria o vacíos normativos que se repiten?

### Paso a paso

1. **Partir de `enrichment_document`**: los campos `instrumento_norm`/`instrumento_raw`,
   `via_legal_norm`, `resultado_actuacion`, `institucion_decisora_segun_fuente` ya están extraídos por
   documento — no hace falta reprocesar nada, es agregación y análisis sobre lo que ya existe.
2. **Cruzar con el crosswalk** `case_mention_project_crosswalk` para conectar la capa de
   clasificación (`case_mention`, que cubre todo el corpus de 3.884 documentos, no solo los 934
   enriquecidos) con los `project_id`/`case_id` resueltos — da visibilidad sobre casos que quedaron
   fuera del enrichment profundo pero sí tienen señal de tipo de objeto/comuna.
3. **Nivel de granularidad regulatoria**: hay casos donde la decisión relevante ocurre a nivel de
   instrumento normativo secundario (ej. un seccional), más fino que el instrumento comunal completo
   — conviene diseñar la extracción para poder distinguir ese nivel, no solo el agregado comunal.
4. **Producto concreto**: contraste sistemático "lo que dice el expediente/instrumento vs. lo que
   dice la prensa" para una muestra de casos.

## Arco Christian — auditoría de evidencia (ESG)

**Pregunta que responde**: ¿qué tan verificable es la evidencia detrás de cada afirmación del corpus —
promesa declarativa vs. cumplimiento institucional vs. evidencia de desempeño real?

### Paso a paso

1. **Partir de las tablas de evidencia ya existentes**: `enrichment_evidence` (citas, con
   `verified` = si la cita es substring literal de la fuente), `claim`/`evidence` de la capa de
   clasificación (con `quote_role`). Estas tablas ya implementan el nivel más básico de auditoría de
   evidencia (¿la cita es real?) — el trabajo de este arco es la capa siguiente: clasificar cada
   afirmación en el eje Declarativo → Cumplimiento-Institucional → Evidencia de Desempeño y
   contrastar contra estándares reales (IRMA, GRI, SASB, DJSI, ISO).
2. **Usar `resolution_status` y los campos `*_verificada`** de las tablas v3.2 como insumo directo:
   cualquier afirmación con evidencia no verificada (cita no encontrada literal en la fuente) debería
   bajar automáticamente de nivel en este eje, no tratarse igual que una afirmación con evidencia
   confirmada.
3. **Producto concreto**: "ESG Disclosure Audit" — aplicar el marco de 2 ejes contra un caso real del
   corpus donde una inmobiliaria/empresa hizo declaraciones públicas de compromiso ("integración",
   "sustentabilidad") y contrastarlas con lo que el corpus documenta que realmente ocurrió.

## Puente de integración (ya construido, no es tarea nueva)

`src/build_projects.py` + `resolve_project_review.py` — ya corridos,
verificados, con tests. Los tres arcos consumen las mismas tablas (`project`,
`project_mention_resolved`, `actor_event_project_link`, `case_mention_project_crosswalk`,
`entity_actor_crosswalk`) ya materializadas en `warehouse.sqlite`. No hace falta que
cada arco construya su propio puente.

## Huecos de capacidad conocidos

- **ERGM**: sin librería Python instalada — decidir si usar R vía subprocess, una librería Python
  menos madura, o posponer el ERGM para una segunda iteración.
- **Derecho urbano/regulatorio chileno** y **ESG/estándares de sustentabilidad**: dependen del
  conocimiento propio de cada arco, no de infraestructura técnica adicional.
