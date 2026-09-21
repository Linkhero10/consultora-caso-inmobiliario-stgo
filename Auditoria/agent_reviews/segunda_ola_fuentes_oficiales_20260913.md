# Segunda ola controlada de fuentes oficiales — Santiago

**Proyecto:** `D:\Felipe\Consultora\caso_inmobiliario_stgo`  
**Fecha de captura:** 2026-09-13 (America/Santiago)  
**Estado:** piloto verificable, read-only; no modifica snapshot de prensa, clasificación, locks, contratos ni datos productivos.

## 1. Alcance y criterio de evidencia

Esta segunda ola buscó únicamente descargas o respuestas públicas, legales y acotadas para complementar el inventario de fuentes oficiales. Se priorizó una comuna/acto o una muestra pequeña cuando la fuente era de gran escala. No se usaron credenciales, se evitó cualquier intento de sortear 403/login, no se llamó SINIM por su restricción de uso no comercial y no se invocaron APIs con ticket faltante.

La evidencia raw queda en:

`D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\agent_reviews\raw_fuentes_oficiales_20260913\`

La condición observable de término fue: (a) al menos un raw verificable para MINVU IPT, permisos MINVU, Diario Oficial, SNIFA/SMA y CMN; (b) un registro explícito de límites o exclusiones; (c) URL, fecha de captura, bytes y SHA-256 para cada raw.

**Convenciones:** “Confirmado” significa que la URL pública respondió y el archivo/cuerpo fue conservado. “Candidato” significa catálogo o ruta útil cuyo contenido no se descargó o no se pudo convertir en una captura de datos utilizable. “Excluido” significa que la restricción fue respetada y no se intentó evadirla.

## 2. Manifiesto de capturas

Todos los hashes son SHA-256 en mayúsculas. Las fechas de modificación de los archivos corresponden a la captura local del 2026-09-13; no se interpreta esa fecha como fecha de actualización del organismo.

| ID | Institución / fuente | URL primaria exacta | Raw local | Estado HTTP | Bytes | SHA-256 |
|---|---|---|---|---:|---:|---|
| F01a | MINVU, Instrumentos de Planificación Territorial RM | https://instrumentosdeplanificacion.minvu.cl/13 | `minvu_ipt_rm_index_20260913.html` | 200 | 1.168.705 | `C5FF97C6305A89EB6325B505900B0939593BAB7A2AD978CF8D7EC8D5BBCC556A` |
| F01b | MINVU, publicación MPRMS-117 La Platina | https://instrumentosdeplanificacion.minvu.cl/files/maps/257/3A.50b19c.13.pdf | `minvu_ipt_mprms117_laplatina_res50_2019.pdf` | 200 | 8.561.901 | `14DA2C48F3B0E919F17C3E702756B01ADB4A461950BF2515DD2DE7B59FFB0066` |
| F02 | MINVU/Centro de Estudios, permisos de edificación | https://catalogo.minvu.cl/cgi-bin/koha/opac-retrieve-file.pl?id=7bc85464839c74082e4ac7fbff52d08c | `minvu_permisos_viviendas_unidades_superficie_ano_comuna.download` | 200 | 496.451 | `DFE2EBEA06E8EC5A2CF3C951D3DE458A6CC728750C5EDD680219D02B66AD3941` |
| F03 | BCN, Ley Chile, Decreto 5274 / PRC Santiago | https://www.bcn.cl/leychile/navegar?idNorma=1132507 | `bcn_leychile_decreto5274_santiago_20190612.html` | 200 | 9.602 | `4FF75CDC3DADE5550D6EEE84A015E513A646A920E50FFCE12CDEA8CF379E9131` |
| F04 | Diario Oficial, CVE 1654184 / Resolución 50 | https://www.diariooficial.interior.gob.cl/publicaciones/2019/09/14/42455/01/1654184.pdf | `diario_oficial_cve1654184_res50_mprms_20190914.pdf` | 200 | 3.620.931 | `5FEBA15042BEAC236FF7E7EE4C30012B21D3D27A5F34C564763ABBFF026238F3` |
| F05 | SMA/SNIFA, catálogo Datos Abiertos | https://snifa.sma.gob.cl/DatosAbiertos | `snifa_datos_abiertos_landing_20260913.html` | 200 | 39.928 | `DAC176EECAED4B15BC583E06985FBA5A124E619B118FFB9F7C1E5648FA0F87F4` |
| F06a | CMN/IDE Patrimonio, puntos de Monumentos Nacionales | https://idepat.patrimoniocultural.gob.cl/server/rest/services/Geodatabase_corporativa/Puntos_Monumentos_Nacionales/FeatureServer?f=pjson | `cmn_puntos_feature_service_metadata.json` | 200 | 5.097 | `77E576BEBA854E679F20DDB3C221A82B1C7CE3F55B850A041E9192D296F5F608` |
| F06b | CMN/IDE Patrimonio, muestra de puntos | https://idepat.patrimoniocultural.gob.cl/server/rest/services/Geodatabase_corporativa/Puntos_Monumentos_Nacionales/FeatureServer/0/query?where=1%3D1&outFields=%2A&returnGeometry=true&resultRecordCount=10&f=geojson | `cmn_puntos_sample10_valid.geojson` | 200 | 8.705 | `94AF86E139EFCEE0B142CE9AB0254FAF4DCEACBA3CB1AB562403D023EEB466E5` |
| F06c | CMN/MINVU IDE, metadatos de polígonos | https://geoide.minvu.cl/server2/rest/services/INFORMACION_EXTERNA/Monumentos_Nacionales/FeatureServer/1?f=pjson | `cmn_poligonos_feature_service_metadata.json` | 200 | 11.123 | `79C4EBD17F856968A778D7C0B8579C90D15CC5646D9910D16618C4BC4170EAB5` |

Se conserva además una captura de error de la primera consulta CMN mal codificada, sin usarla como evidencia positiva: `cmn_puntos_sample10.geojson` (13.254 bytes, SHA-256 `C783B0AE2E306A811341A2B2C206D110AE574A71495C4E89FCC9AF8F4CA144A1`). La consulta corregida y limitada a 10 registros es exclusivamente `cmn_puntos_sample10_valid.geojson`.

## 3. Fichas de fuentes

### F01 — MINVU: Instrumentos de Planificación Territorial (IPT), Región Metropolitana

**Institución y URL primaria.** Ministerio de Vivienda y Urbanismo, catálogo público regional: https://instrumentosdeplanificacion.minvu.cl/13. El portal declara que reúne IPT publicados en Diario Oficial y permite seleccionar comuna/estado; la captura HTML contiene el catálogo RM y enlaces a ordenanzas, memorias y planos.

**Dataset/documento exacto del piloto.** MPRMS-117 / Resolución N°50, “Zonificación y espacio público en un sector de La Platina”, con publicación D.O. y plano asociado. El PDF descargado es la ordenanza/publicación de 15 páginas para la modificación que involucra La Pintana y Puente Alto. El portal también expone el enlace de plano `https://instrumentosdeplanificacion.minvu.cl/files/maps/257/3A.50b19p.13.pdf`, que queda como candidato no descargado en esta ola para mantener el piloto mínimo.

