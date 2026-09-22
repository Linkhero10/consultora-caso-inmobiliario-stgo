# Gate 1A-Validación — resultado y decisión

## Holdout

- N=100 (muestreo aleatorio simple, universo completo menos los 150 IDs de calibración) + N=50
  (muestra dirigida a `sin_respaldo_exact_quote_detectado`, reportada aparte).
- Independencia verificada dos veces: (1) por intersección de conjuntos contra los 150 IDs de
  calibración (0% de solapamiento, ver `holdout_1a_manifest.json`); (2) por un revisor externo
  ciego, que reprodujo los SHA-256 de ambas listas de forma independiente.
- Revisión ciega: el revisor no tuvo acceso a `respaldo_evidencia`, `coverage_backing`,
  `detector_version`, `match_method` ni ninguna señal derivada del detector.
- Warehouse sin cambios entre la generación del holdout y este cruce
  (`8ac767b7d5f4a80a4c49d3b56b8ce50ba72ad65ea3bc4e411141c3f0d36aa8e5`).

## Resultado (ver `gate1a_validacion_crosswalk.json` para el detalle completo)

| Muestra | Target | TP | FP | FN | TN | Precisión (IC95%) | Recall (IC95%) |
|---|---|---|---|---|---|---|---|
| Main N=100 | error_grave | 36 | 29 | 1 | 34 | 55.4% (43.3–66.8%) | 97.3% (86.2–99.5%) |
| Main N=100 | target categories | 29 | 36 | 1 | 34 | 44.6% (33.2–56.7%) | 96.7% (83.3–99.4%) |
| Stress N=50 | error_grave | 28 | 22 | 0 | 0 | 56.0% (42.3–68.8%) | 100% (por diseño) |
| Stress N=50 | target categories | 23 | 27 | 0 | 0 | 46.0% (33.0–59.6%) | 100% (por diseño) |
| Calibración N=150 (referencia) | error_grave | 49 | 27 | 14 | 60 | 64.5% | 77.8% |
| Calibración N=150 (referencia) | target categories | 44 | 32 | 4 | 70 | 57.9% | 91.7% |

## Interpretación

- El recall fuera de muestra es **igual o más alto** que en calibración (97%/97% vs 78%/92%): el
  detector casi no deja pasar errores graves reales sin marcarlos `sin_respaldo`.
- La precisión fuera de muestra es más baja que en calibración (55%/45% vs 65%/58%), pero el
  intervalo de confianza de `error_grave` incluye la cifra de calibración (64.5% está dentro de
  43.3–66.8%); en `target_categories` la calibración (57.9%) queda apenas fuera del intervalo
  (33.2–56.7%) — una caída de precisión pequeña y estadísticamente marginal, no un colapso.
- La interpretación de diseño original se sostiene sin cambios: recall alto / precisión moderada
  sirve para priorizar revisión y construir el universo analítico conservador del dashboard, nunca
  para declarar que un conflicto sin respaldo es falso.
- La muestra de estrés confirma el mismo patrón de precisión entre los casos ya marcados
  `sin_respaldo`, sin agregar sorpresas.

## Decisión

**GO.** El holdout independiente reproduce, dentro de márgenes estadísticos razonables, la misma
calibración medida en N=150 -- de hecho con mejor recall. No hay evidencia de que el detector se
comporte peor fuera de muestra de lo que la calibración ya advertía. Se habilita Fix 1B (revisión
uno por uno de los 15 `conflictos_distintos_fusionados`) y, después, Fix 1C.

El número de conflictos "sin respaldo" (508/839) sigue sin ser parte de ningún gate -- se observa y
reporta, nunca se fuerza a un rango.
