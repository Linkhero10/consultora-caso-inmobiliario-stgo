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

**0 casos nuevos confirmados.** Los únicos matches del patrón 1 (Recoleta+Perú, Recoleta+La Paz,
Providencia+Uruguay, La Florida+México) ya están correctamente `decision_final_amplio='exclude'`.
El patrón 3 solo produjo 3 falsos positivos triviales ("Barcelona"/"Ecuador" como nombres de calle,
no de lugar real). El patrón 2 generó una lista de 115/551 documentos focales sin substring
literal (22 con cero solapamiento de tokens); se revisaron a mano ~30 de los casos más extremos y,
a diferencia de Hospital Ochagavía, en todos el nombre resultó bien fundado (confirmado en un
documento hermano del mismo caso, en el título del artículo, o en contexto no capturado por la
cita muestreada) -- ninguno era una fabricación real.

**Conclusión: Fix 1C se cierra sin cambios de código.** El caso Hospital Ochagavía era relativamente
aislado, no síntoma de un problema sistémico en la clasificación de `nombre_proyecto`. Esto no
significa que el clasificador sea perfecto -- significa que, con los tres patrones buscados en
serio contra los datos reales, no se encontró evidencia de un problema recurrente que justifique
una corrección de código en esta ronda.

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

Con este cierre, el gate CONFLICT completo (Fix 1A + Fix 1B + Fix 1C) queda cerrado. Ver
`audit/run_manifest.json` para el estado del warehouse en el momento de este cierre.
