# Gate 1A — paquete ciego de validación

Este directorio contiene un paquete candidato para la revisión humana del
detector de respaldo documental de Fix 1A.

## Estado actual

`holdout_1a_manifest.json` marca el paquete como
`candidate_independence_unverified`. La lista durable de los 150 conflictos
usados en la calibración N=150 no existe en los artefactos históricos. Por eso
estos archivos son reproducibles y ciegos, pero no deben presentarse todavía
como validación externa ni usarse para calcular un gate de cierre.

## Archivos

- `holdout_main_n100.json`: muestra principal de 100 conflictos.
- `stress_sample_n50.json`: muestra dirigida adicional de 50 conflictos,
  reportada separadamente de las métricas poblacionales.
- `holdout_1a_manifest.json`: semilla, hashes, tamaño del universo y estado de
  independencia.

Los registros contienen únicamente la unidad de conflicto, proyectos,
documentos, menciones y citas/evidencias necesarias para una revisión. Se
omitieron los campos derivados por el detector. La revisión debe hacerse sobre
la evidencia y las fuentes, sin inferir la respuesta a partir de la selección.

## Formato de respuesta humana

Para cada `conflict_id`, devolver:

```json
{
  "conflict_id": "...",
  "veredicto": "correcto|error_menor|error_grave|no_verificable",
  "categoria_error": "etiqueta_no_coincide_con_evidencia|falso_positivo_inclusion|conflictos_distintos_fusionados|otro|ninguna",
  "justificacion": "...",
  "fuentes_revisadas": ["..."]
}
```

La respuesta humana se cruza después, fuera del paquete ciego, con el
warehouse y con las señales del detector para calcular TP/FP/FN/TN. Hasta que
se recupere la lista de calibración, cualquier resultado debe conservar la
etiqueta de independencia no verificada.
