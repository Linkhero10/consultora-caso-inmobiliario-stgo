# Informe de calidad de datos

Resumen de los hallazgos de validación que dieron forma al diseño actual del sistema. No es un
registro paso a paso del desarrollo — es la síntesis de qué se encontró y qué cambió como
consecuencia. El detalle completo de cada corrección vive en el archivo de desarrollo privado.

## Estado operativo vigente — 2026-09-27

La base publicada inspeccionada en esta fecha tiene SHA-256
`378bf7d7686d676dfb1e08cb5c141a2e5bea29b943ad0de6ef4f58d0900c09db`, integridad SQLite `ok` y
cero violaciones de claves foráneas. Contiene 941 proyectos, 850 `case_id`, 833 conflictos y
15.245 vínculos actor→proyecto; 502 conflictos tienen alguna fila de respaldo automático y 331 no.
La cobertura del respaldo es total en 473 conflictos, parcial en 29 y ninguna en 331. “Sin respaldo”
no significa “falso” ni “sin conflicto”.

La reconciliación del paquete histórico `CLASSIFIED_63` encontró 48 IDs ausentes del universo actual:
15 afectan la topología (`mismo_conflicto`/`conflictos_distintos`) y bloquean una reconstrucción
completa; 33 son referencias no topológicas que se preservarán sin alias ni proyección a conflicto.
No se promovieron fusiones de proyecto en esta pasada. El preflight es
`audit/historical_case_reference_preflight.json`; la base publicada no fue modificada. UKAMAU se
registra en una capa descriptiva sustentada por tres evidencias verificadas, sin crear un
`project_id` ni fusionarla con otra identidad.

La validación N=100 + stress N=50 de Fix 1A está completada para su detector y sus conclusiones
están registradas en `audit/validation_summary.json`. El stress es dirigido, no estima prevalencia;
además, sus resultados no validan por sí solos esta reconciliación histórica ni una futura relación
proyecto↔mención. No publicar una reconstrucción integral de CONFLICT hasta resolver con evidencia
los 15 bloqueos topológicos. Los arcos analíticos pueden desarrollar métodos en el warehouse
vigente, pero sus productos deben identificar esta limitación y no presentarse como una nueva
reconstrucción cerrada.

## 1. La unidad "documento" no es la unidad "conflicto"

Una muestra aleatoria estratificada de 50 documentos enriquecidos, revisada caso por caso, encontró:

| Veredicto | n | % |
|---|---:|---:|
| OK | 21 | 42% |
| Error menor | 17 | 34% |
| Error grave | 12 | 24% |

Los errores graves eran sistemáticos, no ruido aleatorio: documentos que discutían más de un
conflicto real bajo una sola unidad de análisis (`case_id`), producto de nombres de proyecto que
coincidían entre desarrollos físicamente distintos. Un 24% de error grave sobre esa muestra
significaba que ninguna red de actores construida directamente sobre `case_id` podía considerarse
confiable.

**Consecuencia de diseño**: se separó explícitamente la identidad física de proyecto (`project`,
homónimos fusionados solo con evidencia verificada), de la identidad sociológica de conflicto
(`conflict`), con una capa de gate documental intermedia (`document_conflict`, con rol
`focal`/`co_focal`/`contextual_mention`) que decide qué evidencia cuenta como protagonista de cada
conflicto. Ver `docs/architecture.md`.

## 2. Homónimos reales encontrados y protegidos contra fusión automática

La resolución de identidad de proyecto nunca fusiona por similitud de texto entre documentos
distintos — solo por coincidencia exacta de nombre normalizado, o por decisión humana explícita
sobre evidencia real (comuna, dirección, actores). Casos reales verificados que habrían fusionado
incorrectamente con una regla más laxa:

- Dos proyectos distintos llamados "El Colorado" (un centro de esquí y una vivienda social).
- "San Isidro" en Chile (planta de tratamiento de aguas, Quilicura) vs. "San Isidro" en Argentina
  (desarrollo de Cencosud en Buenos Aires) — mismo nombre, países distintos.
