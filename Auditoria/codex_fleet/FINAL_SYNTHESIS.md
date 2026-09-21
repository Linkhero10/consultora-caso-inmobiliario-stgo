# Síntesis de auditoría adversarial Codex/Luna

Fecha: 2026-09-12  
Modo: tres subagentes GPT-5.6 Luna, esfuerzo xhigh, solo lectura; debate cruzado posterior. Claude no fue invocado.

## Veredicto

El pipeline está mucho más endurecido que al inicio, pero todavía no es un corpus productivo cerrado. El problema central no es un bug aislado: falta una identidad obligatoria de corrida/contrato (snapshot, código, esquema y prompt) que atraviese todas las etapas y sea validada por los gates.

## Bloqueantes antes de aceptar producción

1. **Mezcla de contratos:** el snapshot contiene 2.592 registros v2 y 95 legacy sin `periodo`/`nivel`; `fulltext_v2` conserva 67 de esos registros. Deben aislarse como `legacy_v1` o rechazarse.
2. **Pérdida de procedencia:** `fulltext_acquisition_v2` deduplica por URL antes de materializar todos los orígenes; se observaron 355 URLs con lineages múltiples. Los orígenes descartados ya no pueden recuperarse desde fulltext.
3. **Discovery no reanudable dentro de una consulta:** una sola fila marca el combo completo; un crash después del primer resultado puede perder los ranks restantes.
4. **Artefactos pre-fix:** la corrida activa de fulltext fue iniciada antes de los últimos parches y su manifest contiene 429/503/error. Debe tratarse como corrida pre-fix, conservarse como evidencia y reconstruirse bajo el contrato vigente.

## Riesgos altos

- Reanudación downstream basada solo en URL: no detecta cambios de texto, snapshot o contrato.
- Crash duro deja lock/estado `running` sin recuperación explícita ni `needs_resume`.
- Mutex de `run_state` rompe su propia exclusión tras un timeout fijo; debe usar ownership/lease o fail-closed.
- Dedupe no publica eventos/vista de forma transaccional. El riesgo de pérdida permanente es especialmente real si queda un `fingerprint_candidate` antes del evento canónico, porque cualquier evento vuelve la URL “ya procesada”. La afirmación más fuerte de pérdida entre `canonical_elected` y `origin_added` fue matizada: normalmente el URL sin evento reaparece.
- Clasificación no valida localmente `classification_schema_v2` antes de escribir.
- `evidence_verified=true` con cita vacía en decisiones `exclude` es semánticamente engañoso para consumidores downstream, aunque el gate de `include` sí funciona.

## Lo que sí quedó validado

- Hashes y lineages observados del snapshot son íntegros.
- El benchmark final de 12 casos es reproducible y terminó con `MANTENER_XHIGH`: 3 regresiones de citas en `high`, 100% acuerdo institucional, 91,7% en evidencia y actores.
- Los locks, checkpoints, gates de citas y lectura tolerante de JSONL mejoraron de forma sustantiva.

## Orden recomendado

1. Cerrar o marcar la corrida fulltext pre-fix; congelar un snapshot v2 puro y conservar todos los orígenes.
2. Corregir el checkpoint de discovery y la identidad de corrida/contrato.
3. Añadir recuperación segura de locks y publicar dedupe mediante archivo temporal + reemplazo atómico.
4. Ejecutar dedupe, clasificación v2 y enrichment v2 sobre el corpus cerrado.
5. Corregir la semántica de `evidence_verified` y validar localmente schemas antes de publicar.

No recomendamos otra ronda abierta de “buscar cualquier cosa”. El siguiente ciclo debe ser una implementación acotada de estos bloqueantes, seguida de una única verificación de regresión.
