# Protocolo de validación ciega de conflictos

Plantilla de instrucciones para el revisor (humano o modelo). Pasos completos en [playbook](playbook.md), paso 16. Las rutas son las que produce `src/build_conflict_holdout.py --output-dir intermediate/review_samples/blind_validation`.


Eres un revisor independiente. NO puedes invocar otros agentes ni subagentes; trabaja tú solo.
No leas nada fuera de lo indicado aquí (en particular, no abras `data/warehouse.sqlite`, `audit/`, `config/` ni `src/`):
la revisión es ciega y cualquier consulta al warehouse la invalida. Solo puedes leer:
- `intermediate/review_samples/blind_validation/sample_main.json` (60 conflictos) y `sample_stress.json` (20 conflictos);
- los textos completos que cada documento indica en `content_file` (JSON con `text`).

## Qué es un registro
Un *conflicto* agrupa proyectos (`projects`) y documentos (`documents`, con `role`: focal/co_focal = trata el conflicto como asunto
principal; contextual_mention / panoramic_mention / mentioned_unreviewed = solo lo menciona). `evidence` son citas extraídas
(`quote_role`: objeto = qué se disputa; accion; geografica). `label` es el nombre que se mostraría al público.
El alcance del estudio: conflictos inmobiliarios y urbanos (proyectos de vivienda, densidad/altura, patrimonio, especulación,
legalidad administrativa, DS19) en las 32 comunas de la Provincia de Santiago, 2014-2026.

## Qué debes decidir por cada conflicto
Lee, como mínimo, los documentos con rol focal/co_focal (todos los que puedas si son pocos) en su texto completo.
Veredicto (`veredicto`):
- `correcto`: es una disputa real y concreta dentro del alcance; los documentos focales tratan esa disputa; el label y los
  proyectos corresponden a ella.
- `error_menor`: disputa real dentro del alcance pero con fallas localizadas (label impreciso, un proyecto listado tangencial,
  comuna dudosa) que no engañarían a un analista sobre lo esencial.
- `error_grave`: un analista que use este registro sería engañado. Incluye: no hay disputa real (mención de pasada, contexto,
  panorama), fuera del alcance territorial o temático, dos disputas distintas fusionadas, o el label/proyectos no corresponden a
  lo que dicen los documentos focales.
- `no_verificable`: no pudiste leer las fuentes o el texto no permite decidir.

`categoria` (obligatoria si el veredicto no es `correcto`; una de): `sin_disputa_real`, `fuera_de_alcance`,
`disputas_distintas_fusionadas`, `label_no_coincide`, `proyecto_ajeno`, `comuna_incorrecta`, `otro`.

Además, para cada conflicto evalúa su respaldo de forma independiente (`respaldo_correcto`): ¿existe en `evidence` al
menos una cita de `objeto` que pertenezca a un documento focal/co_focal y que describa de verdad el objeto de la disputa de
alguno de los proyectos del conflicto? Responde `si`, `no` o `no_evaluable`.

Cada decisión debe justificarse con una cita LITERAL (copiada del texto fuente) en `cita_literal` y una frase en `motivo`.
No inventes citas. Si dudas entre dos veredictos, elige el menos favorable y dilo en `motivo`.

## Formato de salida
Escribe UN archivo: `intermediate/review_samples/blind_validation/verdicts.json` con la forma:

```json
{"revisor": "<tu modelo>", "verdicts": [
  {"conflict_id": "...", "muestra": "main|stress", "veredicto": "...", "categoria": null,
   "respaldo_correcto": "si|no|no_evaluable", "documentos_leidos": ["document_id", "..."],
   "cita_literal": "...", "motivo": "..."}
]}
```
Debe haber exactamente un veredicto por cada `conflict_id` de ambos archivos (80). Guarda el archivo de forma incremental cada
10 conflictos para no perder trabajo. Al terminar, responde solo con el recuento de veredictos por categoría y cualquier
conflicto que no pudiste evaluar. No hagas ninguna otra escritura.
