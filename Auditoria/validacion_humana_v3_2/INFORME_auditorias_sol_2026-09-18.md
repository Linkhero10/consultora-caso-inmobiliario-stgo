# Informe — Dos auditorías de Sol sobre el pipeline v3.2, verificadas independientemente

**Fecha**: 2026-09-18. **Revisor**: Sol (GPT-5.6). **Verificación independiente**: Claude (Sonnet 5), contra
los datos y el código reales, antes de aceptar cualquier hallazgo. Este documento es el resumen para el
equipo (Darío, Nicolás, Christian) de ambas auditorías, con los archivos fuente y qué hacer con cada una.

---

## 1. Auditoría de la cola de fusión de proyectos (253 pares)

**Qué se le pidió a Sol**: revisar los 253 pares de la cola de candidatos a fusión de proyectos
(`project_review_queue_para_revision_sol.json`) contra la evidencia real (comuna, dirección, URL de cada
documento) y marcar solo los desacuerdos con la decisión ya tomada por Claude, sin sobrescribirla.

**Resultado de Sol**: confirmó 222/253 (87.7%), refutó 31/253 (12.3%) — 18 falsas separaciones (debían
fusionarse) y 13 fusiones agresivas (debían separarse). Chequeo de transitividad del grafo: 0
contradicciones antes y después de sus 31 correcciones propuestas.

**Verificación de Claude**: se revisaron las 31 discrepancias una por una contra la evidencia real
(comuna/dirección/URL) antes de aplicar nada. **Las 31 se confirmaron.** Dos patrones de error reales en
la resolución original de Claude:

1. **Números de dirección tratados como números de etapa/fase.** La regla `has_conflicting_numeral()`
   bloqueaba fusiones cuando dos nombres tenían un número al final, sin distinguir "Etapa II" de
   "calle Vital Apoquindo 1.400". Afectó: General Amengual 480, Pajaritos 4600, todo el cluster Vital
   Apoquindo, Urbanya Etapa I, y el cluster completo de Mall Vivo (6 pares — comprobado con evidencia:
   todos los documentos ubican el proyecto en el mismo predio, Vicuña Mackenna/Carlos Dittborn, Ñuñoa,
   ex terrenos de Copesa).
2. **"Empresa/institución ≠ proyecto específico" aplicado de forma inconsistente.** El principio ya se
   había aplicado bien a Fundamenta, pero no a "Nueva El Golf" (fusionada por error con proyectos
   específicos de esa inmobiliaria en ubicaciones distintas) ni a "Universidad San Sebastián" (fusionada
   con un edificio físico específico suyo en Bellavista).

Más 6 fusiones hechas solo por coincidencia de nombre, sin verificar que la ubicación coincidiera:
**Rotonda Atenas** es el caso más claro — el proyecto histórico está en Las Condes/Manquehue-Nueva Delhi
y el "proyecto social de 2023" está en Cerro Colorado 4661, junto a Parque Arauco. Mismos comuna, lugares
distintos. Otros: Barrio Maestranza, Barrio Parque, Parque Bicentenario Cerrillos (vs. el de Vitacura, a
kilómetros), Hospital del Salvador, Carlos Valdovinos.

**Aplicado**: `Trabajo/scripts/resolve_project_review_queue.py` — 31 entradas nuevas que sobrescriben la
decisión anterior, script re-ejecutado sin costo de API. Resultado final: **133 fusionados, 120
mantenidos separados** (antes: 128/125). Verificado con SQL directo que las 31 correcciones surtieron
efecto real en `project.case_id` (ninguna quedó fusionada por una ruta distinta). `PRAGMA
integrity_check=ok`. Test de regresión que fija las 31 decisiones explícitamente. Suite: **141/141**.

**Archivo actualizado para el equipo**: `Auditoria/integracion_v1/project_review_queue_resuelta.json`.

**Pregunta conceptual de Sol, sin resolver todavía** (para hablar con el equipo antes de que Darío use
`case_id` como unidad de análisis de redes): hoy `case_id` mezcla dos criterios — "¿es el mismo edificio
físico?" y "¿es el mismo caso/conflicto analítico?". Una Etapa II puede ser técnicamente otra fase, pero
pertenecer al mismo caso de conflictividad. Sol propone un modelo explícito de 3 niveles:

```
PROJECT (mismo edificio/desarrollo físico)
   ↓
PROJECT_PHASE / SUBPROJECT (una etapa de ese desarrollo)
   ↓
CASE / CONFLICT (el mismo conflicto analítico, puede abarcar varias fases o incluso proyectos distintos del mismo actor)
```

No se implementó — no hace falta reconstruir la base ahora, pero es una decisión de diseño que conviene
tomar antes de convertir los 876 `case_id` actuales en la unidad definitiva del análisis.

---

## 2. Validación humana real del enrichment (muestra de 50 documentos)

**Qué se le pidió a Sol**: revisar los 50 documentos de la muestra aleatoria estratificada
(`muestra_validacion_humana_v3_2_n50_seed20260918.json`, semilla fija) contra el texto fuente real, y
llenar `veredicto_humano`/`notas_humano` por cada uno.

