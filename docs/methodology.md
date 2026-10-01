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

## Respaldo de evidencia de un conflicto

Durante la extracción, el modelo recibe la lista numerada de las `case_mention` que la clasificación ya decidió
para el documento y declara, para cada proyecto mencionado, a cuál pertenece (`case_mention_index`) o `null` si
ninguna lo tiene como objeto. El pipeline valida el rango y conserva el valor crudo si lo limpia. Un conflicto
cuenta como respaldado si alguna mención de sus proyectos apunta a una `case_mention` incluida con al menos una
cita de `objeto` verificada (subcadena literal del texto). La tabla `conflict_evidence_backing` conserva la cadena
completa hasta la cita. La cobertura por conflicto se informa como `total`, `parcial` o `ninguna`; la ausencia de
respaldo no equivale a falsedad. Una `case_mention` dejada `uncertain`/`exclude` por la clasificación puede
respaldar solo por adjudicación explícita (`config/case_mention_eligibility_adjudications.json`), visible en
`match_method`. La asociación proyecto → mención se validó con dos rondas de revisión ciega independiente
(0 fabricaciones en 809 evaluaciones).

## Geografía de menciones de proyecto

`project_mention_geography` resuelve territorio en la unidad de la mención:
`project_mention → case_mention → comuna`. Se acepta el vínculo `direct` cuando
el índice propio de la mención apunta a una `case_mention` incluida con comuna
resuelta. Compartir grupo de duplicados, incluso uno sin decisiones mixtas,
no demuestra por sí solo identidad ni permite transferir geografía: sin una
adjudicación explícita, la mención queda como `ambiguous_duplicate_group` sin
comuna. Una adjudicación humana explícita puede producir
`via_reviewed_duplicate_group`, limitado a la identidad geográfica del
proyecto. No altera `include/exclude`, no transfiere focalidad y no atribuye
conflicto ni evidencia entre menciones. El dashboard cuenta únicamente los
métodos `direct` y `via_reviewed_duplicate_group`; las filas ambiguas o sin
resolución no se usan para inventar ubicación. El reporte de auditoría registra
los hashes del warehouse de entrada/salida, del código y de la configuración
de adjudicaciones.

## Capa de contexto social fino: manzana censal (Censo 2024)

El mapa por comuna (32 unidades) puede activar una capa opcional de manzanas censales del Censo
2024 (INE, 46.864 manzanas), la unidad geográfica más fina disponible, con población, hogares y
viviendas particulares por manzana. **Esta capa es solo contexto socioeconómico de fondo, no
ubica conflictos**: se investigó explícitamente si el warehouse permite ese nivel de precisión
(join espacial contra las coordenadas ya resueltas en `geocoded_location`) y la respuesta es no —
las únicas coordenadas resueltas y vinculadas a un conflicto están marcadas
`relation_type='contextual_location'` (un lugar mencionado en el documento, no el sitio
determinado del conflicto), y tratarlas como ubicación exacta habría violado el mismo principio
("ausencia de resolución > relación inventada") que ya rige el resto del pipeline. Los conflictos
siguen contándose y coloreándose únicamente a nivel de comuna.

## Por qué existe el gate

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

Cada extracción pasa por un contrato de esquema con hash de prompt y esquema registrado en cada registro, un
ensayo previo sin gasto, ejecución por olas con tope de costo y recuperación segura ante caídas. Las citas se
verifican como subcadena literal de la fuente antes de aceptarse; una respuesta pagada que no cumple su contrato
se cuarentena, nunca se pierde. Ver [estándares](standards.md) (E2, E3, E7, E14).

## Decisiones humanas

Toda decisión (fusionar o separar proyectos, elegir una mención, corregir una unidad de caso) es un dato
versionado en `config/`, llaveado por identificadores estables y con su evidencia; se valida al cargar y nunca se
transfiere por parecido de nombres (E5).

## Validación y estado

`audit/validation_summary.json` reúne las validaciones con su método, tamaño y límites, y
`audit/data_quality_report.md` la síntesis de hallazgos. Las cifras vigentes del producto están en el bloque
generado de [START HERE](../START_HERE.md). Las conclusiones analíticas de fondo siguen pendientes de los arcos
(ver `docs/arcos/plan_arcos_analiticos.md`).
