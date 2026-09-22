# Metodología

Cómo un artículo de prensa se convierte en un nodo verificable de la red actor↔conflicto, qué
garantías tiene cada paso, y qué queda deliberadamente sin resolver.

## Las seis capas

```
document → evidence → project → case → conflict → actor
```

1. **document** — el corpus scrapeado (prensa, actas municipales, fuentes DS19), con lineage
   (`url`, `fuente`, `fecha`, hash) para cada registro.
2. **evidence** — citas extraídas por un LLM, cada una marcada como verificada solo si es substring
   literal de la fuente. Una cita no verificada nunca cuenta como evidencia confirmada en las capas
   siguientes.
3. **project** — identidad física de un desarrollo/proyecto. Dos menciones se fusionan en el mismo
   `project_id` **solo** si su nombre normalizado es idéntico. Nunca por similitud parcial entre
   documentos distintos.
4. **case** — agrupa `project_id` relacionados (mismo desarrollo, distinta fase o variante de
   escritura) cuando hay evidencia verificada de que son el mismo desarrollo, nunca solo por
   coincidencia de substring — esos pares quedan en una cola de revisión (`project_review_queue`)
   con la razón registrada.
5. **conflict** — la unidad sociológica de disputa, separada de la identidad física de proyecto. Un
   conflicto puede agrupar 2+ `case_id` cuando hay evidencia de que es el mismo litigio (ej. un
   cementerio y el trazado de un teleférico sobre su terreno, cubiertos por proyectos distintos).
   `conflict_id` es una función many-to-one de `case_id`: nunca ocurre lo inverso.
6. **actor** — identidad de actor institucional, resuelta de forma conservadora: solo 6 instituciones
   nacionales sin ambigüedad de jurisdicción (expansión literal de sigla o verificación directa
   contra citas reales del corpus).

## Gate documental: cuándo un documento cuenta como evidencia de un conflicto

No toda mención de un conflicto en un documento es evidencia de que ese documento trata ese
conflicto como protagonista. Cada vínculo `document ↔ conflict` tiene un rol:

- `focal` / `co_focal` — el documento trata este conflicto como asunto principal.
- `contextual_mention` — lo menciona como contexto de otro asunto.
- `panoramic_mention` — lo menciona dentro de un panorama de varios casos.
- `mentioned_unreviewed` — mención mecánica sin revisión.

Las vistas seguras (`document_conflict_case_safe` y las vistas `actor_event_project_link_*_safe`)
exigen `role IN ('focal', 'co_focal')`. Las vistas `_extended` agregan `contextual_mention` como
análisis de sensibilidad. Nunca se usa `mentioned_unreviewed` ni `panoramic_mention` como evidencia
de que un conflicto es real.

## Respaldo documental de proyecto (Fix 1A)

La vista conservadora exige una cita `objeto` verificada cuyo texto contenga el nombre
normalizado del proyecto (`exact_substring_v1`) y que provenga de un documento con al menos una
mención incluida. La tabla `conflict_evidence_backing` conserva la cadena completa hasta la cita.

El esquema actual no vincula afirmativamente cada proyecto con un `case_mention` específico dentro
de documentos que contienen varios casos. Por eso el respaldo se etiqueta con
`backing_scope=document_level_case_mention_without_project_link` y se marca
`ambiguous_multi_case_document=1` cuando hay más de una mención incluida con evidencia de objeto.
Esto es una señal de calidad y no una adjudicación directa ni una prueba de que los demás proyectos
del documento sean parte del mismo conflicto. La cobertura por conflicto se informa como `total`,
`parcial` o `ninguna`; la ausencia de respaldo no equivale a falsedad.

## Por qué existe el gate: lo que encontró la validación

Una muestra aleatoria de 50 documentos enriquecidos, revisada caso por caso, encontró **24% de
error grave** — documentos que mezclaban más de un conflicto real bajo una sola unidad de análisis.
Ese hallazgo, no una preferencia de diseño abstracta, es la razón por la que existe la capa
`conflict` separada de `project`/`case`, y por la que el gate documental exige rol focal/co-focal en
vez de aceptar cualquier mención. El detalle completo está en `audit/data_quality_report.md`.

## Qué queda deliberadamente sin resolver

- **Homónimos entre proyectos**: solo se fusionan con evidencia verificada (comuna, dirección,
  actores). Un nombre compartido nunca basta.
- **Identidad de actor más allá de las 6 instituciones nacionales**: Cortes de Apelaciones y
  Tribunales Ambientales sin sede identificada (17 y 3 en Chile respectivamente), Direcciones de
  Obras Municipales sin comuna, SEREMIs regionales, y personas naturales — todos con ambigüedad de
  jurisdicción real, no negligencia.
- **Trayectorias temporales de un mismo territorio**: un caso registrado en `conflict_relation`
  como `pending_human_decision` (un mismo actor colectivo y territorio sostiene dos episodios
  contenciosos separados por décadas) queda sin fusionar hasta que un análisis de trayectorias lo
  resuelva mejor que la sola estructura del dato.

## Cómo se audita el uso de LLMs

Cada extracción pasa por un contrato de esquema versionado con hash-pinning de prompt/schema (para
detectar cambios silenciosos entre corridas), preflight antes de gastar presupuesto, y ejecución
incremental con recuperación segura ante caídas. Las citas se verifican como substring literal de
la fuente antes de aceptarse como evidencia confirmada.

## Validación y estado

Ver `audit/validation_summary.json` para los números exactos (muestra de validación, identidad
resuelta, integridad de la base) y `audit/data_quality_report.md` para la síntesis narrativa de qué
se encontró y qué cambió como consecuencia. Las conclusiones analíticas de fondo (más allá de esta
infraestructura de identidad, que sí está verificada y cerrada) siguen pendientes de los arcos
sustantivos de análisis — ver `docs/arcos/plan_arcos_analiticos.md`.
