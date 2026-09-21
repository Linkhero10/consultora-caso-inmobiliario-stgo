# Informe de calidad de datos

Resumen de los hallazgos de validación que dieron forma al diseño actual del sistema. No es un
registro paso a paso del desarrollo — es la síntesis de qué se encontró y qué cambió como
consecuencia. El detalle completo de cada corrección vive en el archivo de desarrollo privado.

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

## 5. Estado de la validación

La validación muestral N=50 identificó el problema real; no se ha corrido todavía una segunda
muestra más grande sobre el corpus completo. Las conclusiones analíticas de fondo (más allá de la
infraestructura de identidad, que sí está verificada y cerrada) siguen pendientes de los arcos
sustantivos de análisis.
