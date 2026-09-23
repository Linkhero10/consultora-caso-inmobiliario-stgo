# Fix 1C — investigación de falsos positivos geográficos/semánticos del clasificador

## Alcance

Fix 1A y Fix 1B corrigieron la capa CONFLICT (respaldo documental trazable y adjudicación de los
15 `conflictos_distintos_fusionados`). Fix 1C ataca la capa anterior: falsos positivos
geográficos o semánticos introducidos por el clasificador LLM aguas arriba, antes de que un
documento/mención llegue a `build_conflicts.py`.

El propio Fix 1B produjo el caso canónico que motiva Fix 1C: el documento "Pedro Aguirre Cerda
toma medidas para poner freno a edificios de altura" fue clasificado con
`enrichment_document.nombre_proyecto = "Núcleo Ochagavía"` pese a que su contenido real trata
anteproyectos genéricos de regulación de altura, sin relación con el sitio específico
Hospital/Núcleo Ochagavía. Ver `tests/test_build_conflicts.py::test_hospital_ochagavia_pac_document_no_longer_focal`
para la regresión y el docstring de `src/build_conflicts.py` (sección "Fix 1B") para el detalle
completo del caso.

## Búsqueda sistemática realizada

Sobre las 608 `case_mention` focales/co-focales, `caso_unico`, `decision_final_amplio='include'`,
con `codigo_comuna_ine` válido (visibles en el dashboard público), se buscaron tres patrones:

1. **Homónimos geográficos con código INE de Santiago**: nombres de comuna con riesgo de
   homonimia (Recoleta, Providencia, San Joaquín, Independencia, La Florida, San Ramón, La Reina,
   Vitacura) cruzados contra menciones de países/ciudades extranjeras en `evidence.quote_text`, más
   verificación de consistencia interna `comuna` (texto) vs. `codigo_comuna_ine` contra `territory`.
2. **`nombre_proyecto` no sustentado por evidencia verificada** (el patrón exacto de Hospital
   Ochagavía): documentos donde el `nombre_proyecto` no aparece como substring literal en ninguna
   cita de objeto verificada de una mención incluida del mismo documento.
3. **Objeto de disputa fuera de la Provincia de Santiago**: `case_mention` con comuna válida pero
   cuya evidencia de objeto mencione explícitamente otra región de Chile o un país extranjero.

## Resultado

Los patrones 1 y 3 sí se agotaron por completo contra los 608 case_mention: **0 casos nuevos** en
ninguno de los dos. Los únicos matches del patrón 1 (Recoleta+Perú, Recoleta+La Paz,
Providencia+Uruguay, La Florida+México) ya están correctamente `decision_final_amplio='exclude'`.
El patrón 3 solo produjo 3 falsos positivos triviales ("Barcelona"/"Ecuador" como nombres de calle,
no de lugar real).

**El patrón 2 NO se agotó por completo -- esto se corrige aquí explícitamente tras revisión
externa que señaló que la redacción anterior sonaba más exhaustiva de lo que fue.** Generó una
lista automatizada de 115/551 documentos focales sin substring literal (22 con cero solapamiento
de tokens). Se revisaron a mano solo **~30 de los 115** (los 22 de cero solapamiento más ~8
adicionales de la lista completa), no los 115. En esos ~30, a diferencia de Hospital Ochagavía,
el nombre resultó bien fundado en todos (confirmado en un documento hermano del mismo caso, en el
título del artículo, o en contexto no capturado por la cita muestreada) -- ninguno era una
fabricación real. **Los ~85 candidatos restantes del patrón 2 quedan sin auditar
individualmente.** La afirmación correcta es "0 confirmados en la submuestra revisada del patrón
2", no "0 confirmados sobre los 115".

**Conclusión: Fix 1C se cierra en esta ronda sin cambios de código, con esta salvedad explícita
pendiente.** El caso Hospital Ochagavía era relativamente aislado dentro de la submuestra
revisada, no evidencia de un problema sistémico -- pero esa conclusión está acotada a ~30/115
candidatos del patrón 2, no a su totalidad. Auditar los ~85 restantes queda como trabajo futuro
concreto para retomar Fix 1C, no como parte de este cierre.

## Observaciones de menor confianza, no confirmadas como bugs (seguimiento eventual, no bloqueante)

1. El documento sobre "Barrio Las Rejas" lista como alias "Nueva Alameda Providencia" (proyecto
   real y distinto, con su propio documento focal). La evidencia sí menciona NAP como causa de la
   amenaza al barrio, así que es defendible, pero vale la pena revisar si esto infla el conteo de
   `project.n_documents` para ese proyecto.
2. 157 `project_id` en `project_mention_resolved` tienen menciones incluidas en más de una comuna
   (ej. un hito usado como referencia geográfica en varios artículos). La mayoría parecen
   legítimos, pero el volumen sugiere que valdría la pena una auditoría dedicada de
   `homonym_partition` como tarea aparte -- no se hizo a fondo por estar fuera del alcance
   estricto de "documentos focales con falso positivo geográfico/semántico".

## Estado del gate CONFLICT

El gate CONFLICT (Fix 1A + Fix 1B + Fix 1C) se considera cerrado **para el alcance efectivamente
auditado** -- con la salvedad explícita de arriba: ~85 candidatos del patrón 2 de Fix 1C quedan
sin revisar individualmente. No se detectó nada en la submuestra que sugiera que retomarlos
cambiaría la conclusión, pero "no se detectó nada en 30/115" no es lo mismo que "se descartaron
los 115". Ver `audit/run_manifest.json` para el estado del warehouse en el momento de este cierre.