**Unidad y cobertura.** Unidad normativa: instrumento/modificación, acto administrativo y archivo técnico; cobertura territorial: La Platina, comunas La Pintana y Puente Alto, dentro del PRMS; cobertura temporal del acto: publicación 2019-09-14. El catálogo regional permite ampliar a las 32 comunas del ámbito del proyecto, pero no se materializó una descarga masiva.

**Formato, acceso y límites.** HTML de catálogo y PDF público, sin login; no se requirió scraping: se conservaron la página de catálogo y un PDF directo. La disponibilidad histórica depende de que el portal mantenga los archivos; el propio catálogo advierte que documentos faltantes deben solicitarse al municipio. No se estableció una API formal de cambios/versionado. Costo observado: gratuito.

**Licencia/uso.** No se encontró una licencia de datos explícita en la captura; tratar como publicación oficial para consulta y análisis con atribución MINVU, conservando URL, fecha y hash. Verificar condiciones de reutilización antes de redistribuir archivos completos.

**Periodicidad.** Ad hoc, según aprobación/publicación de modificaciones y actualización del catálogo; no es una serie periódica.

**Valor analítico.** Permite ubicar cambios de zonificación, normas y espacio público que pueden contextualizar conflictos inmobiliarios, cambios de potencial edificatorio y controversias territoriales. El PDF de Resolución 50 es un caso piloto directamente conectado con La Platina.

