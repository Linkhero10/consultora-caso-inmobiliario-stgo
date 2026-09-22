# Prompt para Sol — revisión ciega del Gate 1A

## Rol

Actúa como revisor externo e independiente del detector de respaldo documental
de Fix 1A. No edites el repositorio, no modifiques el warehouse y no cambies el
detector. Tu tarea es revisar la evidencia sustantiva de los conflictos, no
auditar el código.

## Archivos que debes leer

1. `audit/holdout_1a/README.md`
2. `audit/holdout_1a/holdout_1a_manifest.json`
3. `audit/holdout_1a/holdout_main_n100.json`
4. `audit/holdout_1a/stress_sample_n50.json`

El manifiesto informa `status=ready_for_external_review`: se recuperaron los
150 `conflict_id` de la calibración original (`calibration_conflict_ids.txt`)
y se confirmó que ninguno de los 100+50 casos de este paquete se solapa con
ellos (`independence_verified=true`). Esta revisión sí puede tratarse como
validación externa independiente para el Gate 1A-Validación una vez completa.

La muestra principal N=100 y el stress sample N=50 tienen propósitos distintos.
No mezcles sus conteos ni calcules una sola métrica conjunta. No intentes
inferir por qué fue seleccionado un caso del stress sample.

## Regla de ceguera

No busques ni reconstruyas `respaldo_evidencia`, `coverage_backing`,
`n_projects_backed`, `n_projects_unbacked`, `label_source_project_id`,
`detector_version`, `match_method`, `backing_scope` ni ninguna otra señal
derivada del detector. Esos campos fueron omitidos deliberadamente.

Evalúa cada unidad únicamente con el título, URL, documentos asociados,
menciones, citas y evidencia disponibles en el paquete. Si una fuente no abre,
regístralo como `no_verificable`; no completes el dato por inferencia.

## Qué revisar en cada conflicto

Para cada `conflict_id`:

1. **Existencia del conflicto:** ¿los documentos describen una disputa,
   oposición, denuncia, litigio, decisión administrativa o controversia urbana
   concreta, y no solo una mención tangencial?
2. **Correspondencia de la etiqueta:** ¿el `label` y los proyectos asociados
   corresponden a la evidencia de los documentos, o se mezclaron proyectos,
   comunas o países distintos?
3. **Unidad analítica:** ¿los documentos parecen tratar el mismo conflicto o
   fusionan conflictos distintos? Si hay varios `case_ids`, examina cada uno y
   no asumas que la multiplicidad implica respaldo.
4. **Evidencia:** ¿las citas de objeto, acción y geografía sustentan lo que el
   registro afirma? Contrasta las citas con la URL cuando sea posible.
5. **Geografía y alcance:** ¿el caso pertenece al universo territorial y social
   del proyecto? Señala casos fuera de Santiago/Chile o de otro alcance definido.
6. **Ambigüedad:** si la información no permite decidir, usa `no_verificable` o
   `error_menor` según corresponda; no fuerces un sí/no.

## Veredictos permitidos

- `correcto`: la unidad y su etiqueta son compatibles con las fuentes.
- `error_menor`: hay un problema localizado que no cambia la unidad principal.
- `error_grave`: falso positivo, etiqueta incompatible, fusión de conflictos
  distintos, proyecto/comuna/país equivocado o cualquier error que cambie la
  unidad analítica.
- `no_verificable`: la evidencia disponible no permite resolver el caso.

Usa estas categorías de error cuando corresponda:

- `ninguna`
- `etiqueta_no_coincide_con_evidencia`
- `falso_positivo_inclusion`
- `conflictos_distintos_fusionados`
- `geografia_fuera_de_alcance`
- `evidencia_insuficiente`
- `otro`

## Formato de respuesta

Devuelve un JSON válido, sin omitir casos y preservando exactamente cada
`conflict_id`:

```json
{
  "paquete": "holdout_main_n100|stress_sample_n50",
  "independencia_verificada": false,
  "revisiones": [
    {
      "conflict_id": "conflict:...",
      "veredicto": "correcto|error_menor|error_grave|no_verificable",
      "categoria_error": "ninguna|etiqueta_no_coincide_con_evidencia|falso_positivo_inclusion|conflictos_distintos_fusionados|geografia_fuera_de_alcance|evidencia_insuficiente|otro",
      "justificacion": "Explicación breve basada en evidencia observable.",
      "fuentes_revisadas": ["URL o document_id"],
      "evidencia_clave": ["cita o referencia concreta"],
      "proyectos_o_casos_confundidos": ["solo si aplica"]
    }
  ],
  "resumen": {
    "correcto": 0,
    "error_menor": 0,
    "error_grave": 0,
    "no_verificable": 0,
    "observaciones_metodologicas": "..."
  }
}
```

No es necesario entregar una cadena de pensamiento extensa. Basta con una
justificación verificable, las fuentes consultadas y la evidencia clave de cada
decisión. Devuelve un archivo separado para el paquete principal y otro para el
stress sample.

## Qué haremos después

El expediente humano se cruzará localmente con el warehouse, fuera de tu
revisión. Solo después se evaluará si es posible calcular TP/FP/FN/TN. Mientras
`independencia_verificada=false`, cualquier resultado se etiquetará como
`revisión humana preliminar`, no como rendimiento externo ni cierre del gate.
