# Plan de reprueba ciega v5.2.3

## Estado

- La revisión de Felipe fue independiente y ciega a las salidas de las IAs.
- v5.2.2 ya fue recalculado sin API y corrigió cuatro falsos negativos geográficos.
- Los dos falsos positivos semánticos de la primera corrida (SciELO y Cambio21) no se consideran corregidos todavía: requieren nueva inferencia.
- Producción sigue bloqueada hasta obtener cero falsos positivos definidos.

## Ejecución autorizada

Usar 50 workers, fixture congelada y salida separada:

```powershell
& 'D:\Analisis conflictos\.venv\Scripts\python.exe' `
  'D:\Felipe\Consultora\caso_inmobiliario_stgo\Trabajo\scripts\classify_v5_2_2.py' `
  --urls-file 'D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\blind_sample_v5_2_1_50_urls.txt' `
  --output-file 'D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\clasificacion_blind_v5_2_3_50.jsonl' `
  --workers 50
```

El módulo usa `classifier_system_v5_2_3.md` y
`classification_schema_v5_2_3.json`, conserva el gate v5.2.2 y no toca
`clasificaciones.jsonl` de producción. No repetir sobre el mismo archivo sin
renombrarlo o eliminarlo de manera explícita: el escritor es append-only.

## Comparación posterior

```powershell
& 'D:\Analisis conflictos\.venv\Scripts\python.exe' `
  'D:\Felipe\Consultora\caso_inmobiliario_stgo\Trabajo\scripts\compare_human_v5_2_2_blind50.py' `
  --ai 'D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\clasificacion_blind_v5_2_3_50.jsonl' `
  --output-json 'D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\comparison_human_vs_ai_blind_v5_2_3_50.json' `
  --output-md 'D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\comparison_human_vs_ai_blind_v5_2_3_50.md'
```

## Gate de aceptación

1. `definite_model_include_false_positives_n == 0` frente a la revisión humana.
2. No liberar producción si el punto 1 falla, aunque aumente el acuerdo global.
3. Revisar manualmente cualquier `model_broad_decision=include` no aprobado.
4. Si pasa, crear un nuevo artefacto humano `status=aprobado_revision_humana`
   solo después de confirmar el resultado; este plan no lo autoriza por sí solo.
5. Si falla, registrar cada caso en el ledger y construir otra muestra ciega;
   no seguir ajustando indefinidamente sobre estos mismos 50.