**Riesgos.** Riesgo de sesgo de observación hacia instrumentos formalizados/publicados; un PRC/PRMS no representa por sí solo permisos ejecutados, cumplimiento ni conflicto social. Riesgo de comparabilidad entre versiones y planos; separar acto, fecha de publicación y fecha de vigencia. No contiene microdatos personales en el piloto, pero puede incluir predios/localizaciones sensibles.

**Piloto mínimo recomendado.** Parsear solo la Resolución 50 y su plano, construir una ficha `instrumento → comuna → fecha D.O. → materia → geometría/sector`, y validar manualmente contra Diario Oficial. Después, extender a una modificación por comuna priorizada; no descargar de inmediato todo el catálogo.

**Estado:** **Confirmado** para catálogo y PDF de Resolución 50; **candidato** para planos KML/Shape y resto de instrumentos.

### F02 — MINVU/Centro de Estudios: permisos de edificación por año y comuna

**Institución y URL primaria.** Ministerio de Vivienda y Urbanismo, Centro de Estudios, categoría Permisos de Edificación: https://centrodeestudios.minvu.gob.cl/repositorio/categoria/permisos-de-edificacion/. El archivo enlazado públicamente corresponde al registro de “Viviendas unidades y superficie según año y comuna”, con serie desde 2002 y actualización anunciada hasta junio de 2026 en el catálogo consultado. Descarga directa usada: `https://catalogo.minvu.cl/cgi-bin/koha/opac-retrieve-file.pl?id=7bc85464839c74082e4ac7fbff52d08c`.

**Dataset exacto y unidad.** El raw responde `200`, `application/octet-stream`, pero su firma `PK 03 04` y estructura ZIP son las de un XLSX. El `xl/workbook.xml` contiene seis hojas: `número_total`, `m2_total`, `número_departamentos`, `m2_departamentos`, `número_casas`, `m2_casas`. Unidad analítica: número de viviendas y superficie en m², agregadas por comuna y año; no es un registro de permiso individual.

**Cobertura.** Temporal: desde 2002 hasta la actualización indicada por el catálogo (junio de 2026); territorial: comunas de Chile, con posibilidad de filtrar las 32 comunas del proyecto. La fecha de actualización debe verificarse dentro de la metadata del catálogo al materializar el dataset; no se debe inferir que todos los años tienen igual completitud.

**Formato, acceso y límites.** Descarga pública directa, sin autenticación, 496.451 bytes; conservar con extensión `.download` para no alterar el raw. Es una planilla agregada; límites probables: cambios metodológicos, revisiones, rezagos y ausencia de coordenadas/identificador de proyecto. Costo observado: gratuito.

**Licencia/uso.** No se encontró un texto de licencia específico dentro del archivo descargado. Usar con atribución MINVU/Centro de Estudios y mantener el enlace original; confirmar términos si se redistribuye la planilla completa.

**Periodicidad.** El catálogo ofrece cortes anuales y mensuales por comuna; la ficha descargada es el corte anual. La periodicidad de actualización es editorial y debe registrarse por fecha de captura.

**Valor analítico.** Indicador base para intensidad constructiva, volumen de vivienda y superficie autorizada; complementa noticias y actos normativos sin confundirse con stock construido, recepción final o transacción inmobiliaria.

**Riesgos.** Riesgo de sesgo por permisos no iniciados, anulados o no ejecutados; ruptura de series por cambios de clasificación; riesgo de atribuir a una comuna el efecto metropolitano sin controles. No contiene nombres/RUT en el piloto, pero los agregados pequeños pueden revelar situaciones locales; evitar inferencias sobre hogares individuales.

**Piloto mínimo recomendado.** Leer solo las seis hojas, filtrar 2014–2026 y las 32 comunas, producir validación de totales anuales y documentar unidades. Comparar una comuna y un año contra el corte mensual, sin modificar el pipeline productivo.

**Estado:** **Confirmado** como raw XLSX verificable; contenido analítico requiere validación de encabezados y tipos antes de ingestión.

### F03 — BCN / Ley Chile: norma urbanística municipal

**Institución y URL primaria.** Biblioteca del Congreso Nacional, servicio Ley Chile: https://www.bcn.cl/leychile/navegar?idNorma=1132507. La URL responde `200` con el shell web de Ley Chile. El registro corresponde al Decreto/acto municipal 5274, publicado el 2019-06-12, asociado al Plan Regulador Comunal de Santiago según el catálogo consultado.

