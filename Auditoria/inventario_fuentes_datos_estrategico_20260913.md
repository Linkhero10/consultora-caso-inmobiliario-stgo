# Inventario estratégico de datos para el proyecto inmobiliario/urbano de Santiago

**Fecha:** 2026-09-13  
**Proyecto:** `consultora_caso_inmobiliario`  
**Propósito:** identificar qué datos adicionales pueden incorporarse al trabajo de Felipe, Darío, Nicolás y Christian, sin reducir el proyecto a scraping de noticias.  
**Estado:** inventario y backlog de investigación. No es un cierre de etapa, no cambia `stage_roadmap.yaml`, no autoriza nuevas llamadas pagadas ni modifica `snapshot_v3`, `fulltext_v2`, locks o manifests de producción.

## 1. Respuesta ejecutiva

Sí podemos construir una base mucho más rica que un corpus periodístico. El producto potencial no es “clasificar noticias con IA”, sino una infraestructura socioterritorial auditable que conecta:

`documento → evidencia → evento → proyecto/caso/conflicto → actor/institución → territorio → análisis`

La prensa seguirá siendo una columna vertebral para descubrir casos, lenguaje público y secuencias narrativas. No debe ser el único universo probatorio. Las fuentes oficiales pueden aportar, según el caso:

- población, hogares, viviendas, hacinamiento y migración;
- permisos, recepciones, densidad edificatoria y proyectos habitacionales;
- planes reguladores, zonificación, normas y modificaciones;
- expedientes de evaluación ambiental, participación ciudadana, RCA, fiscalizaciones y sanciones;
- actas municipales, decretos, permisos, contratos y expedientes DOM;
- compras públicas, audiencias de lobby, dictámenes y sentencias;
- patrimonio, transporte, riesgos climáticos, contaminación, campamentos y servicios;
- redes observadas de actores e instituciones, con aristas documentadas;
- afirmaciones ESG/promesas y evidencia de cumplimiento o brecha evidencial.

