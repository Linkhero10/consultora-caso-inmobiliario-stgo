# Adjudicación de conflictos duplicados — instrucciones

NO puedes invocar otros agentes ni subagentes; trabaja tú solo. Lee solo el archivo de parejas que se te asigna
(`duplicate_pairs_<k>.json`) y los textos completos que cada documento indica en `content_file` (JSON con `text`).
No abras `data/warehouse.sqlite`, `audit/`, `config/` ni `src/`.

## Qué es una pareja
Cada pareja son dos *conflictos* (`a` y `b`) que el sistema trata como distintos y que podrían ser **la misma disputa real**
escrita con nombres distintos o partida en piezas. `projects` son los proyectos de cada conflicto, `documents` sus documentos
(rol focal/co_focal = trata el conflicto como asunto principal; el resto solo lo menciona) y `citas_objeto` citas ya extraídas.

## Qué debes decidir (`decision`)
- `mismo_conflicto`: es la MISMA disputa del mundo real. Debe cumplirse al menos una:
  1. el mismo proyecto, sitio, permiso o fallo con nombres distintos (alias, dirección, nombre histórico y actual);
  2. un conflicto es componente, etapa, lote o parte del otro **dentro de la misma controversia** (mismo reclamo, mismos actores
     o el mismo litigio/proceso), de modo que un analista querría verlos como uno solo;
  3. varios edificios o lotes tratados por los documentos como **un solo** litigio o reclamo (p. ej. un mismo fallo sobre todos).
- `distintos`: son disputas distintas aunque compartan artículo, comuna, inmobiliaria, tribunal o autoridad, o aparezcan juntos
  en una lista. Compartir un documento NO basta. Compartir una inmobiliaria NO basta.
- `no_decidible`: los textos no permiten saber. Ante la duda entre `mismo_conflicto` y `distintos`, elige `distintos` o `no_decidible`
  (una fusión errónea contamina el análisis; no fusionar solo pierde precisión).

## Evidencia (obligatoria si decides `mismo_conflicto`)
`evidencia`: lista de `{"lado": "a"|"b"|"ambos", "document_id": "...", "cita": "..."}` con **citas literales copiadas del texto
fuente** (verifica que la cadena exista tal cual en el texto). Necesitas al menos una cita que muestre la identidad: un pasaje que
nombre ambos, o dos pasajes (uno por lado) que describan el mismo objeto, sitio o fallo. Si no puedes citarlo, no es `mismo_conflicto`.

## Salida
Escribe UN archivo `intermediate/review_samples/duplicate_decisions_<k>.json`:

```json
{"revisor": "<tu modelo>", "decisions": [
  {"pair_id": "P000", "decision": "mismo_conflicto|distintos|no_decidible", "evidencia": [], "motivo": "una o dos frases"}
]}
```
Una decisión por cada `pair_id` de tu archivo. Guarda de forma incremental cada 10 parejas. Al terminar responde solo con el recuento por
decisión y las parejas que no pudiste evaluar. No hagas otras escrituras.