**Dataset/norma exacta.** Registro normativo individual identificado por `idNorma=1132507`; no se debe tratar el HTML capturado como el texto normativo: es una aplicación que carga el contenido dinámicamente. El piloto deja constancia de la URL estable y del raw del shell; no se intentó descubrir endpoints internos ni sortear la carga dinámica.

**Unidad y cobertura.** Unidad: acto/norma jurídica; temporal: publicación 2019-06-12; territorial: comuna de Santiago. Ley Chile puede cubrir versiones, relaciones normativas y fechas de vigencia, pero eso debe capturarse en una descarga oficial de la ficha cuando el mecanismo esté documentado.

**Formato, acceso y límites.** HTML de aplicación web, acceso público, 9.602 bytes; la captura no prueba que el articulado completo esté presente en el archivo. No se realizó scraping ni extracción de APIs internas. Costo observado: gratuito.

**Licencia/uso.** Servicio oficial BCN; no se identificó en el shell una licencia de redistribución de la ficha. Usar URL/citación y conservar la evidencia; verificar condiciones BCN si se almacena o redistribuye el articulado.

**Periodicidad.** Actualización jurídica/eventual; no periódica. Las normas pueden tener versiones y anotaciones posteriores.

**Valor analítico.** Complementa el IPT MINVU con una fuente jurídico-legislativa para fechas, vigencia y texto de actos municipales. Puede respaldar la línea `instrumento → norma → cambio territorial`, pero requiere una captura normativa reproducible.

**Riesgos.** Riesgo de usar una versión histórica como vigente; diferenciar publicación, modificación, derogación y texto consolidado. Riesgo de falsa confirmación si solo se conserva el shell HTML. Sin microdatos en el piloto.

**Piloto mínimo recomendado.** Registrar `idNorma`, título, organismo, fecha de publicación y URL desde la ficha Ley Chile; verificar manualmente contra Diario Oficial. No incorporar el shell como evidencia textual suficiente.

**Estado:** **Confirmado** como URL pública y registro candidato; **no confirmado** el texto normativo completo en el raw local.

### F04 — Diario Oficial: publicación de Resolución N°50 / MPRMS-117

**Institución y URL primaria.** Diario Oficial de la República de Chile: https://www.diariooficial.interior.gob.cl/publicaciones/2019/09/14/42455/01/1654184.pdf. El PDF corresponde al CVE 1654184, edición del sábado 14 de septiembre de 2019, 15 páginas.

**Dataset/documento exacto.** Publicación oficial de la Resolución N°50 que modifica el Plan Regulador Metropolitano de Santiago, MPRMS-117 La Platina. Es el contraste primario de la ficha MINVU F01b.

**Unidad y cobertura.** Unidad: publicación/acto normativo; fecha: 2019-09-14; cobertura territorial: sector de La Platina, asociado a La Pintana y Puente Alto. No es una base de permisos ni un inventario de predios.

**Formato, acceso y límites.** PDF directo, público, 3.620.931 bytes; no requiere login. La búsqueda histórica depende de CVE/fecha/edición; no se descargaron otros números. Costo observado: gratuito.

**Licencia/uso.** Publicación oficial del Estado; no se encontró en el PDF una licencia de reutilización separada. Citar edición/CVE y mantener hash; verificar derechos si se redistribuyen facsímiles.

**Periodicidad.** Diaria para el Diario Oficial; el acto es puntual.

**Valor analítico.** Fuente de control para fecha, contenido y trazabilidad jurídica de modificaciones urbanísticas. Reduce el riesgo de usar una copia MINVU desactualizada y permite fechar el evento normativo.

**Riesgos.** La publicación no prueba ejecución, fiscalización ni impacto inmobiliario. PDF escaneado/maquetado puede requerir OCR; cualquier extracción literal debe quedar sujeta a revisión visual.

**Piloto mínimo recomendado.** Extraer metadatos de edición/CVE y revisar las páginas que definen ámbito territorial; vincular por hash/URL a F01b. No usar OCR como texto jurídico sin revisión visual.

**Estado:** **Confirmado**.

### F05 — SMA/SNIFA: catálogo de Datos Abiertos y carpetas públicas

