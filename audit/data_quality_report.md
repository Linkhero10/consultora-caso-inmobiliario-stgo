# Informe de calidad de datos

Síntesis de los hallazgos de validación que dieron forma al diseño y de los límites vigentes de los datos. Las
cifras del producto (proyectos, conflictos, respaldo) no se repiten aquí: están en el bloque generado de
[START HERE](../START_HERE.md) y en `audit/run_manifest.json`. “Sin respaldo” no significa “falso”.

## 1. La unidad «documento» no es la unidad «conflicto»

Una muestra aleatoria estratificada de 50 documentos con extracción estructurada, revisada caso por caso:

| Veredicto | n | % |
|---|---:|---:|
| OK | 21 | 42% |
| Error menor | 17 | 34% |
| Error grave | 12 | 24% |

Los errores graves eran sistemáticos: documentos que discutían más de un conflicto real bajo una sola unidad de
análisis, por nombres de proyecto que coincidían entre desarrollos distintos. **Consecuencia de diseño:** se separó
la identidad física de proyecto (`project`), la identidad de conflicto (`conflict`) y un gate documental
(`document_conflict`, con rol `focal`/`co_focal`/`contextual_mention`). Ver `docs/architecture.md`.

Una ampliación a 150 conflictos del universo completo midió 42 % de error grave sobre el diseño de ese momento
(mención promovida a conflicto sin vínculo verificado). Motivó capturar el vínculo proyecto → mención en la
extracción.

## 2. Homónimos reales protegidos contra fusión automática

La identidad de proyecto nunca se fusiona por similitud de texto entre documentos distintos: solo por nombre
normalizado idéntico o por decisión humana con evidencia. Casos reales que una regla laxa habría fusionado: dos
proyectos llamados «El Colorado» (un centro de esquí y una vivienda social); «San Isidro» de Quilicura y el de Buenos
Aires; «Plaza Egaña» como intersección y como desarrollo de Vitacura. Una auditoría de 131 proyectos que aparecían en
varias comunas halló 0 homónimos reales: el patrón era una atribución por documento, no por mención (corregida al
resolver la geografía a nivel de `case_mention`).

## 3. Identidad de actor y multiafiliación

«Contraloría» y «Contraloría General de la República» contaban como dos nodos (7 y 10 conflictos); consolidadas con
evidencia (29 variantes textuales → 6 instituciones nacionales sin ambigüedad de jurisdicción) llegan a 17
conflictos. Quedan sin resolver, por ambigüedad real de jurisdicción: Cortes de Apelaciones y Tribunales Ambientales
sin sede identificada, Direcciones de Obras Municipales sin comuna, SEREMIs regionales y personas naturales.

## 4. Fusión de unidades frente a exigencia de evidencia

Al comparar la red actor↔conflicto con la red actor↔caso, de 49 actores con caída aparente de multiafiliación, 48 se
explicaban por el requisito de evidencia más estricto y solo 1 por la fusión de unidades. Una prueba dedicada protege
que un conflicto nunca tenga más multiafiliación que la suma de sus casos.

## 5. Menciones duplicadas

La clasificación puede generar varias `case_mention` para el mismo objeto dentro de un documento (5.731
menciones en 3.885 documentos; 102 grupos con duplicados y 257 menciones en ellos; 17 grupos con decisiones mixtas).
El agrupador determinista solo señala: pertenecer a un grupo no transfiere evidencia ni comuna, y puede juntar
proyectos distintos que comparten una cita genérica.

## 6. Límites vigentes

- No hay validación ciega de extremo a extremo del estado final; las muestras humanas miden estados anteriores y el
  vínculo proyecto → mención tiene su propia validación (0 fabricaciones en 809 evaluaciones).
- Conflictos sin respaldo: parte se revisó una sola vez, con verificación de citas y hashes y sin segunda lectura
  independiente completa.
- Menciones de proyecto sin vínculo a una `case_mention` y grupos de duplicados sin adjudicar uno por uno (ver cifras
  en START HERE).
- El descubrimiento no tiene recall medido; el corpus se inclina a lo reciente (52 % de los documentos incluidos con
  fecha son de 2022–2026 y 796 documentos no tienen fecha), de modo que no permite separar incidencia de
  recuperabilidad.
- Las descripciones de los contratos de extracción se limpiaron de anotaciones internas después de ejecutarse; los
  hashes registrados en los registros corresponden al contrato tal como se ejecutó (con saltos de línea CRLF).

Detalle de los estándares que previenen cada problema: [`docs/standards.md`](../docs/standards.md).