- "Plaza Egaña" como intersección real (Ñuñoa/La Reina) vs. un desarrollo distinto en Vitacura que
  también se menciona como "Plaza Egaña".

## 3. La fragmentación textual subestimaba la multiafiliación institucional real

Antes de resolver identidad de actor, "Contraloría" y "Contraloría General de la República"
contaban como dos nodos distintos en la red (7 y 10 conflictos respectivamente). Al fusionar con
evidencia verificada (29 variantes textuales reales del corpus, mapeadas a 6 instituciones
nacionales sin ambigüedad de jurisdicción), la entidad consolidada llega a 17 conflictos —
empatando con la Corte Suprema. La fragmentación nominal subestimaba la multiafiliación observada
de la institución en la red actor–conflicto (grado bipartito, no una medida de centralidad como
betweenness o eigenvector, todavía no calculadas).

Quedan deliberadamente sin resolver (ambigüedad de jurisdicción real, no negligencia): Cortes de
Apelaciones y Tribunales Ambientales sin sede identificada, Direcciones de Obras Municipales sin
comuna, SEREMIs regionales, y personas naturales.

## 4. Separar el efecto de fusionar unidades del efecto de exigir evidencia

Al construir la red actor↔conflicto, una comparación directa contra la red anterior (actor↔caso)
atribuía toda caída de multiafiliación a "fragmentación de un mismo conflicto en varios proyectos".
Eso confundía dos efectos reales y distintos: el cambio de unidad de agrupación, y el nuevo
requisito de que el documento trate ese conflicto como protagonista (no solo mencionado). Separando
ambos efectos con un universo intermedio de comparación: de 49 actores con caída aparente de
multiafiliación, 48 se explicaban por el requisito de evidencia más estricto, y solo 1 por la
fusión real de unidades. La propiedad matemática (un conflicto nunca puede tener más multiafiliación
que la suma de sus casos) quedó protegida con un test dedicado, no solo documentada.

## 5. Estado de la validación — contexto histórico y vigencia

La muestra N=50 de esta sección fue la auditoría inicial y motivó cambios de diseño. Después se
ejecutaron validaciones posteriores, incluida la N=150 de calibración y el holdout N=100 + stress
N=50 de Fix 1A. El estado y sus métricas con procedencia están en
`audit/validation_summary.json`; no reutilizar estos resultados como validación de los gates
históricos ni de una nueva versión del linker. Las conclusiones analíticas sustantivas siguen
pendientes de los arcos y deben usar el snapshot vigente señalado arriba.

## 6. Fix 1A: respaldo documental y ambigüedad multi-caso

La validación ampliada N=150 detectó 63 errores graves (42%), concentrados en promociones
mecánicas de menciones de proyecto a conflictos y en etiquetas que no coincidían con la evidencia.
Fix 1A conserva el universo completo, pero separa una vista conservadora basada en una coincidencia
`exact_substring_v1` entre el nombre normalizado del proyecto y una cita `objeto` verificada de un
documento con al menos una mención incluida.

El esquema actual no tiene un vínculo afirmativo proyecto↔case_mention. Por tanto, el respaldo se
declara como documental, no directo, mediante `backing_scope`; cuando un documento tiene más de una
mención incluida con evidencia de objeto, `ambiguous_multi_case_document=1` hace visible esa
limitación. La tabla `conflict_evidence_backing` conserva la cita, documento, mención, versión del
detector y método de coincidencia.

En el snapshot histórico de cierre de Fix 1A: 839 conflictos, 331 con respaldo documental detectado,
508 sin respaldo; 281 con cobertura total y 50 parcial. Esos conteos no son los del warehouse
vigente (ver el encabezado). Los estados no equivalen a “verdadero/falso”: ausencia de respaldo
significa que la regla conservadora no lo detectó. El holdout N=100 y stress N=50 ya se completaron;
su interpretación y las limitaciones de independencia están anotadas en el bloque de validación
correspondiente de `audit/validation_summary.json`.