**Institución y URL primaria.** Superintendencia del Medio Ambiente, Sistema Nacional de Información de Fiscalización Ambiental: https://snifa.sma.gob.cl/DatosAbiertos. La página capturada declara acceso a datos reportados por empresas y datos de procesos de la SMA.

**Dataset/API exacto.** El catálogo enlaza carpetas Google Drive para: Termoeléctricas (datos desde 2014), Unidades Fiscalizables e Instrumentos, Sancionatorios, RILES (desde 2017), Fiscalizaciones, Sanciones Firmes SMA y Monitoreo de biodiversidad. Enlaces observados en el HTML incluyen, entre otros, las carpetas públicas de Fiscalizaciones (`https://drive.google.com/drive/u/2/folders/1WAw7SSPMug3oZimgHYkEIi7_5JqLvzpb`), Sancionatorios (`https://drive.google.com/drive/u/2/folders/1O7o60LzQ-qH8xiK_-Ofqw_mZzti_gbEr`) y Unidades Fiscalizables (`https://drive.google.com/drive/u/2/folders/1Pos3xmMDj0OoRiqmR1W9Q2K0hsnMaEL4`).

**Unidad y cobertura.** Unidad esperable: unidad fiscalizable, instrumento, fiscalización, sancionatorio o medición; cobertura temporal según colección (2014+ Termoeléctricas, 2017+ RILES, histórico en fiscalizaciones/sancionatorios); territorial: Chile, relacionable por comuna/coordenadas cuando el archivo lo exponga. No se descargó un archivo Drive porque el catálogo no entregó un URL de archivo directo verificable.

**Formato, acceso y límites.** Landing HTML pública, 39.928 bytes. Las carpetas Drive se trataron como candidatos; la navegación no se convirtió en descarga raw de archivo y no se usó login, gdown ni bypass. La propia SMA advierte que la información fue obtenida/reportada por regulados y no ha sido procesada, analizada ni verificada por la SMA; pueden existir errores u omisiones. Costo observado: gratuito para el catálogo público.

**Licencia/uso.** No se identificó una licencia consolidada para cada archivo Drive. No asumir libertad de redistribución; conservar la atribución SMA y verificar condiciones por archivo antes de ingestión.

**Periodicidad.** Depende del conjunto; el catálogo indica cortes de inicio, no una garantía única de actualización.

**Valor analítico.** Potencial para conflictos socioambientales, cargas regulatorias, fiscalización y proximidad de proyectos/infraestructuras a las 32 comunas. No debe confundirse sanción/fiscalización con impacto ambiental probado.

**Riesgos.** Reporte de regulados, faltantes y errores; posible sesgo hacia unidades que reportan o que fueron fiscalizadas. Riesgo de privacidad/localización si un archivo incluye personas de contacto; minimizar campos. Riesgo de duplicación/versiones dentro de Drive.

**Piloto mínimo recomendado.** Elegir una carpeta y un archivo que tenga URL directo, fecha y formato; descargar una sola muestra una vez confirmada la ruta pública. Registrar checksum del archivo, no de la página Drive. Antes de eso, usar solo el catálogo como fuente candidata.

**Estado:** **Confirmado** para el catálogo HTML; **candidato/excluido de descarga** para archivos Drive por falta de una URL directa verificable en esta ola.

### F06 — CMN: puntos y polígonos de Monumentos Nacionales

**Institución y URL primaria.** Consejo de Monumentos Nacionales / Ministerio de las Culturas, las Artes y el Patrimonio, servicios ArcGIS públicos del IDE Patrimonio. Puntos: https://idepat.patrimoniocultural.gob.cl/server/rest/services/Geodatabase_corporativa/Puntos_Monumentos_Nacionales/FeatureServer. Polígonos: https://geoide.minvu.cl/server2/rest/services/INFORMACION_EXTERNA/Monumentos_Nacionales/FeatureServer/1.

**Dataset/API exacto.** La metadata de puntos describe ubicaciones de Monumentos Históricos, Zonas Típicas o Pintorescas y Santuarios de la Naturaleza; declara actualización semestral, capacidad `Query`, formato JSON y copyright CMN/Ministerio. La muestra pública F06b está limitada a `resultRecordCount=10`, con GeoJSON y geometría. El servicio de polígonos se identificó como `CULTURA_Poligonos_monumentos_nacionales`; declara salida JSON/GeoJSON/PBF y capacidad Query.

