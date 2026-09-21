# Solicitud de expediente oficial mínimo — caso "Guetos verticales de Estación Central"

Generado 2026-09-16, a pedido de Felipe, siguiendo la recomendación de Sol
("incorporar un expediente oficial mínimo — municipio/DOM, MINVU-Seremi,
Contraloría y BCN/Diario Oficial — para este mismo caso, antes de escalar
a 10-20 casos"). Este documento NO contiene los documentos oficiales en sí
(no se ha hecho ninguna descarga ni scraping nuevo) — es la lista precisa y
citable de qué pedir, a quién, y por qué, construida a partir de los
números de documento ya extraídos literalmente de la prensa por la Fase F
(`enrich_case_v2.py`) y verificados contra el texto fuente.

## Por qué esto importa

Todo el piloto hasta ahora está construido sobre prensa y opinión (Sol:
"todo el piloto sigue basado en prensa y opinión" — su recomendación
explícita es priorizar el arco institucional). Los documentos oficiales
permitirían: (a) confirmar o refutar la narrativa de "permisos ilegales"
que manejan los medios contra la posición de las inmobiliarias/Colliers de
que eran "permisos válidos bloqueados posteriormente" (tensión que Sol
señaló explícitamente como controversia no resuelta, no un hecho jurídico
pacífico); (b) dar fecha/número verificable a cada hito de la línea de
tiempo, hoy sustentado solo en cómo la prensa parafraseó el documento
oficial, no en el documento mismo.

## 1. Contraloría General de la República

| Documento | Fecha | Contenido según la prensa | Por qué pedirlo |
|---|---|---|---|
| Dictamen N° 27.918 | 2018 | Determina la ilegalidad de 49 permisos de edificación otorgados por la Municipalidad de Estación Central; instruye su invalidación administrativa y un sumario en la DOM. Fuente: `elciudadano.com/.../estacion-central-administracion-de-rodrigo-delgado...` | Es el documento más citado por la prensa como fundamento de "permisos ilegales" — hoy solo tenemos la paráfrasis periodística, no el dictamen. |
| Dictamen N° 27.918/2018 (referencia a desacato) | posterior a 2018 | Una fuente menciona "denuncia desacato a su dictamen N° 27.918/2018" — sugiere un dictamen de seguimiento o una denuncia formal de incumplimiento. | Confirmaría si el dictamen original se cumplió o no — dato clave para la controversia que señaló Sol. |

**Cómo pedirlo**: portal de Contraloría (buscador de dictámenes por número/año) o solicitud de Transparencia. No requiere gestión municipal previa.

## 2. Municipalidad de Estación Central (DOM + Alcaldía)

| Documento | Fecha | Contenido según la prensa | Por qué pedirlo |
|---|---|---|---|
| Decreto Alcaldicio N° 324 | 2017-04-26 | Reconoce la vigencia del PRC de Santiago (sic, verificar si es error de la fuente por "de Estación Central") y justifica la postergación de permisos por 3 meses; luego prorrogado el 26 de julio (mismo año, sin año explícito confirmado en el texto — ver limitación de `fecha_year_grounded` abajo). Fuente: `eldinamo.cl/.../guetos-verticales-miente-miente...` | Es el acto administrativo que congeló permisos — confirmaría fecha exacta y alcance real (¿toda la comuna o solo ciertos proyectos?). |
| Carta de Armin Seeger a Gustavo Hasbún | 2008-01-14 | Propone un programa para "fortalecer y agilizar" la DOM y promover iniciativas inmobiliarias. Fuente: `elciudadano.com/.../administracion-de-rodrigo-delgado...` | Documento fundacional del vínculo entre la administración municipal y el boom inmobiliario, según la narrativa de prensa — confirmar si existe registro formal (no solo carta privada referida por un tercero). |
| Registro de permisos de edificación aprobados 2013-2020 | 2013-2020 | "107 permisos de edificación de edificios" según registro municipal citado por la prensa. Fuente: misma que la anterior. | Permitiría reconstruir la línea de tiempo real de permisos, no solo los casos que llegaron a prensa. |
| Expediente DIA — Edificio Las Rejas (Inmobiliaria Las Rejas S.A.) | ingresada 2012-06 | Declaración de Impacto Ambiental para 2 torres de 23 pisos, 1.017 departamentos. Fuente: `elciudadano.com/.../las-nuevas-callampas...` | Es el caso mejor documentado del piloto (ver `proyecto_edificio_las_rejas_v1` en el crosswalk) — el expediente confirmaría representante legal, fecha exacta de ingreso y estado de tramitación real. |
| Permiso de edificación — proyecto SuKsa "esquina de los circos" | posterior a venta 2014 | Torre de 40 pisos, 3.237 departamentos, 49 locales, 449 estacionamientos, según el permiso citado por la prensa. Fuente: misma que Las Rejas. | Confirmaría si el permiso efectivamente se otorgó y en qué condiciones. |

**Cómo pedirlo**: Ley de Transparencia (Portal de Transparencia, `portaltransparencia.cl`) dirigida a la Municipalidad de Estación Central / DOM — solicitar los expedientes por nombre de proyecto o número de decreto.

## 3. MINVU / SEREMI Metropolitana de Vivienda y Urbanismo

| Documento | Fecha | Contenido según la prensa | Por qué pedirlo |
|---|---|---|---|
| Circular 203-DDU 313 | 2016-05-16 | Relacionada con la imposibilidad de edificación continua. Fuente: `elciudadano.com/.../administracion-de-rodrigo-delgado...` | Circulares DDU son documentos técnicos públicos del MINVU — confirmar el texto exacto y su aplicación real al caso. |
| Oficio Seremi N° 4939, al Director de Obras Municipales | 2015 | Interpretación sobre rasantes y distanciamientos aplicable a los proyectos. Fuente: `eldinamo.cl/.../guetos-verticales-todos-los-analizados...` | Es la interpretación normativa que habría habilitado (o no) los permisos cuestionados — clave para la controversia "permisos ilegales vs. válidos". |
| Oficio Seremi N° 3660, a Agrupación Defensa Barrios EC + DOM + Contraloría | 2017-08-30 | Respuesta del Seremi a acusaciones sobre anteproyectos y permisos. Fuente: misma que el oficio anterior. | Documento de la posición oficial del MINVU frente a las mismas acusaciones que documenta la prensa — necesario para no publicar solo el lado vecinal/municipal de la controversia. |
| Retiro del Plan Regulador Comunal del SEA | 2008-07-31 | El alcalde Gustavo Hasbún retiró el PRC de Estación Central del Servicio de Evaluación Ambiental. Fuente: `elciudadano.com/.../administracion-de-rodrigo-delgado...` | Explica por qué la comuna operó sin PRC vigente durante gran parte del boom — dato estructural para entender el caso completo. |

**Cómo pedirlo**: Transparencia dirigida a la SEREMI Metropolitana de Vivienda y Urbanismo; los oficios con número y fecha exactos facilitan la búsqueda directa.

## 4. BCN Ley Chile / Diario Oficial

| Documento | Fecha | Contenido según la prensa | Por qué pedirlo |
|---|---|---|---|
| Modificación N° 1 del PRC de Estación Central (Decreto N° 41 exento, alcalde) | Diario Oficial, 2014-01-30 | Fuente: `eldinamo.cl/.../guetos-verticales-miente-miente...` | Estos SÍ son públicos y de acceso directo (Diario Oficial y BCN Ley Chile son bases públicas) — deberían poder obtenerse sin solicitud de transparencia, solo búsqueda directa por fecha/número. |
| Modificación N° 2 del PRC de Estación Central (Decreto N° 32, MINVU) | Diario Oficial, 2017-01-04 | Fuente: misma que la anterior. | Idem. |
| Plan Regulador Comunal (version vigente desde ~2018-04-28) | Diario Oficial, 2018-04-28 | Fija hasta 12 pisos en el eje Alameda y 5 pisos en calles interiores. Fuente: `transportevertical.org/sitio/guetos-verticales-en-santiago/` | El instrumento normativo que formalmente cierra (o reordena) el boom — confirmar el texto exacto de las alturas máximas por zona. |

**Cómo pedirlo**: búsqueda pública directa en `diariooficial.interior.gob.cl` (por fecha) y `bcn.cl/leychile` (por decreto/norma) — no requiere solicitud de transparencia, es información ya pública. Esta categoría es la más rápida de conseguir de las cuatro.

## Confirmaciones ya obtenidas vía búsqueda web pública (2026-09-16, antes de la solicitud formal)

No se descargó ningún documento oficial completo, pero 3 búsquedas públicas
(WebSearch) ya confirman independientemente varios datos que solo teníamos
parafraseados por la prensa del corpus:

1. **Dictamen Contraloría N° 27.918 — fecha exacta confirmada: 12 de
   noviembre de 2018** (el corpus solo tenía "2018", sin día/mes).
   Confirmado además: invalidó permisos de **49 edificios**, coincide
   exacto con la cifra ya extraída. Fuente:
   [El Mostrador, 2018-11-16](https://www.elmostrador.cl/noticias/pais/2018/11/16/contraloria-declara-ilegales-permisos-de-edificacion-en-estacion-central/).
2. **La controversia "permisos ilegales vs. permisos válidos bloqueados"
   que Sol señaló probablemente tiene resolución judicial firme, según
   fuentes periodísticas secundarias** — **[CALIFICACIÓN 2026-09-16,
   hallazgo de Luna: esto NO es verificación primaria]** La Tercera y Emol
   reportan que la Corte de Apelaciones de Santiago y la Corte Suprema
   rechazaron los recursos de las inmobiliarias contra el dictamen de
   Contraloría. Esto viene de **prensa que reporta sobre las sentencias,
   no de las sentencias mismas** — no se descargó ni leyó ningún fallo
   judicial oficial (Poder Judicial / Corte Suprema). Fuentes secundarias:
   [La Tercera (Corte de Santiago)](https://www.latercera.com/pulso/noticia/corte-de-santiago-confirma-invalidacion-de-permisos-de-edificacion-en-estacion-central/CARTTIC7BVB7DJ3543SGTODIUI/),
   [La Tercera (Corte Suprema)](https://www.latercera.com/pulso/noticia/corte-suprema-ratifica-invalidacion-de-permisos-de-edificacion-a-proyectos-de-departamentos-en-estacion-central/HJM3ZUZSSVBHLNO5WRQM5XPU74/),
   [Emol](https://www.emol.com/noticias/Nacional/2020/03/10/979333/Corte-rechaza-recursos-edificios-estacion.html).
   Esto tampoco significa que no siga habiendo controversia
   pública/mediática (Colliers y las inmobiliarias pueden seguir
   sosteniendo su posición en prensa) — el piloto debe distinguir tres
   capas, no dos: (a) lo que dice la prensa sobre el conflicto, (b) lo que
   la prensa reporta sobre las sentencias, (c) las sentencias oficiales
   mismas — hoy solo tenemos (a) y (b). Las sentencias del Poder Judicial
   (búsqueda por rol de causa, no incluidas todavía en esta solicitud)
   deberían agregarse como quinta categoría si se prioriza este caso.
3. **Circular DDU 313 confirmada real, con fecha exacta coincidente
   (2016-05-16)**, indexada públicamente en el propio sitio de circulares
   del MINVU (`minvu.gob.cl/elementos-tecnicos/circulares-generales-ddu-por-numero/`)
   — trata sobre aplicación de los artículos 1.1.2 y 2.6.1 de la OGUC
   cuando no hay norma de edificación continua establecida. Coincide
   exactamente con lo que la prensa parafraseó.
4. **Existe literatura académica específica sobre este caso**: "Contraloría
   y dictámenes sobre permisos de edificación ilegales: la (in)validez de
   los guetos verticales de Estación Central" —
   [Dialnet](https://dialnet.unirioja.es/servlet/articulo?codigo=8147097).
   Relevante para el arco de Christian (auditoría de evidencia) y el de
   Nicolás (institucional) — es literatura jurídica ya publicada sobre
   exactamente este caso, no habría que "descubrirla" desde cero.
5. **Discrepancia menor detectada**: el corpus (transportevertical.org)
   dice que Estación Central se separó de Santiago en **1985**; la
   búsqueda web indica **1984** ("Estación Central fue formada en 1984").
   No resuelto — anotado para verificar contra una fuente oficial (BCN o
   la propia ley de creación de la comuna) antes de publicar cualquiera de
   las dos fechas como definitiva.

## Limitación explícita

Todos los números de documento anteriores vienen de **cómo la prensa los citó**, no de haber leído el documento oficial mismo — es exactamente el vacío que esta solicitud busca cerrar. Un número mal transcrito por el medio (fecha, número de decreto) se propagaría aquí también. Verificar cada uno contra la fuente oficial antes de darlo por exacto.

## Siguiente paso sugerido

Los 4 documentos del Diario Oficial/BCN (sección 4) son los más rápidos de obtener por ser de acceso público directo, sin solicitud de transparencia — buen punto de partida de bajo costo. Los expedientes de DOM/Contraloría/Seremi (secciones 1-3) requieren solicitudes formales de Transparencia, que toman tiempo de respuesta legal (15-20 días hábiles en Chile) — conviene iniciarlas pronto si se quiere avanzar con el arco institucional de Nicolás.

## Lo que falta para ser una solicitud formal presentable (hallazgo de Luna)

Este documento es una **lista de investigación** (qué pedir, a quién, por
qué), no todavía un formulario listo para presentar por Ley de
Transparencia. Para eso faltaría, por cada solicitud:
- **Solicitante**: nombre/RUT/domicilio o correo del solicitante (Felipe,
  o quien la consultora designe) — dato personal que no corresponde
  completar sin su confirmación explícita.
- **Formato de entrega solicitado**: copia digital (PDF) vs. copia física;
  la Ley de Transparencia permite elegir.
- **Delimitación administrativa final**: cada organismo (Municipalidad,
  SEREMI, Contraloría) tiene su propio portal/formulario de Transparencia
  — no hay un formulario único; hay que llenar uno por organismo.
- **Texto jurídico de la petición**: la Ley 20.285 exige una redacción
  específica citando el derecho de acceso a la información pública; no se
  redactó ese texto legal aquí, solo el contenido sustantivo de qué se
  pide.
Esto queda pendiente para cuando se decida presentar las solicitudes de
verdad (no antes, para no generar un documento a medio llenar con datos
personales sin confirmar).

## Enlace pendiente: crosswalk ↔ evidencia (hallazgo de Luna)

Los 5 `project_id` adjudicados en `crosswalk_project_id_piloto.json` v3
citan su documento fuente (URL) pero **no enlazan todavía a un
`evidence_id` específico de la tabla `evidence` del warehouse, ni al hash
exacto del párrafo leído**. La verificación que sustenta cada adjudicación
fue una lectura directa del texto completo (documentada arriba en este
mismo archivo y en la bitácora), no una cita ya materializada en el
warehouse con su propio `evidence_id` — son dos capas de evidencia
distintas hoy, sin cruzar entre sí. Cerrar esto requeriría: por cada
adjudicación, identificar si el párrafo leído coincide con alguna fila de
`evidence` ya existente (probable que sí, dado que son citas del mismo
documento) o crear una nueva entrada de evidencia trazable a esa lectura
específica. No se hizo en esta ronda — queda como deuda explícita para la
próxima vez que se trabaje el crosswalk.
