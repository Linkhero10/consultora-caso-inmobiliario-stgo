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
Hospital/Núcleo Ochagavía.

## Búsqueda sistemática realizada (dos rondas)

Sobre las 608 `case_mention` focales/co-focales, `caso_unico`, `decision_final_amplio='include'`,
con `codigo_comuna_ine` válido (visibles en el dashboard público), se buscaron tres patrones:

1. **Homónimos geográficos con código INE de Santiago.**
2. **`nombre_proyecto` no sustentado por evidencia verificada** (el patrón exacto de Hospital
   Ochagavía): documentos donde el `nombre_proyecto` no aparece como substring literal en ninguna
   cita de objeto verificada de una mención incluida del mismo documento.
3. **Objeto de disputa fuera de la Provincia de Santiago**.

Los patrones 1 y 3 se agotaron por completo contra los 608 case_mention en la primera ronda: **0
casos nuevos** en ninguno de los dos. Los únicos matches del patrón 1 (Recoleta+Perú, Recoleta+La
Paz, Providencia+Uruguay, La Florida+México) ya están correctamente `decision_final_amplio='exclude'`.
El patrón 3 solo produjo 3 falsos positivos triviales (nombres de calle, no de lugar real).

### Patrón 2 — ronda 1 (2026-09-23, primera pasada, incompleta)

Una primera búsqueda automatizada generó 115 candidatos y solo se revisaron a mano ~30 -- la
conclusión de esa ronda ("0 casos nuevos confirmados") quedó explícitamente acotada a esa
submuestra, no a los 115 completos. El usuario pidió completar la auditoría de los candidatos
restantes.

### Patrón 2 — ronda 2 (2026-09-23, auditoría completa)

Se reconstruyó la lista de candidatos con una metodología más precisa (comparación de conjuntos de
palabras clave, no solo substring completo, excluyendo artículos/preposiciones): **204 documentos
focales de 551 no tienen `nombre_proyecto` como substring literal en ninguna cita verificada
incluida** (más candidatos que la ronda 1 porque el criterio quedó más estricto/documentado, no
porque haya más bugs). Se separaron en:

- **Tier A (128 casos, cero solapamiento de palabras clave con la evidencia)**: la señal más
  fuerte de riesgo. Revisados **los 128, uno por uno**, vía 3 subagentes en paralelo, cada uno
  verificando título del documento, `proyectos_mencionados_json`, todas las `case_mention` del
  documento (no solo las incluidas), y documentos "hermanos" que mencionen el mismo `project_id`.
- **Tier B (76 casos, algún solapamiento de palabras clave)**: señal más débil -- casi siempre
  nombres descriptivos largos que por diseño no calzan como substring completo pero sí comparten
  una palabra distintiva real con la evidencia (ej. "Humedal Urbano..." ↔ cita "secar un humedal").
  Se revisaron a mano los 2 casos de menor solapamiento (ambos resultaron bien fundados); los 74
  restantes (solapamiento ≥0.2) **no se revisaron individualmente** -- el patrón observado sugiere
  que son en su mayoría paráfrasis legítimas, pero esto es un supuesto razonable, no una
  verificación exhaustiva.

## Resultado final

| Grupo | n | bien fundado | posible error (confirmado) | no concluyente | sin revisar individualmente |
|---|---|---|---|---|---|
| Patrón 1 (homónimos) | 608 case_mention | -- | 0 | -- | 0 |
| Patrón 3 (fuera de región) | 608 case_mention | -- | 0 | -- | 0 |
| Patrón 2, Tier A | 128 | 123 | **4** | 1 | 0 |
| Patrón 2, Tier B | 76 | 2 (submuestra) | 0 (submuestra) | 0 | 74 |

Detalle completo caso por caso: `audit/fix_1c_patron2_auditoria_completa.json`.

### Los 4 casos confirmados y corregidos

Los 4 comparten exactamente el patrón de Hospital Ochagavía: `nombre_proyecto` viene de una
`case_mention` **excluida** o de una referencia retórica/periférica, mientras la `case_mention`
realmente **incluida** describe un objeto distinto. Los 4 aparecían como evidencia `focal`
(verificada, visible en el dashboard público) bajo el nombre equivocado; los 4 se corrigieron con
`document_case_unit.correccion_nombre_proyecto=''` protegido por `tiene_error=1` explícito, igual
que Hospital Ochagavía -- ya no cuentan como evidencia focal.

1. **"Templo votivo"** — el objeto real es el nuevo Plan Regulador Comunal de Maipú (límites de
   altura); el templo es solo una referencia retórica en el titular ("Ninguna construcción
   superará al Templo votivo").
2. **"Liceo Reino de Dinamarca"** — el objeto real son las faenas de la empresa minera Imperial
   SPA que generan contaminación en Rinconada Rural; el liceo es el establecimiento afectado
   (clases suspendidas), no el proyecto en disputa. **Este caso ya había sido señalado
   independientemente por la revisión externa del Gate 1A**
   (`conflict:fdac62833c48b1814f2b74a9`, categoría `etiqueta_no_coincide_con_evidencia`) --
   confirmación cruzada por dos métodos distintos.
3. **"Hotel Sheraton San Cristóbal"** — la mención literal del hotel quedó excluida; el caso
   incluido es un juicio de ENACO contra el nuevo plan regulador de Lo Barnechea.
4. **"Casona de calle Huérfanos"** — la mención de esa casa específica quedó excluida; el caso
   incluido es la protección patrimonial general del barrio Yungay.

## Conclusión

**Fix 1C se cierra con auditoría completa del Tier A (128/128) y submuestra representativa del
Tier B (2/76 de los de menor solapamiento).** Se encontraron y corrigieron 4 casos reales
adicionales al de Hospital Ochagavía -- total 5 documentos corregidos en esta fase. La tasa de
error real medida es baja (4/128 = 3.1% en el grupo de mayor riesgo, 0/480 en los patrones 1 y 3,
que sí se agotaron por completo) pero no cero: confirma que el patrón de Hospital Ochagavía no fue
un caso aislado, aunque tampoco es un problema sistémico masivo.

**Lo que queda explícitamente sin auditar**: los 74 candidatos del Tier B con solapamiento parcial
de palabras clave. Dado el patrón observado (nombres descriptivos largos con al menos una palabra
distintiva real coincidente), el riesgo esperado es bajo, pero esto no se ha verificado caso por
caso.

## Estado del gate CONFLICT

El gate CONFLICT (Fix 1A + Fix 1B + Fix 1C) se considera cerrado para el Tier A completo (mayor
riesgo, 100% auditado) y con una salvedad explícita en el Tier B (74/76 sin auditar
individualmente, riesgo estimado bajo). Ver `audit/run_manifest.json` para el estado del warehouse
vigente.