**Resultado de Sol**: 21/50 `ok` (42%), 17/50 `error_menor` (34%), **12/50 `error_grave` (24%)**, 0
`no_verificable`.

**Esta es la primera validación humana real del enrichment v3.2.** Todo lo verificado antes en esta
sesión (integridad SQL, hashes, conteos, gate de calidad automático) fue verificación de datos/código,
nunca una lectura humana con criterio de dominio sobre si el "caso" extraído tiene sentido.

**Verificación de Claude**: se comprobaron 3 de los 12 `error_grave` directamente contra
`enrichment_document_v3_2` y el título real del artículo. **Los 3 confirmaron exactamente lo que Sol
describe**:

| Documento | Título real | Qué extrajo el enrichment | Problema |
|---|---|---|---|
| La Tercera, Estación Central | "...**tres proyectos** paralizados por presiones políticas" | `proyectos_mencionados: ["Ciudad del Niño", "Plaza Egaña"]` | Ninguno de los dos es uno de los 3 edificios del título — son ejemplos comparativos de otras comunas |
| DF, Cencosud | "...proyecto **en Argentina**" | `ubicacion_especifica: "San Isidro... Buenos Aires, Argentina"` | Caso focal fuera del universo (Santiago); Costanera Center solo aparece como comparación |
| Emol, Peñalolén | Vecinos de una comunidad residencial | `nombre_proyecto: "Comunidad Ecológica de Peñalolén"` | Una comunidad/barrio real quedó registrada como si fuera "el proyecto en disputa" |

**El hallazgo importante, ya respaldado por evidencia, no solo por el reporte de Sol: el problema no es
que el extractor invente citas** (el grounding literal funciona razonablemente bien incluso en los casos
`error_grave`) **— es que no existe ningún gate que decida, antes de extraer, qué tipo de unidad de caso
es el documento.**

Sol identificó 4 familias de error recurrentes:

1. **Documentos panorámicos/comparativos tratados como un caso único** — artículos jurídicos con varios
   precedentes, perfiles políticos con varias controversias, notas electorales que recorren varias
   comunas.
2. **Casos secundarios/ejemplos comparativos capturados como si fueran el caso focal** — el caso de
   "edificios fantasma" de arriba es el ejemplo más claro.
3. **Actores/comunidades/lugares confundidos con "proyecto"** — "Comunidad Ecológica de Peñalolén" es el
   ejemplo verificado; también ocurre con condominios/comunidades afectadas.
4. **El caso focal real está fuera del universo de Santiago** — el caso Cencosud/Argentina verificado.

Los 17 `error_menor` son de otra naturaleza y menos preocupantes: citas puntuales que no pasaron el
verificador de substring, una fecha sin año, un identificador de permiso ("PE N° 88 de 2016") tratado
como nombre de proyecto, una ubicación usada como nombre de proyecto. El núcleo del caso sigue siendo
recuperable en todos estos.

**Recomendación de Sol, no implementada, pendiente de decisión**: agregar un gate explícito
`documento → unidad(es) de caso` con categorías como

```
caso_unico
multiples_casos_documentados
documento_comparativo_panoramico
contexto_sin_caso_individualizable
caso_focal_fuera_del_universo
```

Sol explícitamente **no** recomienda tocar el extractor de actores por este hallazgo — el grounding de
citas ya funciona bien; el problema está un nivel de abstracción arriba, antes de la extracción.

**Impacto real para el arco de Darío (SNA/redes)**: con 24% de `error_grave` verificado en una muestra
aleatoria, no conviene construir la red de actores sobre `case_id`/`project_id` como si fuera una unidad
100% confiable sin filtrar primero los documentos de las 4 familias de error — al menos hasta que exista
el gate que propone Sol, o hasta que se audite manualmente una porción mayor del corpus.

**Archivo con la revisión completa, auditable** (incluye `resumen_revision_sol` con los conteos y el
criterio aplicado, no es una edición silenciosa):
`Auditoria/validacion_humana_v3_2/muestra_validacion_humana_v3_2_n50_seed20260918_rellenada_sol.json`.

---

## Resumen de archivos para el equipo

| Archivo | Contenido |
|---|---|
| `Auditoria/integracion_v1/project_review_queue_resuelta.json` | Las 253 decisiones finales de fusión de proyectos, ya corregidas |
| `Auditoria/validacion_humana_v3_2/muestra_validacion_humana_v3_2_n50_seed20260918_rellenada_sol.json` | La muestra de 50 documentos con veredicto humano real por cada uno |
| Este informe | Resumen de ambas auditorías + qué queda pendiente de decidir |

## Pendientes de decisión (no técnicos, requieren al equipo)

1. **Modelo de 3 niveles** (PROJECT / PROJECT_PHASE / CASE) propuesto por Sol para `case_id` — decidir
   si se implementa antes de que Darío empiece el análisis de redes.
2. **Gate `documento → unidad de caso`** propuesto por Sol — decidir si se construye antes de escalar el
   enrichment a más documentos o de confiar en `case_id` para el análisis.
3. Si el 24% de `error_grave` amerita una segunda muestra de validación humana más grande antes de dar
   por buena la calidad general del enrichment, o si alcanza con excluir las 4 familias de error
   identificadas.