El repositorio [listado-apis-publicas-en-chile](https://github.com/juanbrujo/listado-apis-publicas-en-chile) sirve como índice de descubrimiento. No es una autoridad de vigencia, cobertura, licencia ni calidad: su README marca algunas entradas como `DEPRECATED` y mezcla APIs oficiales, visores, proyectos comunitarios y wrappers. Cada fuente debe validarse en su institución propietaria antes de ingresar datos al proyecto.

## 2. Qué queda decidido y qué queda abierto

### Decidido

1. La investigación de fuentes se realiza ahora en modo read-only; la flota no ejecutó APIs, scraping, descargas ni llamadas pagadas.
2. Las fuentes complementarias son un corpus separado de la prensa. No se agregan registros al `snapshot_v3` ni se mezclan con la clasificación de etapa 1.
3. Todo registro externo debe conservar fuente primaria, URL/endpoint o archivo, fecha de captura, hash, licencia/condiciones, unidad espacial y temporal, y estado de verificación.
4. La cadena de evidencia conserva documentos y no permite que un agregado, mapa, grafo o salida de LLM reemplace la fuente original.
5. Los joins entre fuentes deben declarar si se hicieron por ID oficial, alias adjudicado, relación documental o proximidad espacial. “Parecido” no es una identidad.
6. No se habilitan todavía redes sociales, predicción, inferencia causal, SAOM/SIENA, monitoreo automático, SaaS, valor predial granular ni ranking legal/ESG.

### Abierto y requiere decisión posterior

- qué diez casos serán el piloto oficial;
- si se usarán fuentes con restricciones de uso comercial, especialmente SINIM;
- qué municipalidades y DOM tienen expedientes recuperables;
- qué fuentes tienen exportación masiva y licencia suficiente;
- cuándo se cierra humanamente la etapa 1 y se habilita el piloto de arcos.

## 3. Reglas de evidencia y datos

### 3.1 Tipos de aporte

Cada fuente debe etiquetarse como una o más de estas categorías:

- **Evidencia primaria de evento:** acta, permiso, RCA, sanción, sentencia, decreto, audiencia o documento fechado.
- **Evidencia primaria de objeto:** expediente, proyecto, titular institucional, instrumento, polígono o norma.
- **Contexto territorial:** población, vivienda, transporte, equipamiento, riesgo o contaminación.
- **Denominador/medida:** población, hogares, viviendas, superficie, unidades autorizadas, presupuesto.
- **Descubrimiento:** catálogo, buscador o índice que ayuda a encontrar la fuente, pero no prueba por sí solo el hecho.
- **Fuente derivada o auxiliar:** OSM, Wikidata, geocodificación, imágenes satelitales o agregadores; sirven para orientación o análisis espacial, no para sustituir una fuente primaria.

### 3.2 Contrato mínimo para cada captura

Todo dataset, archivo, capa, consulta o documento debe tener como mínimo:

```text
source_id
publisher
source_url
endpoint_or_file
dataset_name
dataset_version_or_last_modified
retrieved_at
sha256
license_or_terms
coverage_spatial
coverage_temporal
spatial_unit
temporal_unit
official_ids_available
pii_or_secrecy_risk
evidence_role
join_method
validation_status
human_review_status
```

Para documentos y eventos se agregan `document_id`, `evidence_id`, `event_id`, `project_id`, `case_id`, `actor_id`, `institution_id`, `territory_id`, `linea_tiempo[]`, `source_locator` y `literal_quote_safe` cuando corresponda.

### 3.3 Regla de temporalidad

Nunca se debe usar la fecha de publicación como fecha del hecho sin evidencia. Se deben separar al menos:

`fecha_del_hecho`, `fecha_del_acto`, `fecha_de_publicacion`, `fecha_de_vigencia`, `fecha_de_captura`, `fecha_de_actualizacion`.

En normas, IPT, permisos, expedientes y decisiones, la pregunta correcta es qué versión estaba vigente en la fecha del evento.

## 4. Catálogo de fuentes priorizadas

Las etiquetas son deliberadamente conservadoras:

- **P0:** habilitante para el primer caso integrado, después del cierre de etapa 1.
- **P1:** aumenta robustez, contraste institucional o valor de portafolio.
- **P2:** producto posterior o investigación metodológica; no comprometer ahora.
- **Confirmada:** la institución describe el dataset/servicio y su acceso.
- **Candidata:** falta probar descarga, cobertura histórica, licencia o estabilidad del endpoint.

### 4.1 Demografía, vivienda y contexto social

| Fuente | Estado/prioridad | Qué se puede obtener | Unidad/joins | Riesgos y límite |
|---|---|---|---|---|
| [INE Censo 2024](https://censo2024.ine.gob.cl/resultados/) y [Portal de Mapas](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos) | Confirmada / P0 | Población, hogares, viviendas, hacinamiento, tenencia, migración, densidad; visualizador comunal y manzana-entidad | comuna, área, manzana/entidad; códigos y geometrías INE cuando estén disponibles | No es serie anual; cambios de unidad y límites; riesgo de inferencia ecológica y reidentificación en escalas finas. Usar agregados y notas metodológicas |
| [CASEN 2024](https://observatorio.ministeriodesarrollosocial.gob.cl/encuesta-casen-2024) / [BIDAT](https://bidat.gob.cl/) | Confirmada / P1 | pobreza, ingresos, arriendo, tenencia, vivienda, servicios, grupos vulnerables | hogares/personas y estimaciones comuna/provincia según base; requiere factores de expansión | Encuesta, no censo; error muestral y baja precisión en subgrupos; reportar intervalos y no usar para afirmar condiciones de un proyecto específico |
| [SIEDU/SIET-Chile](https://www.siet-chile.cl/) | Confirmada / P0-P1 | acceso a servicios, movilidad, vivienda, integración social, medio ambiente y calidad urbana | comuna/ciudad/territorio y año; crosswalk con comuna y capas | Cambios de denominador, cobertura y definición; contexto, no explicación causal |
| [SINIM/SUBDERE](https://datos.sinim.gov.cl/datos_municipales.php) | Confirmada / P1 con revisión de licencia | finanzas, gestión municipal, servicios, desarrollo territorial y series comunales | municipio-indicador-año | El portal declara uso pertinente sin fines comerciales y exige citar; no usar para la consultora sin revisar autorización específica. “No recepcionado” no equivale a cero |
| [CEAD/SIED y ENUSC](https://cead.spd.gov.cl/) | Confirmada / P1 | delitos, denuncias, tasas, encuestas de victimización y seguridad comunal | comuna/año, hechos agregados | No usar como atributo de un proyecto o comunidad; tasas y población de referencia deben conservarse |
| [SERVEL, datos electorales](https://www.servel.cl/) | Confirmada / P1 | resultados, participación, candidaturas, aportes y gastos electorales publicados | local de votación/comuna/circunscripción, elección y candidato | No inferir preferencias de un conflicto particular ni perfilar personas; revisar corte y auditoría de cada elección |

### 4.2 Urbanismo, suelo, permisos y proyectos habitacionales

| Fuente | Estado/prioridad | Qué se puede obtener | Unidad/joins | Riesgos y límite |
|---|---|---|---|---|
| [MINVU Portal IPT](https://www.minvu.gob.cl/elementos-tecnicos/portal-de-instrumentos-de-planificacion-territorial/) / [Portal IPT](https://portalipt.minvu.cl/) | Confirmada / P0 | PRC, PRI/PRM, zonificación, memorias, ordenanzas, planos, actos de aprobación y modificaciones | instrumento-comuna-zona-acto-fecha; vínculo a norma y polígono | Versiones heterogéneas, PDF escaneado y geometría referencial; no afirmar legalidad sin revisar acto y vigencia |
| [MINVU permisos de edificación](https://centrodeestudios.minvu.gob.cl/repositorio/categoria/permisos-de-edificacion/) | Confirmada / P0 | viviendas, unidades, superficie, casa/departamento, comuna, mes/año desde series históricas | comuna-mes/año-destino; join contextual a casos | Permiso no equivale a obra, venta, ocupación o conflicto; rezagos y cambios de definición |
| [INE permisos y recepciones geográficas](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos) | Confirmada / P0 | certificados de recepción final y permisos históricos, principalmente 2010–2020 | obra/comuna/área/geometría según producto | Cobertura histórica acotada; INE retira identificadores cuando podrían reidentificar informantes; no reconstruir números eliminados |
| [MINVU proyectos DS19/DS49](https://www.minvu.gob.cl/proyectos-minvu-en-el-pais/) | Confirmada como visor, exportación candidata / P0-P1 | proyectos habitacionales, obras urbanas, estado, programa y localización | proyecto-programa-comuna-coordenada-estado | Puede omitir terminados/cancelados; no automatizar hasta confirmar exportación y licencia |
| [MINVU Catastro de Campamentos 2024](https://www.minvu.gob.cl/catastro-de-campamentos/) / [GeoIDE](https://geoide.minvu.cl/server/rest/services/Catastros/Catastros_campamentos/MapServer/0) | Confirmada / P1 | polígonos y atributos agregados de campamentos | polígono-comuna-región-fecha; join espacial | No exponer hogares/personas; riesgo de estigmatización; corte 2024 no es estado actual |
| [Observatorios de mercado de suelo urbano MINVU](https://www.minvu.gob.cl/observatorios-del-mercado-de-suelo-urbano/) | Confirmada/candidata / P1 | indicadores y mapas agregados de valor de suelo basados en transacciones SII, IPT y módulos del portal | territorio-indicador-fecha; join con comuna/zonificación | Proxy agregado, no precio predial ni registro de transacciones; no inferir titularidad o valor comercial individual |
| [IDE Chile](https://www.ide.cl/) y [Geoportal](https://geoportal.cl/geoportal/catalog?action=search) | Confirmada / P0 | catálogo, WMS/WFS, CSW, límites, equipamiento, riesgos, usos de suelo y capas sectoriales | capa-feature-polígono/punto, CRS, proveedor y fecha | WMS es imagen, WFS depende del proveedor; licencias y actualización son por capa; registrar CRS y metadatos |
| [datos.gob.cl / CKAN](https://datos.gob.cl/) | Confirmada como catálogo / P1 | descubrimiento de datasets y DataStore de organismos públicos | dataset/resource/record; `package_id`, `resource_id` | Calidad y licencia varían por recurso; no ingerir solo porque aparece en el catálogo |

### 4.3 Evidencia ambiental y territorial

| Fuente | Estado/prioridad | Qué se puede obtener | Unidad/joins | Riesgos y límite |
|---|---|---|---|---|
| [SEA/e-SEIA](https://www.sea.gob.cl/evaluacion-ambiental/informacion-linea-base-eia) / [mapa de proyectos](https://sig.sea.gob.cl/mapadeproyectos/) | Confirmada / P0 cuando aplique | proyectos, titulares, DIA/EIA, RCA, pertinencia, expediente, PAC, observaciones, fechas | expediente/proyecto/RCA/titular/comuna/documento; alta utilidad para eventos y actores | No todos los proyectos urbanos entran al SEIA; punto representativo no es polígono de impacto; expedientes pueden contener PII |
| [SMA/SNIFA](https://snifa.sma.gob.cl/DatosAbiertos) | Confirmada / P1 | fiscalizaciones, cargos, sanciones, seguimiento y unidades fiscalizables | unidad fiscalizable-expediente-RCA-sanción-fecha | Datos reportados pueden no estar verificados; separar reportado, fiscalizado y sancionado; procedimientos en curso pueden no aparecer |
| [ARClim](https://arclim.mma.gob.cl/) | Confirmada / P1 | amenaza, exposición, sensibilidad y riesgo climático, capas GeoJSON/SHP/GeoTIFF/Excel | comuna, grilla, ciudad, cadena de impacto, escenario | Proyecciones no son hechos observados; conservar escenario, resolución y horizonte |
| [SINCA](https://sinca.mma.gob.cl/) | Confirmada / P1 | estaciones, contaminantes, meteorología y series históricas | estación-hora/día-contaminante; join espacial-temporal | Calidad, faltantes y representatividad; no imputar causalidad de un proyecto a una estación |
| DMC/Climatología | Candidata / P2 | precipitación, temperatura, estaciones y climatología | estación-fecha-medición | Confirmar endpoint, licencia, continuidad y utilidad antes de incorporar |
| DGA/agua y derechos de aprovechamiento | Candidata / P1 en conflictos pertinentes | derechos, caudales, expedientes y eventos hídricos | expediente/curso/cuenca/derecho/fecha | Puede tener complejidad jurídica, escalas distintas y PII; solo cuando el caso lo requiera |
| [Consejo de Monumentos Nacionales](https://www.monumentos.gob.cl/indicadores-sobre-monumentos-nacionales) / [Geoportal](https://www.monumentos.gob.cl/geoportal) | Confirmada / P0 cuando aplique | monumentos, zonas típicas, santuarios, decretos, planimetría, fotos, XLSX/KMZ y geometrías | monumento/decreto/polígono/fecha; superposición con proyecto/PRC | Fecha de decreto no es fecha del conflicto; localizaciones arqueológicas sensibles requieren cautela |

### 4.4 Decisión institucional, contratación y justicia

| Fuente | Estado/prioridad | Qué se puede obtener | Unidad/joins | Riesgos y límite |
|---|---|---|---|---|
| Portal de Transparencia y transparencia municipal | Confirmada como canal / P0 | actas, decretos, resoluciones, permisos, contratos, órdenes, expedientes y respuestas | documento/acto/municipio/solicitud/fecha; relación manual a proyecto/caso | Portales heterogéneos, faltantes, reservas y PII; ausencia de un documento no prueba ausencia del acto |
| DOM municipales | Candidato prioritario / P0 para casos seleccionados | permisos, anteproyectos, fusiones, subdivisiones, recepciones, certificados, observaciones y resoluciones | expediente/acto/predio/proyecto/fecha | No hay esquema nacional; digitalización y acceso varían; pedir primero índice y metadatos, no barrer todos los PDFs |
| [BCN/LeyChile](https://www.bcn.cl/leychile) / [datos.bcn.cl](https://datos.bcn.cl/es/documentacion/normas) | Confirmada / P0 | leyes, LGUC/OGUC, DS19, decretos, ordenanzas, versiones y relaciones normativas | norma/artículo/versión/fecha/vigencia | Texto vigente no siempre es el texto aplicable a la fecha del hecho; norma no prueba cumplimiento |
| [Diario Oficial](https://www.diariooficial.interior.gob.cl/presente/) | Confirmada / P0 | publicación oficial de leyes, decretos, resoluciones, avisos y actos | edición/sección/CVE/fecha; crosswalk con BCN | Alto volumen y PII societaria; conservar condiciones de uso y localizar exactamente la publicación |
| [Contraloría General](https://www.cgr.cl/) | Confirmada / P1 | dictámenes, oficios, informes y control de legalidad | dictamen/organismo/materia/fecha | Dictamen interpreta o controla; no reemplaza expediente ni prueba que todos los casos sean iguales |
| [Poder Judicial/Jurisprudencia](https://juris.pjud.cl/) | Base confirmada, extracción candidata / P1 | sentencias, roles, tribunales, materias, normas y textos | causa/sentencia/rol/tribunal/fecha | Sesgo hacia litigios; causas en curso y autenticación; no extraer RUT, domicilios ni perfilar partes |
| [ChileCompra/Mercado Público](https://www.chilecompra.cl/api/) | Confirmada, acceso a verificar / P1 | licitaciones, órdenes de compra, organismos, proveedores y contratos | código licitación/OC/organismo/proveedor/fecha | Compra no prueba influencia ni conflicto; ticket/ratelimit y campos personales; revisar condiciones de API |
| [Ley de Lobby](https://www.leylobby.gob.cl/) | Portal confirmado, endpoint candidato / P1 | audiencias, viajes, donativos y sujetos pasivos | audiencia/institución/actor/fecha/materia | Registro legalmente acotado; ausencia no prueba ausencia de gestión; revisar homónimos, PII y mantenimiento |

### 4.5 Transporte, servicios y fuentes auxiliares

| Fuente | Estado/prioridad | Qué se puede obtener | Unidad/joins | Riesgos y límite |
|---|---|---|---|---|
| [DTPM/Red Movilidad GTFS](https://dtpm.cl/index.php/gtfs-vigente) | Confirmada / P1 | paradas, rutas, horarios, programas de operación y accesibilidad | `stop_id`, `route_id`, feed/version, geometría; join espacial 500 m | Oferta no equivale a uso real; feed vigente no reconstruye automáticamente historia; algunos servicios requieren credenciales |
| Transporte Informa/UOCT | Confirmada/candidata / P1 | incidentes, desvíos, obras y avisos fechados | aviso/segmento/fecha/URL | Puede no haber archivo histórico estable; publicación no prueba impacto |
| [SINCA](https://sinca.mma.gob.cl/) | Confirmada / P1 | aire y meteorología, como contexto | estación/medición/hora | No atribuir contaminación a un proyecto sin diseño y evidencia independiente |
| OSM/Overpass | Auxiliar, no fuente probatoria / P2 | calles, POI, equipamiento y red vial como apoyo cartográfico | `osm_id`, geometría, `version`, licencia ODbL | Cambios de cobertura y voluntariado; respetar límites de API y atribución; contrastar con IDE/organismo |
| Sentinel-2/Landsat/Copernicus | Auxiliar / P2 | cambios de cobertura, superficies construidas, vegetación, agua y series de imágenes | escena/fecha/pixel/polígono; join espacial-temporal | Requiere procesamiento, validación y control de nubes; no convierte imagen en permiso o prueba legal |
| Wikidata/Geonames/geocodificadores | Auxiliar / P2 | alias, coordenadas aproximadas y resolución de nombres | entidad/URI/coordenada | No usar como autoridad de titularidad, legalidad o decisión; revisar licencia y errores |
| APIs del repositorio comunitario | Índice / no fuente | descubrir BCN, Mercado Público, BDE, CNE, SINCA, ARClim, transporte, etc. | registrar la entrada como `discovery_source` | La entrada puede estar obsoleta, ser un wrapper o marcarse deprecated; siempre volver a la fuente propietaria |

## 5. Qué aporta cada colega y qué datos necesita

### Felipe: corpus, clasificación, tópicos, mapa y dashboard

Necesita cerrar primero el corpus y luego producir el crosswalk `project_id`/`case_id`. Los datos más valiosos son:

1. noticias y documentos con citas y lineage;
2. proyectos, alias, comuna, localización y fechas múltiples;
3. IPT/PRC, permisos, recepciones y capas IDE;
4. Censo 2024, SIEDU/SIET y permisos como denominadores/contexto;
5. evidencia de cada claim que llegue al mapa, tópico o dashboard.

Producto mínimo: un caso end-to-end donde cada punto del mapa abre la evidencia, y donde se distingue “valor de suelo” de “proxy agregado”, “fecha de publicación” de “fecha del hecho” y “contexto” de “prueba”.

### Darío: redes de actores, multiafiliación, centralidad y ERGM

Necesita un diccionario de actores y una red observada, no una red inferida libremente:

- `actor_id`, alias y tipo de nodo;
- `institution_id`, cargo y vigencia;
- arista tipificada: firma, audiencia, aprobación, objeción, citación, representación, contrato o coaparición;
- fecha/intervalo, dirección, peso y `evidence_id`;
- frontera de red y denominador explícitos;
- dos olas si se quiere afirmar cambio temporal.

Las fuentes más fuertes para esto son expedientes SEA/municipales, normas, lobby, compras, sentencias y documentos del corpus. Una coaparición de prensa puede ser una arista de coaparición, pero no demuestra relación social, coordinación ni poder causal.

### Nicolás: institucionalidad, regulación y decisiones

Necesita reconstruir quién podía decidir, qué hizo, bajo qué norma y en qué fecha:

- BCN/LeyChile y Diario Oficial para la línea normativa versionada;
- IPT/PRC y modificaciones;
- actas, decretos, permisos y expedientes DOM;
- SEA/RCA/PAC cuando el proyecto entra al SEIA;
- CGR y Poder Judicial para interpretaciones, controles y litigios;
- ChileCompra/Lobby como contexto institucional, nunca como prueba automática de influencia;
- entrevistas solo con consentimiento, anonimización y protocolo propio.

### Christian: evidencia, ESG y anti-greenwashing

Necesita separar la promesa de la prueba:

- `claim_id`, emisor, objeto, fecha y cita literal;
- clase de evidencia: declarativa, cumplimiento institucional, desempeño medido;
- obligación, estándar, unidad, método, resultado y verificador;
- contradicciones, rectificaciones y faltantes;
- estados `supported`, `contradicted`, `unresolved` y `not_publicly_verifiable`.

No se debe llamar “greenwashing”, ilegalidad o incumplimiento solo porque no exista un documento público. En este proyecto, la salida prudente es “brecha evidencial/no verificado” salvo que exista base jurídica y documental suficiente.

## 6. Arquitectura de datos propuesta

### 6.1 Capas separadas

1. **Fuentes brutas:** archivos, respuestas API, HTML/PDF, capas geográficas, imágenes; inmutables y con hash.
2. **Índices de fuente:** metadatos, IDs oficiales, fechas, cobertura, licencia, errores y estado de acceso.
3. **Evidencia normalizada:** documentos, citas, tablas, geometrías y mediciones con localizador reproducible.
4. **Entidades adjudicadas:** proyectos, casos, actores, instituciones, territorios y normas; cada adjudicación humana debe conservar decisión y motivo.
5. **Eventos:** permiso, denuncia, aprobación, audiencia, PAC, RCA, sanción, sentencia, cambio normativo, obra, ocupación o declaración.
6. **Análisis:** tópicos, mapa, red, indicadores, comparaciones y dashboard; nunca reemplaza las capas 1–5.

### 6.2 IDs y joins

- `document_id`: hash/ID local de documento.
- `source_record_id`: ID del registro en la fuente primaria.
- `project_id`: entidad adjudicada; puede tener alias y lista explícita de no correspondencias.
- `case_id`: unidad analítica; no es sinónimo de proyecto.
- `event_id`: hecho o acto con una o más fechas.
- `actor_id`/`institution_id`: nodos con tipo, alias, cargo y vigencia.
- `territory_id`: comuna, manzana, polígono, estación o zona, con CRS y fecha.
- `claim_id`/`evidence_id`: afirmación y soporte, respectivamente.

Métodos de join permitidos: ID oficial; relación explícita en documento; alias adjudicado manualmente; o join espacial con tolerancia, CRS, fecha y validación. Debe existir un valor `no_match` o `unresolved`; no forzar coincidencias.

## 7. Plan de incorporación por olas

### Ola 0 — ahora, sin tocar producción

- congelar este inventario y los tres informes de la flota;
- escoger diez casos candidatos sin reabrir el discovery;
- construir matriz de cobertura/viabilidad/licencia, no descargar todavía;
- documentar el costo estimado de cada piloto y si requiere ticket, autenticación o solicitud de transparencia.

### Ola 1 — primer piloto oficial, después del cierre humano de etapa 1

Para un solo caso con prensa y expediente:

1. IPT/PRC y acto municipal;
2. permiso/recepción INE o MINVU;
3. acta/expediente DOM o transparencia;
4. BCN/Diario Oficial para norma y vigencia;
5. SEA/PAC, CMN o SMA solo si el caso los requiere;
6. una capa INE/Censo y una capa IDE como contexto.

**Aceptación:** 10–20 documentos, 5–10 eventos, 20 actores potenciales, 10 aristas, una norma versionada, una decisión institucional y una vista integrada que un segundo revisor pueda reconstruir sin leer el chat.

### Ola 2 — robustez de los arcos

- tres municipalidades o comunas contrastadas;
- ChileCompra y Lobby como contexto institucional;
- CGR/Poder Judicial para casos que llegaron a control o litigio;
- DTPM/GTFS, SIET/SIEDU, CASEN y ARClim como contexto comparativo;
- 3–5 entrevistas si Nicolás consigue acceso y consentimiento;
- auditoría de 3–5 proyectos con marco de Christian.

### Ola 3 — productos avanzados, solo con nueva decisión

- dos o más olas de red para análisis temporal;
- Sentinel/Landsat y cambios territoriales;
- series ambientales más densas;
- producto de monitoreo recurrente;
- SAOM/SIENA, predicción o alertas;
- datos de suelo más granulares bajo licencia autorizada;
- expansión a otros sectores o territorios.

## 8. Qué no conviene hacer

- No barrer todas las APIs del repositorio comunitario.
- No descargar microdatos o capas finas “por si acaso”.
- No asumir que un visor tiene API o permiso de redistribución.
- No usar una entrada de CKAN, un agregador, OSM o una noticia como prueba primaria si existe el documento propietario.
- No mezclar datos de ventanas temporales o contratos distintos.
- No convertir ausencia de registro en evidencia de ausencia del hecho.
- No usar SINIM con fines comerciales sin resolver su condición de uso.
- No recolectar RUT, domicilios, teléfonos, correos o firmas personales si no son indispensables.
- No correr extracción masiva en un portal municipal o API sin piloto, rate limit, registro de errores y aprobación.
- No llamar a Sol automáticamente. Sol solo se convoca con autorización explícita de Felipe; una diferencia de modelos no habilita por sí sola esa escalada.

## 9. Criterios para decidir si una fuente entra

Una fuente puede pasar de inventario a piloto solo si responde afirmativamente, con evidencia, a:

1. ¿Es primaria o está claramente identificada como auxiliar?
2. ¿Tiene cobertura útil para las 32 comunas o para el caso piloto?
3. ¿Su unidad y período pueden alinearse con el caso?
4. ¿Existe ID, URL, expediente, coordenada o localizador reproducible?
5. ¿La licencia/condiciones permiten el uso previsto, especialmente comercial?
6. ¿Se puede capturar un hash y una fecha de corte?
7. ¿Se puede separar contexto de evidencia probatoria?
8. ¿Los riesgos de PII, secreto, sesgo y reidentificación están controlados?
9. ¿El costo/tiempo de extracción es proporcional al valor?
10. ¿Un segundo revisor podría reconstruir el resultado?

Si alguna respuesta crítica es “no sé”, el estado queda `candidato`, no `confirmado para producción`.

## 10. Prioridad final recomendada

### P0 — primer caso integrado

1. Censo 2024/INE geodatos y permisos.
2. MINVU IPT y permisos.
3. Portal de Transparencia + dos DOM.
4. BCN/LeyChile + Diario Oficial.
5. IDE Chile para límites y capas de control.
6. SEA/e-SEIA, CMN o SMA cuando el caso lo justifique.

### P1 — contraste y portafolio

1. CASEN 2024, SIET/SIEDU y DTPM/GTFS.
2. CGR y Poder Judicial.
3. ChileCompra y Ley de Lobby.
4. SINIM, solo tras resolver licencia comercial.
5. ARClim, SINCA, DGA y SERVEL según hipótesis.

### P2 — posterior

OSM como auxiliar, Sentinel/Landsat, DMC, redes sociales, satélite avanzado, valor predial granular, entrevistas fuera del caso piloto, SAOM/SIENA, predicción, SaaS y monitoreo.

## 11. Artefactos que respaldan este inventario

- `Auditoria/agent_reviews/inventario_fuentes_oficiales_20260913.md`
- `Auditoria/agent_reviews/inventario_fuentes_territoriales_20260913.md`
- `Auditoria/agent_reviews/inventario_integracion_arcos_20260913.md`
- `Trabajo/config/stage_roadmap.yaml`
- `Trabajo/config/pipeline_contract_v2.yaml`
- `Trabajo/config/protocolo_revision_multiagente.md`
- `backlog_estrategico_socioterritorial.md`

Los informes de los agentes son revisiones de solo lectura. Este documento los integra; no los reemplaza.

## 12. Fuentes web primarias y de descubrimiento revisadas

- [Repositorio comunitario de APIs públicas en Chile](https://github.com/juanbrujo/listado-apis-publicas-en-chile) — índice CC0, no autoridad de vigencia.
- [Resultados Censo 2024](https://censo2024.ine.gob.cl/resultados/) y [geodatos INE](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos).
- [CASEN 2024](https://observatorio.ministeriodesarrollosocial.gob.cl/encuesta-casen-2024).
- [IDE Chile](https://www.ide.cl/) y [Geoportal](https://geoportal.cl/geoportal/catalog?action=search).
- [MINVU Portal IPT](https://www.minvu.gob.cl/elementos-tecnicos/portal-de-instrumentos-de-planificacion-territorial/), [permisos](https://centrodeestudios.minvu.gob.cl/repositorio/categoria/permisos-de-edificacion/) y [campamentos](https://www.minvu.gob.cl/catastro-de-campamentos/).
- [SEA/e-SEIA](https://www.sea.gob.cl/evaluacion-ambiental/informacion-linea-base-eia) y [mapa de proyectos](https://sig.sea.gob.cl/mapadeproyectos/).
- [BCN/LeyChile](https://www.bcn.cl/leychile) y [datos.bcn.cl](https://datos.bcn.cl/es/documentacion/normas).
- [Portal de Transparencia](https://www.portaltransparencia.cl/PortalPdT/), [ChileCompra](https://www.chilecompra.cl/api/) y [Ley de Lobby](https://www.leylobby.gob.cl/).
- [SMA/SNIFA](https://snifa.sma.gob.cl/DatosAbiertos), [CMN](https://www.monumentos.gob.cl/indicadores-sobre-monumentos-nacionales), [DTPM GTFS](https://dtpm.cl/index.php/gtfs-vigente), [ARClim](https://arclim.mma.gob.cl/), [SINCA](https://sinca.mma.gob.cl/) y [SINIM](https://datos.sinim.gov.cl/datos_municipales.php).

