# Gate 1A — paquete ciego de validación

Este directorio contiene un paquete candidato para la revisión humana del
detector de respaldo documental de Fix 1A.

## Estado actual

`holdout_1a_manifest.json` marca el paquete como `ready_for_external_review`.
Los 150 `conflict_id` de la calibración original se recuperaron desde el
archivo de validación externa N=150 (110 coincidían exactamente; 40 tenían el
hash transcrito con error y se recuperaron por prefijo único de 6 caracteres,
verificado a mano contra el contenido de una muestra). `calibration_ids_present`
= 150/150 e `independence_verified = true`: se confirmó por comparación directa
de conjuntos que ninguno de los 100 casos de `holdout_main_n100.json` ni de los
50 de `stress_sample_n50.json` coincide con los 150 de calibración. Este
paquete sí puede presentarse como validación externa una vez revisado.

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
warehouse y con las señales del detector para calcular TP/FP/FN/TN. La
muestra principal (aleatoria simple) informa las métricas poblacionales; la
muestra de estrés (dirigida a `sin_respaldo_exact_quote_detectado`) se
reporta aparte y nunca se mezcla con las métricas poblacionales del holdout
principal.
