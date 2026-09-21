# Inventario de fuentes oficiales chilenas para el caso inmobiliario/urbano de Santiago

**Fecha:** 2026-09-13  
**Rol:** sweeper (investigación de fuentes, solo lectura)  
**Proyecto:** `consultora_caso_inmobiliario` — Provincia de Santiago, 32 comunas, 2014–2026  
**Estado:** informe de investigación; no se ejecutaron llamadas a APIs, scraping ni scripts del proyecto.

## 1. Criterio y alcance

El contrato vigente (`Trabajo/config/pipeline_contract_v2.yaml`) define cuatro ventanas (2014–2017, 2018–2020, 2021–2023 y 2024–2026), 32 comunas y conflicto inmobiliario/urbano en sentido amplio. Estas fuentes no reemplazan el corpus periodístico: aportan denominadores, contexto territorial, normativa, proyectos, vivienda, suelo y trazabilidad institucional.

**Confirmada** = la página institucional describe el dataset/servicio y su forma de acceso. **Candidata** = existe visor/catálogo o una referencia oficial, pero falta confirmar exportación masiva, licencia detallada, cobertura histórica o estabilidad de endpoint antes de incorporarla al pipeline. “Gratis” significa sin precio publicado; no implica autorización para sobrecargar servicios ni redistribuir microdatos.

## 2. Hallazgo sobre el repositorio solicitado

