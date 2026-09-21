# Comparación revisión humana vs IA — muestra ciega v5.2.1 (50)

- Revisor humano: **Felipe** (human_blind_review)
- Casos comparados: **50**; URLs coincidentes con IA: **True**
- Humano: {'confirmar_exclude': 35, 'aprobar_include': 13, 'requiere_mas_revision': 1, 'mantener_uncertain': 1}
- IA, decisión amplia: {'insufficient_content': 10, 'include': 11, 'exclude': 25, 'uncertain': 4}
- Acuerdo estricto (clase exacta): **33/50 (66.0%)**
- Acuerdo operacional (exclude también cubre insufficient_content): **42/50 (84.0%)**
- Includes amplios del modelo: **11**; aprobados por Felipe: **9**
- Falsos positivos definidos (modelo include + Felipe exclude): **2**
- Includes del modelo no aprobados (incluye incierto/más revisión): **2**
- Includes humanos que fueron override de un no-include del modelo: **4**

## Lectura correcta

El criterio de liberación es **0 falsos positivos**: un include producido por el modelo que Felipe no aprueba no se libera. `insufficient_content` y `confirmar_exclude` son equivalentes operacionalmente seguros, pero se conservan como etiquetas distintas.

El bundle de Sol no contiene veredictos independientes caso por caso; sirve como paquete de auditoría de las salidas de IA. No se presenta consenso de modelos como validación.

Detalle por URL: `comparison_human_vs_ai_blind_v5_2_1_50.json`.

Nota metodológica añadida el 2026-09-15: Felipe confirmó que la revisión humana fue verdaderamente ciega a las salidas de las IAs. La comparación no debe tratarse como revisión asistida ni como gold absoluto, pero sí como evaluación humana independiente respecto del modelo.