**Unidad y cobertura.** Unidad: monumento/registro espacial; atributos observados en la muestra: código, nombre, categoría, región, provincia, comuna y coordenadas/geometría. Cobertura: nacional; la muestra incluyó registros de Metropolitana de Santiago, entre otras regiones, por orden del servicio. Actualización declarada: semestral.

**Formato, acceso y límites.** JSON de metadata y GeoJSON de diez registros, públicos, sin login ni ticket. El portal indicador de CMN para XLSX/KMZ no se descargó porque respondió 403; no se intentó sortearlo. La muestra no debe interpretarse como selección territorial ni como inventario completo. Costo observado: gratuito en el endpoint público.

**Licencia/uso.** La metadata declara copyright del CMN y Ministerio; no se encontró licencia abierta detallada en el JSON. Citar organismo, servicio y fecha de captura; confirmar términos antes de redistribuir geometrías completas.

**Periodicidad.** Semestral según descripción del servicio, asociada a nuevas declaraciones/publicaciones.

**Valor analítico.** Permite construir una capa de restricciones/protección patrimonial y proximidad a proyectos, permisos o eventos. Complementa IPT y conflictos sin afirmar causalidad.

**Riesgos.** Rezago entre declaración y publicación; diferencias entre punto y polígono; geometría de referencia no equivale al perímetro legal completo; posibles duplicados o cambios de código. La localización de inmuebles patrimoniales es pública, pero evitar enriquecer con datos personales de propietarios.

**Piloto mínimo recomendado.** Filtrar por `region = Metropolitana de Santiago` y las 32 comunas, validar diez registros contra ficha/decreto CMN y mantener por separado punto, polígono y acto declaratorio. No materializar toda la capa hasta fijar versión/fecha del servicio.

**Estado:** **Confirmado** para metadata y consulta pública de diez puntos; **candidato** para descarga completa y XLSX/KMZ del indicador; **excluido** el indicador web por 403.

## 4. Exclusiones y límites respetados

| Fuente o ruta | Decisión | Motivo y siguiente condición |
|---|---|---|
| SINIM | Excluida | No se usa por la restricción de licencia no comercial indicada para este encargo. No se llamó ni descargó. |
| ChileCompra API | Excluida | Requiere ticket/API key; no se llamó. Solo sería evaluable con credencial y autorización explícita. |
| SII/avalúos | Candidato no materializado | No se llamó un servicio autenticado ni se intentó acceder a microdatos; evaluar solo publicación oficial agregada o descarga explícitamente pública. |
| SNIFA/Drive | Catálogo confirmado, archivos no descargados | La página entrega carpetas públicas, pero no se verificó en esta ola una URL de archivo directo reproducible. No se usó login ni bypass. |
| CMN indicador XLSX/KMZ | Excluido | La URL pública respondió 403. Se conserva la referencia del catálogo y se usa el FeatureServer público como piloto alternativo. |
| BCN texto completo | Parcial | Ley Chile respondió el shell 200; el articulado es dinámico y no se forzó una API interna. Requiere mecanismo oficial/documentado de exportación o captura manual de ficha. |

## 5. Recomendación de integración futura

1. Promover F02 como fuente estructurada candidata para un piloto de permisos 2014–2026, manteniendo sus seis hojas, unidades y fecha de captura.
2. Promover el par F01b–F04 como evidencia normativa dual MINVU/Diario Oficial para un caso MPRMS-117; validar manualmente texto y plano antes de derivar eventos.
3. Mantener F05 como catálogo de descubrimiento hasta obtener un archivo SNIFA con URL directa, formato, fecha y hash.
4. Promover F06 como capa patrimonial versionada semestralmente, separando geometría de acto declaratorio y evitando asumir que diez registros representan el universo.
5. No incorporar ninguno de estos raws al snapshot de prensa ni a las capas derivadas sin un contrato de fuente/linaje y una revisión de licencia; este informe es evidencia de discovery, no una autorización de ingestión productiva.

## 6. Reproducibilidad local

La evidencia local se encuentra bajo:

`D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\agent_reviews\raw_fuentes_oficiales_20260913\`

La lista completa de archivos, tamaños y hashes está en la sección 2. No se ejecutaron scripts del pipeline ni se alteraron manifests, locks, snapshots o contratos.