El repositorio [juanbrujo/listado-apis-publicas-en-chile](https://github.com/juanbrujo/listado-apis-publicas-en-chile) es un **índice comunitario**, no una fuente de datos ni garantía de vigencia. Su README declara licencia CC0-1.0 y lista, entre otros, API BCN, API Mercado Público, API CNE, API BDE, valores SII, SINCA, ARClim y servicios de mapas; también marca varios enlaces como `DEPRECATED`. Por tanto:

- sirve para descubrimiento inicial y para detectar candidatos;
- cada entrada debe validarse contra la institución propietaria (validación realizada aquí para las fuentes principales);
- no se debe usar su descripción como evidencia de cobertura, licencia o periodicidad;
- no se deben usar APIs de terceros listadas allí si no son oficiales o si tienen scraping/proxy (por ejemplo, servicios que el propio README no presenta como estatales).

## 3. Fuentes prioritarias confirmadas

### F-01 — INE: Censo de Población y Vivienda 2024

- **Institución / URL primaria:** Instituto Nacional de Estadísticas, [Resultados Censo 2024](https://censo2024.ine.gob.cl/resultados/) y [sitio Censo 2024](https://censo2024.ine.gob.cl/).
- **Dataset/API exacto:** Dashboard de indicadores; Dashboard geográfico; Visualizador Geográfico Manzana–Entidad; Redatam Web para procesar microdatos; síntesis descargable. El INE también centraliza capas del Censo en su [Portal de Mapas](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos).
- **Unidad y cobertura:** personas censadas, hogares y viviendas; nacional, región, provincia, comuna y, en el visualizador, manzana/entidad. Corte 2024, con comparación posible contra Censo 2017/2002 mediante productos separados.
- **Formato/acceso:** visualizadores web, tablas/síntesis y Redatam; el Portal de Mapas enlaza capas ArcGIS y descargas geográficas. Acceso público sin costo y sin API-key documentada para resultados agregados.
- **Licencia, periodicidad y costo:** datos oficiales del INE; usar con cita institucional y revisar las condiciones de cada descarga (no asumir una licencia única CC-BY). Censo decenal/operativo excepcional; no es una serie anual. Sin costo.
- **Valor para el proyecto:** denominadores para densidad, vivienda, hogares, hacinamiento, tenencia, migración y cambios 2017–2024; permite separar intensidad del conflicto de simple tamaño poblacional.
- **Riesgos:** cambio de límites/unidades censales; subcobertura o no respuesta; comparabilidad imperfecta entre censos; riesgo de inferencia ecológica; no exponer microdatos ni intentar reidentificación en manzana.
- **Piloto mínimo:** seleccionar las 32 comunas; descargar la tabla comunal y el diccionario; calcular población, viviendas, hogares, densidad y hacinamiento por comuna; guardar fecha de descarga, URL, versión y notas metodológicas. No llamar Redatam en producción todavía.

### F-02 — INE: geodatos de permisos y recepciones finales

- **Institución / URL primaria:** INE, [Geodatos Abiertos](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos).
- **Dataset exacto:** “Certificados de Recepción Final y Permisos de Edificación” (visor) y descargas “Certificado de Recepción Final Chile, años 2011–2020 (1er semestre)” y “Permisos de Edificación principales ciudades, años 2010–2020 (1er semestre)”.
- **Unidad y cobertura:** permiso/recepción y sus atributos espaciales; Chile, con detalle para ciudades/comunas según producto; cobertura histórica publicada principalmente 2010/2011–2020 (1er semestre).
- **Formato/acceso:** visor y descargas geográficas ArcGIS; acceso público gratuito; no se identificó una API versionada específica en la página.
- **Licencia, periodicidad y costo:** citar INE y conservar metadatos; periodicidad histórica/actualización por publicación, no necesariamente continua. Sin costo publicado.
- **Valor:** contraste independiente de permisos, recepciones y actividad edificatoria frente a noticias y series MINVU.
- **Riesgos:** producto acotado a un período antiguo; permiso no equivale a obra terminada ni ocupación; posibles diferencias de cobertura con DOM/MINVU.
- **Piloto mínimo:** comparar 2018–2020 para Santiago, Ñuñoa y Providencia con la serie MINVU F-07; verificar definiciones de unidad y duplicados antes de enlazar con casos.

### F-03 — Ministerio de Desarrollo Social y Familia: CASEN 2024

- **Institución / URL primaria:** Observatorio Social, [Encuesta CASEN 2024](https://observatorio.ministeriodesarrollosocial.gob.cl/encuesta-casen-2024); ficha de uso de bases en [BIDAT](https://bidat.gob.cl/details/ficha/dato/base-de-datos-casen-2024-spss).
- **Dataset exacto:** Base CASEN 2024 en Stata (`.dta`), SPSS (`.sav`) y R (`.RData`); bases de provincia/comuna; libros de códigos; cuestionario; diseño muestral y notas metodológicas. Incluye módulo de vivienda y nota técnica sobre campamentos.
- **Unidad y cobertura:** personas y hogares en viviendas particulares; resultados nacionales, regionales y, según base/producto, provincia/comuna. Trabajo de campo 2024-11-01 a 2025-02-02; series históricas desde 1990 con levantamientos no anuales (cada 2–3 años).
- **Formato/acceso:** descarga directa, CKAN/BIDAT y documentos PDF/XLSX. Acceso gratuito; la base es innominada. BIDAT identifica licencia Creative Commons Attribution–ES para el recurso publicado.
- **Licencia, periodicidad y costo:** atribución a MDSF/CASEN y al año; revisar nota de uso y libro de códigos. Periodicidad bienal/trienal, no anual. Sin costo.
- **Valor:** pobreza, ingresos, tenencia, arriendo/dividendo, servicios, hacinamiento, grupos vulnerables y desigualdad territorial para contextualizar conflictos y políticas de vivienda.
- **Riesgos:** error muestral y baja precisión en subgrupos/comunas; factores de expansión obligatorios; CASEN no es censo; la nota técnica advierte que no entrega representatividad estadística del universo de viviendas en campamentos; cambios metodológicos 2024 rompen comparaciones mecánicas.
- **Piloto mínimo:** usar base de comuna/provincia y códigos; producir para las 32 comunas estimaciones ponderadas de hacinamiento, tenencia y carga de vivienda >30% del ingreso, con intervalos/advertencia de precisión; contrastar con resultados publicados.

### F-04 — BCN: normativa, leyes y ordenanzas en Linked Open Data

- **Institución / URL primaria:** Biblioteca del Congreso Nacional, [documentación de normas](https://datos.bcn.cl/es/documentacion/normas), [Ley Chile](https://www.bcn.cl/leychile) y [catálogo de servicios](https://datos.bcn.cl/catalogo/).
- **Dataset/API exacto:** URIs de normas, versiones, relaciones (`modificada-por`, `refunde-a`), organismos, clasificaciones y consultas SPARQL. El catálogo también registra servicios REST de Ley Chile; la entrada “Últimas Leyes publicadas” requiere key.
- **Unidad y cobertura:** norma/version/relación, incluyendo leyes, decretos, reglamentos y ordenanzas municipales; cobertura histórica nacional, con fecha de publicación y fecha de versión.
- **Formato/acceso:** RDF/representaciones estructuradas y SPARQL para Linked Open Data; REST/XML en servicios que exigen key. Acceso LOD público y gratuito; API REST con registro/key.
- **Licencia, periodicidad y costo:** BCN declara reutilización de datos estructurados y formatos no propietarios; citar BCN y revisar términos del servicio concreto. Actualización por publicación/modificación normativa, no periódica fija. Sin costo publicado.
- **Valor:** línea de tiempo de LGUC/OGUC, DS19, decretos, leyes, ordenanzas y modificaciones; enlaza actores/instituciones y permite auditar si una afirmación periodística tiene norma y versión identificable.
- **Riesgos:** una norma vigente no prueba cumplimiento administrativo; diferencias entre publicación, entrada en vigor y consolidación; cobertura de ordenanzas puede depender de incorporación; posibles datos personales en documentos legales.
- **Piloto mínimo:** consultar LOD de ordenanzas de la Municipalidad de Santiago y normativa LGUC/OGUC 2014–2026; conservar URI, versión, fecha, tipo y hash del contenido; validar manualmente cinco normas contra Ley Chile antes de usar relaciones automáticas.

### F-05 — Datos.gob.cl: catálogo CKAN y Data API

- **Institución / URL primaria:** Gobierno de Chile / División de Gobierno Digital, [portal](https://datos.gob.cl/) y [documentación API de datos](https://datos.gob.cl/es/api/1/util/snippet/api_info_gobcl.html).
- **Dataset/API exacto:** API CKAN `package_search`, `package_show`, `datastore_search` y `datastore_search_sql`; el recurso documenta como endpoints de consulta `https://datos.gob.cl/api/3/action/datastore_search` y `.../datastore_search_sql`.
- **Unidad y cobertura:** dataset/recurso/registro; cobertura territorial y temporal dependen del organismo publicador. Incluye potencialmente municipios, MINVU, MDSF, transporte y obras.
- **Formato/acceso:** JSON CKAN/DataStore, además de CSV, XLSX, JSON, SHP u otros formatos por recurso; consultas públicas de lectura; acciones de creación/actualización requieren autenticación. Sin costo de lectura.
- **Licencia, periodicidad y costo:** licencia y periodicidad son **por dataset**, no globales; revisar ficha antes de reutilizar. Sin costo publicado para lectura.
- **Valor:** descubrimiento reproducible de datasets no encontrados en la navegación de cada ministerio y acceso estructurado sin scraping; posible fuente municipal.
- **Riesgos:** esquemas y URLs pueden cambiar; recursos duplicados, obsoletos o sin actualización; calidad heterogénea; no tratar presencia en el catálogo como garantía de completitud.
- **Piloto mínimo:** búsqueda CKAN de `MINVU`, `permisos de edificación`, `plan regulador`, `campamentos` y `Santiago`; revisar 20 fichas y registrar propietario, fecha, licencia, formato, última actualización y recurso descargable. No ingerir ningún recurso sin revisión.

### F-06 — IDE Chile / Geoportal: catálogo y geoservicios OGC

- **Institución / URL primaria:** Secretaría Ejecutiva SNIT/Bienes Nacionales, [IDE Chile](https://www.ide.cl/) y [Geoportal](https://geoportal.cl/geoportal/catalog?action=search).
- **Dataset/API exacto:** Catálogo Nacional de Información Geoespacial; servicios CSW de metadatos y servicios WMS/WFS de las instituciones proveedoras. El Geoportal ofrece fichas, capas, archivos y servicios; la guía oficial documenta URLs WMS/WFS y `GetCapabilities`.
- **Unidad y cobertura:** capa/feature/servicio; cobertura nacional, regional, comunal o temática, indicada por cada ficha; fechas de creación/actualización por metadato.
- **Formato/acceso:** WMS (imagen), WFS (vector), archivos GeoJSON/Shapefile/otros según proveedor; acceso web gratuito, generalmente sin API-key. La propia ficha solicita citar a la institución proveedora.
- **Licencia, periodicidad y costo:** proveedor y ficha determinan licencia/condiciones; actualización es institucional; servicios públicos y gratuitos no equivalen a permiso de redistribución ilimitada. Sin costo publicado.
- **Valor:** límites administrativos, IPT, campamentos, equipamiento, áreas de riesgo, ambiente, calles y otras capas para unir documentos/casos con territorio sin geocodificación improvisada.
- **Riesgos:** disponibilidad y esquema dependen del proveedor; WMS no entrega vector; CRS/datum y precisión pueden variar; límites referenciales; servicios pueden quedar fuera de línea.
- **Piloto mínimo:** buscar `plan regulador`, `campamentos`, `permisos`, `división comunal` y `Santiago`; elegir una capa WFS con metadatos completos, consultar solo el polígono de la Provincia de Santiago, registrar CRS/fecha/proveedor y validar 10 geometrías contra el límite oficial.

### F-07 — MINVU: Instrumentos de Planificación Territorial (IPT)

- **Institución / URL primaria:** MINVU, [Portal de Instrumentos de Planificación Territorial](https://www.minvu.gob.cl/elementos-tecnicos/portal-de-instrumentos-de-planificacion-territorial/) y [Portal IPT](https://portalipt.minvu.cl/).
- **Dataset exacto:** planes reguladores comunales/intercomunales/metropolitanos, procesos de elaboración/aprobación y modificaciones; los antecedentes son suministrados por municipalidades, gobiernos regionales y órganos competentes conforme a OGUC 2.1.6.
- **Unidad y cobertura:** instrumento, versión, zona/norma y modificación; comunas/regiones de Chile; fecha de aprobación/modificación. No es una única base tabular homogénea.
- **Formato/acceso:** visor, reportes y documentos/cartografía (frecuentemente PDF y capas); acceso público gratuito; no se confirmó API estable de descarga masiva.
- **Licencia, periodicidad y costo:** citar MINVU y municipio/proveedor; actualización cuando cambia el instrumento, sin periodicidad fija; verificar autorización de reutilización de cada plano/documento.
- **Valor:** altura, densidad, uso de suelo, áreas patrimoniales y cronología normativa; fuente primaria para interpretar disputas por permisos, modificaciones y reclamos de ilegalidad.
- **Riesgos:** versión publicada puede no ser la vigente o consolidada; datos municipales heterogéneos; mapa/ordenanza pueden requerir lectura jurídica; no inferir legalidad desde un visor sin revisar publicación oficial.
- **Piloto mínimo:** Santiago, Ñuñoa y Providencia: descargar instrumento vigente y dos modificaciones relevantes por comuna; construir una tabla de fecha–acto–zona–regla–URL y contrastar tres noticias del corpus.

### F-08 — MINVU: estadísticas de permisos de edificación

- **Institución / URL primaria:** Centro de Estudios Ciudad y Territorio, [repositorio de permisos](https://centrodeestudios.minvu.gob.cl/repositorio/categoria/permisos-de-edificacion/).
- **Dataset exacto:** “Viviendas unidades y superficie según año y comuna” (desde 2002 hasta la última actualización mensual); “Viviendas unidades y superficie según mes y comuna”; casas/departamentos por tramo de superficie; totales por agrupamiento y comuna; variación anual.
- **Unidad y cobertura:** unidades de vivienda y superficie asociada a permisos; comuna/mes/año; serie nacional y comunal desde 2002, con publicaciones mensuales y cierres anuales.
- **Formato/acceso:** fichas de catálogo MINVU con archivos descargables (normalmente XLSX/tabla); acceso gratuito; no se identificó API pública versionada.
- **Licencia, periodicidad y costo:** citar MINVU/Centro de Estudios y conservar fecha de descarga; actualización mensual/anual según producto; sin costo publicado.
- **Valor:** medida oficial de presión edificatoria y cambio de oferta; permite tasas por población/vivienda, comparación 2014–2026 y contraste con permisos/recepciones INE.
- **Riesgos:** permiso no equivale a inicio, término, venta u ocupación; revisiones y rezagos municipales; diferencias de clasificación casa/departamento; cambios territoriales.
- **Piloto mínimo:** descargar tablas anual y mensual; agregar las 32 comunas por año 2014–2026; comparar tres picos con el corpus y con F-02; registrar revisión de cifras y no atribuir causalidad.

### F-09 — MINVU: visor de proyectos habitacionales y urbanos (DS19/DS49)

- **Institución / URL primaria:** [Visor de Proyectos MINVU en el país](https://www.minvu.gob.cl/proyectos-minvu-en-el-pais/) y [página DS19](https://www.minvu.gob.cl/beneficio/vivienda/subsidio-de-integracion-social-y-territorial-ds19/).
- **Dataset exacto:** proyectos colectivos DS49 y DS19, además de obras urbanas, espacios públicos e intervenciones barriales; el visor georreferencia obras actualmente en ejecución y se actualiza periódicamente.
- **Unidad y cobertura:** proyecto/obra, programa, estado y localización; país/región/comuna; principalmente estado vigente/en ejecución, no necesariamente histórico completo.
- **Formato/acceso:** visor web; exportación/API no documentada en la página pública, por lo que el acceso programático es **candidato** hasta verificar metadatos o servicio subyacente. Sin costo de consulta.
- **Licencia, periodicidad y costo:** citar MINVU; actualización periódica sin calendario publicado; confirmar condiciones de descarga/redistribución.
- **Valor:** conecta casos de DS19 con proyecto, localización y obras públicas; permite separar política habitacional de desarrollo privado general.
- **Riesgos:** sesgo hacia proyectos activos; omite proyectos terminados/cancelados o con fichas incompletas; georreferenciación no prueba recepción ni integración social efectiva.
- **Piloto mínimo:** revisar manualmente la Región Metropolitana y 10 proyectos DS19/DS49; registrar nombre, programa, comuna, estado, coordenadas, fecha de consulta y enlace a ficha; no automatizar hasta confirmar exportación estable.

### F-10 — MINVU: Catastro Nacional de Campamentos 2024

- **Institución / URL primaria:** [Catastro de Campamentos MINVU](https://www.minvu.gob.cl/catastro-de-campamentos/) y servicio oficial [GeoIDE MINVU, capa Catastro campamentos 2024](https://geoide.minvu.cl/server/rest/services/Catastros/Catastros_campamentos/MapServer/0).
- **Dataset exacto:** capa ArcGIS `Catastros/Catastros_campamentos/MapServer/0`, “Catastro campamentos 2024”; levantamiento diciembre 2023–febrero 2024, basado en INE, TECHO e informantes institucionales/comunitarios.
- **Unidad y cobertura:** polígono de campamento; atributos de identificación/caracterización según capa; nacional, con consulta espacial por comuna/región. La capa declara JSON, GeoJSON y PBF y `maxRecordCount=2000`.
- **Formato/acceso:** ArcGIS REST, JSON/GeoJSON/PBF, sin costo publicado; no usar consulta masiva sin límites y respetar disponibilidad.
- **Licencia, periodicidad y costo:** el MINVU exige atribución y condiciones específicas para bases innominadas de catastros; confirmar las condiciones vigentes del producto 2024 antes de publicar derivados. Actualización por catastro/actualización, no serie anual garantizada.
- **Valor:** informalidad habitacional, localización de asentamientos y exposición a riesgos/servicios; contexto para conflictos de suelo y políticas habitacionales.
- **Riesgos:** estigmatización y privacidad territorial; cobertura depende de definición de campamento e informantes; corte 2024, no estado actual; no exponer hogares/personas ni convertir polígono en registro individual.
- **Piloto mínimo:** consultar solo polígonos de la Región Metropolitana, agregar conteos por comuna y contrastar con CASEN/INE; conservar metadatos, fecha y CRS; no descargar fichas personales.

### F-11 — SEA: proyectos sometidos al SEIA

- **Institución / URL primaria:** Servicio de Evaluación Ambiental, [Mapa de proyectos sometidos al SEIA](https://sig.sea.gob.cl/mapadeproyectos/) y [ArcGIS REST ProyectosSEIA](https://arcgisv11.sea.gob.cl/server/rest/services/WEBServices/ProyectosSEIA/MapServer/0).
- **Dataset/API exacto:** capa agrupada `ProyectosSEIA` con subcapas EIA y DIA; el servicio declara JSON, GeoJSON y PBF. La ficha de proyecto enlaza expediente/estado en SEIA.
- **Unidad y cobertura:** proyecto/actividad, tipo de evaluación, fecha de presentación, estado y localización representativa; nacional, filtrable por región; cobertura histórica según expediente disponible.
- **Formato/acceso:** visor y ArcGIS REST de lectura, acceso público y gratuito; la localización es representativa y validada por SEA, no necesariamente el polígono completo del impacto.
- **Licencia, periodicidad y costo:** citar SEA y mantener enlace al expediente; actualización por ingreso/cambio de proyecto, sin periodicidad fija; verificar términos de uso del servicio.
- **Valor:** proyectos urbanos/inmobiliarios con dimensión ambiental, participación ciudadana, RCA y controversias administrativas; enlazable con actores y cronologías del corpus.
- **Riesgos:** no todos los proyectos inmobiliarios entran al SEIA; estado puede cambiar; punto representativo no prueba huella; usar “ingresado/evaluado/aprobado” con categorías separadas.
- **Piloto mínimo:** filtrar Región Metropolitana, 2014–2026, nombres/tipologías urbanización, residencial, infraestructura urbana; seleccionar 10 proyectos y verificar ficha, DIA/EIA, RCA y participación antes de codificar.

### F-12 — ChileCompra: API de Mercado Público

- **Institución / URL primaria:** ChileCompra, [API de Mercado Público](https://www.chilecompra.cl/api/) / [api.mercadopublico.cl](https://api.mercadopublico.cl/).
- **Dataset/API exacto:** licitaciones, órdenes de compra, organismos compradores y proveedores; endpoints JSON/XML/JSONP, por fecha, estado, código de licitación, código de organismo/proveedor.
- **Unidad y cobertura:** licitación/orden/proveedor/comprador; más de 1.000 entidades; consultas diarias y por código, con datos en tiempo real según documentación. Histórico efectivo depende del endpoint/exportación.
- **Formato/acceso:** REST vía GET; gratuita y pública, pero requiere solicitar ticket y usar Clave Única para consumo. No usar ticket ajeno ni llamar masivamente.
- **Licencia, periodicidad y costo:** condiciones de uso de ChileCompra; acceso sin costo anunciado; actualización en tiempo real/diaria según consulta.
- **Valor:** contratos y compras públicas de municipios, MINVU/SERVIU y obras/estudios urbanos; identifica actores institucionales y cronologías de contratación.
- **Riesgos:** licitación no equivale a ejecución ni conflicto; cambios de estados/códigos; límites/rate limiting y ticket; datos de proveedores deben tratarse como información pública contextual, no perfil personal.
- **Piloto mínimo:** sin pedir ticket ni llamar API en esta fase; preparar una consulta para un organismo municipal y palabras clave `vivienda`, `urbanización`, `espacio público`, `plan regulador`; validar manualmente 10 resultados cuando el usuario autorice acceso.

### F-13 — Banco Central: API de Base de Datos Estadísticos (BDE)

- **Institución / URL primaria:** [API BDE](https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index_API_sec1_es.htm) y [acceso API](https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/acceso_api.html).
- **Dataset/API exacto:** series oficiales BDE, incluyendo UF, IPC, dólar observado, tasas y otras series; REST, SOAP o librería Python `bcchapi`.
- **Unidad y cobertura:** serie–período–valor; nacional; frecuencias diaria/mensual/anual según serie; cobertura histórica según código de serie.
- **Formato/acceso:** Web Service REST/SOAP/Python; requiere cuenta BDE y habilitar API key/token. Gratuito según la página, sin API de pago.
- **Licencia, periodicidad y costo:** términos BDE obligan a citar/verificar fuente; actualización según serie (diaria/mensual); sin costo publicado.
- **Valor:** deflactar avalúos/precios y contextualizar crédito/UF/inflación; no sustituye indicadores locales.
- **Riesgos:** confusión entre series nominales/reales, revisiones y cambios de base; correlación macro no demuestra causalidad comunal.
- **Piloto mínimo:** identificar códigos UF, IPC y tasa hipotecaria; documentar transformaciones y usar una tabla de factores 2014–2026. No llamar API sin credenciales/autoridad explícita.

### F-14 — SII: avalúos, rol y cartografía predial

- **Institución / URL primaria:** SII, [Consulta de antecedentes de un bien raíz](https://zeus.sii.cl/avalu_cgi/br/brc803.sh), [cartografía/FAQ](https://www.sii.cl/preguntas_frecuentes/aval_contrib_bbrr/001_165_8108.htm) y [Resolución 23/2024 sobre SII-Mapas](https://www.sii.cl/normativa_legislacion/resoluciones/2024/reso23.pdf).
- **Dataset/API exacto:** consultas por comuna–rol/dirección; certificados de avalúo; rol semestral; servicios OGC SII-Mapas de polígonos vigentes. La resolución documenta campos como comuna, manzana, predio, dirección, destino, ubicación, avalúo total/afecto.
- **Unidad y cobertura:** predio/rol y, en algunos servicios, transacción/avalúo; cobertura por comuna; valores fiscales vigentes y períodos de reavalúo/semestrales, no necesariamente serie histórica homogénea.
- **Formato/acceso:** web de consulta/certificados; WMS/WMTS OGC institucional. Acceso ciudadano por dirección/rol; la cartografía interoperable descrita en la resolución se entrega a instituciones autorizadas. No se confirmó un bulk API abierto a investigadores.
- **Licencia, periodicidad y costo:** fuente tributaria con condiciones y restricciones de uso; mapas son referenciales, deben citar SII-Mapas y no acreditan límites prediales/comunales; certificados/consultas pueden requerir autenticación. No asumir libre redistribución de propietarios/direcciones.
- **Valor:** proxy de valor fiscal/suelo, destino y morfología predial; útil para mercado de suelo y contraste con observatorios MINVU, no como precio comercial ni registro de propiedad.
- **Riesgos:** datos personales y secreto tributario; sesgo del avalúo fiscal frente al valor de mercado; cobertura/actualización; error de geolocalización; no usar nombres/RUT ni inferir titularidad.
- **Piloto mínimo:** una comuna y una dirección/rol de prueba, solo campos no personales (comuna, destino, superficie/avalúo si públicamente visible); verificar si existe exportación autorizada y registrar resultado “confirmado/candidato” antes de cualquier ampliación.

## 4. Priorización para el pipeline

1. **Primera ola, bajo riesgo y alto rendimiento:** F-01 Censo 2024, F-03 CASEN 2024, F-07 IPT, F-08 permisos MINVU, F-06 IDE Chile y F-11 SEIA. Son complementarias: denominadores sociales + norma + edificación + geografía + proyectos.
2. **Segunda ola, con revisión de términos:** F-04 BCN, F-05 Datos.gob.cl, F-10 Campamentos y F-09 visor de proyectos MINVU.
3. **Candidatas condicionadas por autorización/acceso:** F-14 SII (bulk/OGC), F-12 ChileCompra (ticket), F-13 BDE (token). No llamar APIs pagadas ni autenticadas en el estado actual.

## 5. Reglas de incorporación y límites

- Cada incorporación debe congelar URL primaria, fecha, metadatos, licencia, versión/fecha de actualización, CRS y hash del archivo o respuesta; no sobreescribir capturas previas.
- Separar **hecho de fuente**, **proxy analítico** e **interpretación**. Un permiso, proyecto SEIA o subsidio no prueba ejecución, impacto o conflicto.
- No mezclar periodos/unidades sin registrar cambios metodológicos y fronteras comunales; usar población/viviendas del Censo como denominador explícito.
- Mantener privacidad: no almacenar nombres, RUT, propietarios, direcciones individuales ni microdatos reidentificables; agregar a comuna/manzana solo cuando el tamaño y la fuente lo permitan.
- No hacer scraping de visores, no usar APIs de terceros del repositorio como autoridad, y no integrar ninguna fuente al pipeline productivo hasta terminar el piloto, revisar licencia y documentar cobertura/errores.

## 6. Evidencia web consultada

- [Repositorio comunitario de APIs públicas](https://github.com/juanbrujo/listado-apis-publicas-en-chile)
- [Resultados Censo 2024](https://censo2024.ine.gob.cl/resultados/) y [Geodatos INE](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos)
- [CASEN 2024](https://observatorio.ministeriodesarrollosocial.gob.cl/encuesta-casen-2024) y [BIDAT](https://bidat.gob.cl/details/ficha/dato/base-de-datos-casen-2024-spss)
- [BCN Linked Open Data](https://datos.bcn.cl/es/documentacion/normas)
- [API Datos.gob.cl](https://datos.gob.cl/es/api/1/util/snippet/api_info_gobcl.html)
- [IDE Chile](https://www.ide.cl/) y [Geoportal](https://geoportal.cl/geoportal/catalog?action=search)
- [MINVU IPT](https://www.minvu.gob.cl/elementos-tecnicos/portal-de-instrumentos-de-planificacion-territorial/), [mercado de suelo](https://www.minvu.gob.cl/observatorios-del-mercado-de-suelo-urbano/), [permisos](https://centrodeestudios.minvu.gob.cl/repositorio/categoria/permisos-de-edificacion/), [proyectos](https://www.minvu.gob.cl/proyectos-minvu-en-el-pais/), [campamentos](https://geoide.minvu.cl/server/rest/services/Catastros/Catastros_campamentos/MapServer/0)
- [SEA ProyectosSEIA REST](https://arcgisv11.sea.gob.cl/server/rest/services/WEBServices/ProyectosSEIA/MapServer/0)
- [API Mercado Público](https://www.chilecompra.cl/api/)
- [API BDE](https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index_API_sec1_es.htm)
- [SII-Mapas y resolución técnica](https://www.sii.cl/normativa_legislacion/resoluciones/2024/reso23.pdf)

