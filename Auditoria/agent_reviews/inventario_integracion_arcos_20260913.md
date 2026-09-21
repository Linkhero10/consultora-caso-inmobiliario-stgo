# Inventario de integración de arcos y fuentes públicas

**Proyecto:** `consultora_caso_inmobiliario`  
**Fecha:** 2026-09-13  
**Rol:** auditoría/read-only de integración estratégica  
**Alcance:** todo el proyecto (etapas 2–4), sin ejecutar scraping, APIs, entrevistas ni cambios de producción.

## 1. Resultado ejecutivo

La arquitectura que permite integrar el caso sin perder trazabilidad es:

`documento/evidencia → evento → caso/conflicto → análisis`

El documento original, su URL/archivo, hash, fecha de captura y `lineage` siguen siendo la fuente. Eventos, casos, actores, grafos, tópicos, scores y dashboards son capas derivadas. Esto coincide con el backlog estratégico y no autoriza ampliar el discovery actual.

Hallazgos principales:

1. **Hay insumos públicos suficientes para un piloto P0** de los cuatro arcos, pero no existe un identificador universal de proyecto inmobiliario. Se debe crear un `project_id` local y una tabla de correspondencias; no forzar joins por nombre.
2. **Las fuentes más valiosas son oficiales y heterogéneas:** MINVU/Portal IPT, INE Geodatos, SEA/e-SEIA, BCN/Ley Chile, Diario Oficial, municipalidades/Transparencia, ChileCompra, Ley de Lobby, SMA/SNIFA y CMN. Su acceso es mayormente público, pero no tienen un contrato único de licencia, cobertura, frecuencia ni API.
3. El **faltante técnico transversal** es una capa de entidades y eventos con intervalos temporales (`linea_tiempo`, no una sola `fecha_evento`), IDs de fuente, localizadores, incertidumbre, estado de verificación y clasificación PII.
4. **Darío necesita red observada y repetida**, no solo coocurrencias de prensa. Un SNA exploratorio es factible P0/P1; ERGM exige una frontera de red y controles; SAOM queda P2 hasta disponer de varias olas comparables.
5. **Nicolás requiere documentos de decisión** (actas, expedientes, normas vigentes/versionadas) y entrevistas con consentimiento. La prensa no sustituye esos documentos.
6. **Christian debe auditar afirmaciones verificables, no declarar ilegalidad o “greenwashing” por un score.** La salida correcta es `afirmación → estándar/criterio → evidencia → brecha → estado de verificación`.
7. El **cierre comercial** necesita evidencia del caso y conversaciones prospectivas anonimizadas; no necesita una API CRM ni datos personales de actores para validar la oferta.

La etapa 1 sigue bloqueada por sus gates documentados. La expansión solo debe activarse después del acta humana de cierre de `stage_1_corpus`.

## 2. Base documental y límites de alcance

| Fuente local | Evidencia usada | Implicancia |
|---|---|---|
| `constitucion_consultora.html` §9 | Arco 0/base de Felipe; Darío (SNA/ERGM); Nicolás (normativa, decisiones, expediente vs prensa); Christian (auditoría de evidencia); cierre mapa+tópicos+dashboard y 18 publicaciones | El producto final tiene cinco bloques funcionales, aunque `stage_2_arcos` los resume como tres arcos analíticos más integración. |
| `Trabajo/config/stage_roadmap.yaml` | `stage_1_corpus` exige discovery, snapshot v3, fulltext/dedupe/clasificación/enrichment verificables y revisión humana; `stage_2_arcos` exige evidencia/método/límites por arco; `stage_3` exige concordancia y límites publicados; `stage_4` exige oferta y responsabilidades | No se deben incorporar fuentes al pipeline productivo durante la corrida ni declarar cerrado un arco por tener código o un prototipo. |
| `Trabajo/config/backlog_estrategico_socioterritorial.md` | Ontología mínima: proyecto, caso/conflicto, evento, actor, institución, territorio, documento/evidencia, afirmación, resultado y temporalidad | Predicción, causalidad, mercado inmobiliario granular, catastro avanzado, satélite, redes sociales, APIs/SaaS, simulaciones e internacionalización son backlog posterior, no alcance actual. |
| `Trabajo/config/pipeline_contract_v2.yaml` | `lineage` con `query_hash`, `plan_version`, `snapshot_sha256`, `origins`; hueco de diseño confirmado para múltiples hitos temporales | La integración debe consumir un snapshot v3 y una versión de enrichment que admita lista de hitos; no corregir datos en esta auditoría. |

## 3. Contrato de integración mínimo

Antes de unir fuentes, el proyecto debería definir estas tablas derivadas (sin borrar el documento fuente):

| Entidad | Campos mínimos | Regla de identidad |
|---|---|---|
| `document` | `document_id` (hash), URL/archivo, fuente, fecha publicación/captura, tipo, licencia/condiciones, `lineage`, localizador, `content_hash` | SHA-256 del contenido capturado; una URL no es identidad suficiente. |
| `evidence` | `evidence_id`, `document_id`, cita/localizador, tipo, literalidad, estado de verificación, PII, método de extracción | No promover OCR/paráfrasis a cita literal sin revisión visual/textual. |
| `project` | `project_id` local, nombres/alias, titulares, comuna(s), dirección/punto/polígono, IDs oficiales conocidos, fechas de proyecto | Alta manual o adjudicada; no resolver solo por similitud de nombre. |
| `event` | `event_id`, `case_id`, tipo, `fecha_inicio`, `fecha_fin` o incertidumbre, descripción, actores/instituciones, territorio, evidencia | Un artículo puede contener varios hitos; usar `linea_tiempo[]`. |
| `case/conflict` | `case_id`, proyecto(s), ventana temporal, pregunta analítica, estado, documentos/eventos asociados | Caso es capa derivada y auditable, no reemplazo del corpus. |
| `actor/institution` | `actor_id`/`institution_id`, nombre canónico y alias, tipo, rol, ámbito, fuente y vigencia | Separar persona, cargo, organización y relación; no guardar RUT, domicilio o contacto salvo necesidad justificada. |
| `territory` | `territory_id`, comuna/código, geometría, fecha/fuente, CRS, nivel | Preferir códigos oficiales y guardar versión temporal de límites. |
| `claim` | `claim_id`, emisor, objeto, cita, estándar/criterio, métrica, fecha, evidencia de desempeño, contradicciones, veredicto | “No verificado” y “sin evidencia localizada” son estados válidos; no equivalen a falsedad. |

## 4. Catálogo de fuentes públicas candidatas

El repositorio solicitado [juanbrujo/listado-apis-publicas-en-chile](https://github.com/juanbrujo/listado-apis-publicas-en-chile) sirve como **índice comunitario** (licencia CC0-1.0), no como garantía de disponibilidad, licencia de los datos, seguridad ni mantenimiento de cada API. El README marca como `DEPRECATED` la API DPA, las APIs municipales de Peñalolén/Providencia y varios servicios de terceros. La entrada sí identifica como relevantes la API BCN/Ley Chile, Mercado Público y Ley de Lobby; cada una debe verificarse en su fuente oficial antes de uso. No usar rutificadores, bypass-CORS ni APIs de RUT listadas allí.

| ID | Fuente primaria | Qué aporta | Acceso, costo y licencia | Límites, PII y sesgo | IDs/joins esperables |
|---|---|---|---|---|---|
| S0 | Corpus local + snapshots v3 | Prensa/documentos base, evidencia y lineage | Costo ya comprometido del proyecto; licencia depende de cada fuente de origen | Sesgo de cobertura mediática y términos de búsqueda; no es registro censal | `document_id`, `content_hash`, `query_hash`, `snapshot_sha256` |
| S1 | [MINVU DS19](https://www.minvu.gob.cl/beneficio/vivienda/subsidio-de-integracion-social-y-territorial-ds19/) y resoluciones/KMZ | Zonas, reglas, materiales y antecedentes del Programa de Integración Social y Territorial | Descargas públicas; costo monetario bajo, captura y normalización manual/media; revisar condiciones de cada archivo | Cobertura centrada en DS19 y en información ministerial; un proyecto puede cambiar de estado | Código/nombre de proyecto cuando exista; si no, `project_id` local + alias + comuna |
| S2 | [Portal de Instrumentos de Planificación Territorial MINVU](https://portalipt.minvu.cl/instrumentos) y [seguimiento IPT](https://seguimientoipt.minvu.cl/main.php?module=prc) | PRC/PRI/PRMS, modificaciones, estados y fechas de publicación | Público; no se asume API estable ni licencia de redistribución de mapas/documentos | Información suministrada por municipios/GORE; puede faltar o tener rezago | Comuna, tipo IPT, fecha/DO, expediente; unir por comuna+vigencia+documento, no por nombre de zona solamente |
| S3 | [INE Geodatos Abiertos](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos) | Censo, densidad, manzanas/zonas, DPA, certificados de recepción final y permisos de edificación | Descargas/visores públicos; costo bajo; términos de uso deben registrarse por capa | Censo es corte temporal; permisos/recepciones no equivalen a conflicto ni a valor de mercado; algunas geometrías son agregadas | Código comuna/manzana/entidad, coordenadas y `item_id` ArcGIS; guardar CRS/fecha |
| S4 | [SEA: reportes y buscador e-SEIA](https://www.sea.gob.cl/documentacion/reportes), [estadísticas SEIA](https://www.sea.gob.cl/informacion-estadistica-del-seia), [búsqueda histórica](http://seia.sea.gob.cl/busqueda/buscarProyecto.php) | Proyectos, titulares, DIA/EIA, RCA, PAC, pertinencias, documentos y fechas de evaluación | Acceso público y descargas; no hay garantía de API masiva; costo de extracción medio, respetando rate limits | Expedientes pueden contener nombres/contactos de personas y observaciones; cobertura ambiental, no todos los proyectos inmobiliarios pasan por SEIA | ID/número de proyecto/expediente, titular, comuna, región, RCA, fechas; alta utilidad para `document→event` |
| S5 | [BCN Ley Chile](https://nuevo.leychile.cl/acerca-de-ley-chile), [esquema/API](https://www.leychile.cl/esquemas/accesoLeyesChilenas4.pdf) | LGUC, OGUC, DS19, leyes, decretos, versiones y relaciones normativas | Servicio oficial; consultar condiciones de reutilización y límites de la API | Texto normativo no muestra por sí solo la decisión concreta; cambios/versiones requieren fecha de vigencia | `idNorma`, tipo/número, fecha publicación/vigencia, artículo; unir a evento normativo |
| S6 | [Diario Oficial](https://www.diariooficial.interior.gob.cl/presente/) | Publicación oficial de leyes, decretos, resoluciones, sociedades y avisos | Consulta/descarga pública; volumen y formatos hacen la extracción costosa; condiciones de uso deben conservarse | Publicaciones pueden contener PII y datos societarios; no es un registro de hechos materiales | CVE/edición/fecha/sección y número de norma; corroborar con `idNorma` BCN |
| S7 | Portales oficiales municipales y [Transparencia Activa](https://www.portaltransparencia.cl/) | Actas de concejo, acuerdos, permisos/DOM, PLADECO, presupuestos, organigramas y expedientes | Heterogéneo; normalmente costo monetario $0 pero alto costo de búsqueda, PDF/OCR y solicitudes; no existe esquema único | Rezago, faltantes y formatos inconsistentes; actas no equivalen a totalidad de deliberación | Municipalidad/código, número de acta, sesión, fecha, expediente, proyecto; requiere crosswalk manual |
| S8 | [API Mercado Público](https://api.mercadopublico.cl/documentos/Documentaci%C3%B3n%20API%20Mercado%20Publico%20-%20Licitaciones.pdf) | Licitaciones, órdenes de compra, organismos compradores y proveedores | API oficial con ticket/credencial; costo monetario aparente bajo, costo de acceso y límites de uso por verificar | Pueden aparecer nombres/contactos de personas; compras no prueban influencia ni vínculo causal | Código de licitación/OC, RUT proveedor/organismo (proteger), fechas, comuna/servicio |
| S9 | [Ley de Lobby](https://www.leylobby.gob.cl/) | Audiencias, viajes, donativos y sujetos pasivos/activos registrados | Portal oficial; la plataforma informa publicidad y descargas, pero no asumir endpoint estable; costo medio de normalización | Registro legalmente acotado: ausencia no prueba ausencia de gestión; nombres son PII en contexto público | ID de audiencia/registro, institución, sujeto pasivo, fecha, materia; unir a institución/proyecto solo con evidencia |
| S10 | [SMA/SNIFA Datos Abiertos](https://snifa.sma.gob.cl/DatosAbiertos) | Unidades fiscalizables, RCA asociadas, fiscalizaciones, sancionatorios, sanciones y monitoreo | Descargas públicas; costo bajo/medio; SMA advierte que parte de los datos reportados por regulados no ha sido verificada | Datos reportados pueden contener error/omisión; no convertir “sin sanción publicada” en cumplimiento total | ID unidad fiscalizable, expediente, RCA, comuna/titular y fechas |
| S11 | [CMN indicadores/descargas](https://www.monumentos.gob.cl/indicadores-sobre-monumentos-nacionales), [FeatureServer](https://idepat.patrimoniocultural.gob.cl/server/rest/services/Geodatabase_corporativa/Puntos_Monumentos_Nacionales/FeatureServer) | Monumentos, zonas típicas, polígonos/puntos y decretos | XLSX/KMZ/servicio geográfico público; revisar atribución y términos de cada capa | Actualización periódica; centroide/punto puede ocultar polígono protegido; patrimonio arqueológico tiene tratamiento particular | ID/código/decreto, comuna, geometría/CRS; join espacial con proyecto |
| S12 | [DTPM GTFS vigente](https://dtpm.cl/index.php/gtfs-vigente) y [datos/servicios](https://www.dtpm.cl/index.php/sistema-transporte-publico-santiago/datos-y-servicios) | Paradas, rutas, horarios y accesibilidad territorial para mapa | GTFS público; servicios adicionales requieren formulario/credenciales e IP; no usar la API comunitaria como sustituto | Es oferta de transporte, no medición de accesibilidad real ni percepción vecinal; versiones cambian | IDs GTFS de parada/ruta, fecha de feed, geometrías; join espacial con proyecto/territorio |
| S13 | [Datos.gob.cl](https://datos.gob.cl/es/) (CKAN) | Catálogo y `resource_id`/DataStore para descubrir datasets públicos | Portal público, pero licencia y calidad dependen de cada recurso | Metadatos incompletos, actualización desigual y recursos retirados | `dataset_id`, `resource_id`, organización, fecha de actualización |

## 5. Matriz de necesidades por arco

**Escala:** P0 = habilitante para el primer caso integrado; P1 = mejora necesaria para robustez/portafolio; P2 = investigación o producto posterior. “Costo” es costo incremental esperado (monetario + trabajo), no una cotización.

### 5.1 Felipe: corpus, clasificación, tópicos, mapa y dashboard

| Prioridad | Dato adicional | Fuente(s) | Cadena y joins | Factibilidad / límites | Piloto mínimo |
|---|---|---|---|---|---|
| P0 | Registro canónico de proyectos, alias, titulares, comuna, dirección/punto, estado y fechas múltiples | S0 + S1 + S3 + S4 | `document/evidence→event→project`; `document_id`, URL/hash; tabla `project_alias` | Alta como trabajo de modelado; no hay ID universal; requiere adjudicación humana de 10–20 casos | 10 casos con al menos dos fuentes y una revisión de identidad por persona |
| P0 | Eventos con intervalos y tipo (permiso, denuncia, acta, RCA, sanción, sentencia, declaración) | S0, S2, S4–S7, S10 | `event_id→case_id`; conservar `source_locator` y `linea_tiempo[]` | Alta después de resolver el hueco `fecha_evento`; extracción LLM no sustituye revisión | 10–20 documentos, registrar desacuerdos y fechas inciertas |
| P0 | Límites administrativos, densidad/vivienda, permisos/recepciones y capas de patrimonio/transporte | S3, S11, S12 | Join espacial reproducible con CRS, fecha de capa y tolerancia; nunca por dirección textual solamente | Alta para mapa descriptivo; cobertura/fechas no homogéneas; no llamar “valor de suelo” a un proxy | 2 comunas y 10 proyectos, con mapa de controles y casos sin coordenada |
| P0 | Etiquetas de inclusión, tema, tono, actor, vía legal, evidencia y revisión humana | S0 + esquema v2 | `claim/evidence` enlazado a texto; hash del payload y versión del clasificador | Alta, pero depende de cerrar stage 1 y no mezclar contratos; sesgo de términos/medio | Revisión ciega de incluidos, excluidos e inciertos; métricas de acuerdo y errores |
| P1 | Normativa/actas/expedientes para ampliar el corpus más allá de prensa | S2, S5–S7 | Relacionar URL/expediente/acta con `project_id` y `event_id` | Media: municipalidades no tienen formato/API uniforme; extracción PDF/OCR costosa | 3 comunas, un mismo conflicto, 5 documentos oficiales por caso |
| P1 | Accesibilidad de transporte y equipamientos como contexto, no como causa | S3, S12 y recursos oficiales de equipamiento si se seleccionan | Join espacial/temporal; guardar versión GTFS | Media; GTFS vigente no reconstruye automáticamente 2014–2026 | Un corte temporal actual y un corte histórico, comparando cobertura |
| P2 | Precio/valor de suelo granular, satélite, redes sociales y predicción/alerta | Fuentes adicionales aún no comprometidas | Requieren licencias, validación y gobernanza nuevas | Fuera de alcance actual; alta probabilidad de sesgo/PII/costo | Solo diseño de hipótesis, sin ingestión ni score público |

### 5.2 Darío: SNA, ERGM, SAOM y red de actores

| Prioridad | Dato adicional | Fuente(s) | Cadena y joins | Factibilidad / límites | Piloto mínimo |
|---|---|---|---|---|---|
| P0 | Diccionario de actores: persona pública, cargo, institución, empresa, comunidad/organización, titular y fuente | S0, S4, S7, S8–S10 | `actor_id`, `institution_id`, alias, vigencia; cada nodo debe tener evidencia | Media-alta para roles públicos; homónimos y cambios de cargo exigen adjudicación; no recolectar RUT/domicilio | 1 caso, 20–40 actores, adjudicación manual y lista de excluidos |
| P0 | Aristas observadas y tipificadas: firma, audiencia, compra, aprobación, objeción, citación, representación, coaparición | S4, S7–S10 + S5/S6 | `edge_id`, origen/destino, tipo, fecha/intervalo, peso, `evidence_id`, dirección | Alta para aristas documentales; coaparición de prensa no equivale a relación social | 1 caso con 3 tipos de arista y doble revisión de 10 aristas |
| P1 | Afiliaciones históricas y multiafiliación verificable | S7–S9, S6, sitios institucionales | `actor_id` + institución + cargo + `valid_from/to`; no inferir propiedad/financiamiento sin fuente | Media; registros incompletos y datos personales; excluir relaciones especulativas | 10 actores puente, dos fuentes independientes por afiliación |
| P1 | Frontera de red y controles: quién entra, universo elegible, nodos ausentes, denominador | S0 + protocolo analítico | `sampling_frame_id`, criterio posicional/relacional, fecha de corte | Imprescindible para ERGM; sin frontera, centralidad/ranking no es interpretable | Comparar red de un caso bajo dos fronteras predefinidas |
| P1 | Red temporal por olas (antes/durante/después de un evento) | S0, S4, S7–S10 | `wave_id`, fechas de observación y eventos; no confundir tiempo de publicación con tiempo de relación | Factible solo para casos con expediente suficiente; 2014–2026 no garantiza observaciones regulares | 2 olas de un caso y análisis descriptivo de cambios |
| P2 | SAOM/SIENA y explicaciones de homofilia/imitación | Red longitudinal con varias olas y nodos estables | Panel de red + covariables por ola; requiere diseño muestral específico | No factible con una sola red de prensa o coocurrencia; queda deferido | Solo simulación metodológica offline con datos sintéticos, si se autoriza |

### 5.3 Nicolás: institucional, regulatorio, entrevistas y decisión

| Prioridad | Dato adicional | Fuente(s) | Cadena y joins | Factibilidad / límites | Piloto mínimo |
|---|---|---|---|---|---|
| P0 | Línea normativa versionada: LGUC/OGUC, DS19, resoluciones, circulares, vigencia y artículos aplicables | S1, S2, S5, S6 | `norm_id/idNorma`, artículo, publicación/vigencia, `event_id` | Alta; BCN/DO son fuentes primarias, pero la vigencia debe fijarse por fecha del evento | 1 conflicto y 10 disposiciones con control de versión |
| P0 | Expediente de decisión: acta, acuerdo, permiso, observación, aprobación/objeción, RCA/pertinencia cuando aplique | S2, S4, S7, S10 | `decision_id`, institución firmante, cargo/rol, fecha, proyecto/caso, documento | Media; documentos municipales fragmentados y a veces solo PDF; acceso no equivale a completitud | 3 municipalidades, 1 expediente comparable por comuna |
| P0 | Matriz “quién aprueba / quién objeta / qué competencia tiene” | S2, S5–S7, S10 | `institution_id`, `role_id`, competencia, evidencia normativa, evento | Alta en lo formal; no inferir poder informal ni causalidad | 10 decisiones codificadas y revisión jurídica/documental |
| P1 | Contraste expediente–prensa: qué afirma la prensa, qué documento lo respalda o contradice | S0 + S2/S4/S7 | `claim_id` a una o más evidencias oficiales; estados `supported/contradicted/unresolved` | Alta para muestra; sesgo de selección del corpus y documentos faltantes | 5 casos con 2–3 piezas mediáticas y expediente oficial |
| P1 | Audiencias de lobby y compras públicas como contexto institucional | S8, S9 | `meeting/procurement_id`, institución, fecha, materia, actor; no unir al proyecto sin prueba | Media; cobertura legalmente acotada, ticket/descarga y campos personales; ausencia no prueba ausencia | 1 comuna y un período, con revisión de 20 registros |
| P1 | Entrevistas semiestructuradas a informantes institucionales/comunitarios | Diseño propio, consentimiento informado; pueden orientar selección de casos, no ser “dataset público” | `interview_id`, consentimiento, rol, fecha, transcript hash, códigos; separar PII | Costo alto en tiempo/ética; riesgo de identificación, memoria y deseabilidad social | 3–5 entrevistas, transcripción controlada, anonimización y memo de límites |
| P2 | Inferencia causal, predicción de decisiones o perfilamiento de funcionarios | No comprometido | No hay join legítimo sin diseño adicional | Fuera de alcance; no presentar correlación documental como causalidad o asesoría automática | Ninguno |

### 5.4 Christian: ESG/evidencia/anti-greenwashing

| Prioridad | Dato adicional | Fuente(s) | Cadena y joins | Factibilidad / límites | Piloto mínimo |
|---|---|---|---|---|---|
| P0 | Registro de afirmaciones sobre integración social, impacto, mitigación, participación, patrimonio y cumplimiento | S0, S1, S2, S4, S7, S10 | `claim_id`, emisor, objeto/proyecto, cita exacta, fecha, `document_id` | Alta para afirmaciones documentales; lenguaje promocional no es evidencia de desempeño | 20 afirmaciones de 3 proyectos, con localizador verificable |
| P0 | Clasificación de evidencia: declarativa → cumplimiento institucional → evidencia de desempeño; nivel nominal/ordinal/intervalo/razón | Fuentes del caso + marco interno de Christian | `claim_id→evidence_id`, criterio, unidad, fecha, método, verificador | Alta si cada categoría tiene ejemplos y reglas; no confundir ausencia de publicación con incumplimiento | Doble codificación independiente de 20 afirmaciones |
| P0 | Evidencia de obligación/resultado: permiso, acta, recepción, RCA/seguimiento, sanción, medición, informe | S2–S7, S10/S11 | `project_id`, instrumento, fecha, métrica, unidad, condición, resultado y contradicción | Media; SMA advierte que datos reportados por regulados pueden no estar verificados; documentos no siempre comparables | 5 proyectos, al menos 2 tipos de evidencia y un caso `unresolved` |
| P1 | Comparabilidad entre inmobiliarias/proyectos: denominador, período, tamaño, estándar y cobertura | S1–S4, S7, S10 + documentos corporativos si están públicamente disponibles | `comparison_set_id`, normalización, regla de inclusión, `license_status` | Media; ranking sin normalización sería engañoso; reportar intervalos y faltantes | Comparar 3 proyectos del mismo programa y período |
| P1 | Contradicciones y rectificaciones: promesa, cambio, incumplimiento, sanción o explicación posterior | S0, S4, S7, S10 | `event_id` ordenado temporalmente; no borrar afirmación original | Media-alta para muestra; requiere línea temporal y lectura del expediente | 5 trayectorias con al menos una fuente primaria y una secundaria |
| P2 | Auditoría ESG comercial multindustria y conclusión legal de “greenwashing” | Reportes privados/estándares con licencia que deberá verificarse | No incorporar sin alcance, estándar, licencia y asesoría pertinente | Producto posterior; usar “brecha evidencial” en este caso, no conclusión jurídica | Solo ficha metodológica, sin ranking público ni acusación |

### 5.5 Cierre Felipe + integración + comercialización

| Prioridad | Dato adicional | Fuente(s) | Cadena y joins | Factibilidad / límites | Piloto mínimo |
|---|---|---|---|---|---|
| P0 | Crosswalk integrado: proyecto–caso–evento–actor–institución–territorio–claim–documento | Todas las fuentes P0; S0 como columna vertebral | IDs locales estables, `evidence_id`, fechas, procedencia y estado de revisión | Alta como entregable de integración; el trabajo es manual y debe admitir “no join” | 1 caso end-to-end con 10–20 documentos y un dashboard de trazabilidad |
| P0 | Reglas de publicación: incertidumbre, cobertura, campos faltantes, sesgo y límites | `stage_roadmap`, contrato y revisión humana | Cada visualización/claim apunta a evidencia; publicar versión de datos y fecha de corte | Alta; es gate de `stage_3` | Checklist de 10 afirmaciones y 5 visualizaciones contra fuente |
| P0 | Tópicos/sentimiento/mapa solo sobre corpus cerrado y entidades adjudicadas | S0 + S3/S11/S12 | `topic_run_id`, modelo/versión, `project_id`, geometría y `evidence_id` | Factible después de stage 1; sentimiento no debe tratarse como opinión poblacional | 1 caso y una muestra humana de validación; sin redes sociales |
| P1 | Medición de desempeño del caso: tiempo/costo de producción, cobertura, acuerdo humano, errores, consultas respondidas | Logs/artefactos propios del proyecto | `artifact_id`, `run_id`, `cost`, `review_id`, `claim_id` | Alta y sin fuente externa; no exponer secretos ni credenciales | Ficha de caso de una página con cifras auditables |
| P1 | Descubrimiento comercial: problema, comprador, alcance, resultado esperado, presupuesto, objeciones y disposición a pagar | Conversaciones voluntarias, anonimizadas y registradas | `conversation_id→service_offer_id→artifact_id`; separar PII del corpus | Costo medio/alto; exige consentimiento y no usar actores del caso como leads sin base | 3–5 conversaciones, sin prometer producto automático |
| P1 | Paquete vendible acotado (scraping/clasificación, red de actores, expediente regulatorio o auditoría evidencial) | Evidencia P0/P1 + constitución §10 | `offer_id`, alcance, supuestos, exclusiones, plazo, costo, responsable, criterio de éxito | Alta si se vende servicio manual asistido; no construir SaaS antes de validar demanda | Una oferta de alcance único y un piloto con criterio de aceptación |
| P2 | CRM/API comercial, producto de cartera, monitoreo continuo y score de riesgo | No comprometido | Requiere gobernanza, seguridad, licencias y PII adicional | Fuera de alcance; no usar este caso para prometer automatización recurrente | Ninguno |

## 6. Priorización consolidada

### P0 — habilitar el primer caso integrado, después del cierre de etapa 1

1. Congelar el snapshot v3 y no mezclarlo con legacy; completar el `enrichment_schema_v2`/`linea_tiempo` y revisión por lotes según el contrato vigente.
2. Definir y revisar manualmente el crosswalk `project_id` para 10–20 casos, con alias, titulares, comunas, geometría, IDs SEA/MINVU/municipales cuando existan y una lista explícita de no correspondencias.
3. Materializar `document`, `evidence`, `event`, `case`, `actor`, `institution`, `territory` y `claim` con hash, localizador, fuente, fecha, licencia/condiciones, PII y estado de verificación.
4. Usar un piloto oficial pequeño: MINVU/Portal IPT + INE + BCN/DO + acta/expediente municipal; añadir SEA/SMA/CMN solo cuando el caso los requiera.
5. Ejecutar un caso end-to-end: al menos 10–20 documentos, 5–10 eventos, 20 actores potenciales, un mapa, una tabla de afirmaciones y una revisión humana independiente.

### P1 — robustez y portafolio

- Ampliar expedientes municipales y actas a tres comunas.
- Incorporar ChileCompra y Ley de Lobby como contexto institucional, nunca como prueba automática de influencia.
- Construir red temporal en dos olas y correr SNA descriptivo/ERGM solo con frontera y controles documentados.
- Hacer 3–5 entrevistas con consentimiento y anonimización, si Nicolás consigue acceso.
- Auditar 3–5 proyectos con el marco de Christian y publicar brechas/faltantes, no ranking crudo.
- Medir costo, cobertura, acuerdo, error y utilidad comercial; convertirlo en una oferta de alcance acotado.

### P2 — no comprometer ahora

SAOM/SIENA con panel longitudinal; redes sociales; inferencia causal/predicción/early warning; valor de suelo granular; catastro avanzado; satélite/computer vision; producto de cartera; APIs/SaaS; internacionalización; ranking legal/ESG o perfilamiento individual. Su activación requiere fuentes, licencia, diseño, gobernanza y aprobación de alcance independientes.

## 7. Criterios de aceptación

### Contrato común de evidencia

- [ ] Cada documento tiene `document_id`, hash, URL/archivo, fecha de captura, fuente, condiciones de uso y `lineage`.
- [ ] Cada afirmación publicada apunta a un `evidence_id` y localizador reproducible; citas literales fueron comprobadas contra el documento.
- [ ] Cada evento admite varias fechas o un intervalo; la fecha de publicación no se presenta como fecha del hecho sin evidencia.
- [ ] Cada caso conserva documentos y eventos de origen; ningún grafo, score o resumen reemplaza la procedencia.
- [ ] Los joins declaran método (ID oficial, alias adjudicado o espacial), fecha de capa, CRS y tasa de no unión.
- [ ] PII está minimizada, marcada y separada de salidas públicas; no se usan RUT, domicilios, contactos o entrevistas identificables sin necesidad/base legítima.
- [ ] Se reportan cobertura, sesgo de selección, faltantes, incertidumbre, duplicados y límites de generalización.

### Criterios por arco

- **Felipe:** clasificación y tópicos reproducibles por versión; mapa no confunde proxy con valor de mercado; dashboard concuerda con la tabla fuente y permite abrir la evidencia.
- **Darío:** frontera de red y reglas de inclusión publicadas; toda arista tiene tipo, fecha y evidencia; centralidad no se interpreta como poder causal; ERGM reporta controles y sensibilidad; SAOM no se declara viable sin olas longitudinales.
- **Nicolás:** cada conclusión normativa identifica norma/artículo/versión/vigencia; cada decisión identifica institución competente y documento; expediente y prensa se contrastan; entrevistas muestran consentimiento, anonimización y límites de memoria/selección.
- **Christian:** cada claim tiene emisor, objeto, fecha, estándar/criterio y clase de evidencia; las comparaciones tienen denominador y período homogéneos; se usa “brecha evidencial/no verificado” salvo base jurídica específica para otra conclusión.
- **Cierre/comercial:** existe un caso reproducible, un paquete de alcance definido, costos/tiempos medidos, límites visibles y 3–5 conversaciones registradas sin PII pública; no se promete monitoreo automático ni asesoría decisoria.

## 8. Recomendación de piloto mínimo (sin ejecutar en esta auditoría)

Seleccionar, después del cierre humano de etapa 1, **un solo conflicto** con cobertura mediática y al menos un expediente oficial. Congelar 10–20 documentos; construir manualmente el `project_id`; localizar 5–10 eventos con `linea_tiempo`; validar 20 actores y 10 aristas; levantar una norma y una decisión institucional; codificar 20 claims; añadir una capa INE y, si aplica, CMN/SEA/SMA; producir una vista integrada con enlaces de evidencia. El piloto se acepta solo si un segundo revisor puede reconstruir el caso desde los documentos sin leer el chat.

No se debe ejecutar scraping, consumir APIs, hacer entrevistas, incorporar nuevas fuentes al manifest, cambiar contratos, locks o manifests, ni modificar producción como parte de este inventario.

## 9. Fuentes revisadas

- Constitución de la consultora, §9: `D:\Felipe\Consultora\constitucion_consultora.html` (arcos y cierre comercial).
- `D:\Felipe\Consultora\caso_inmobiliario_stgo\Trabajo\config\stage_roadmap.yaml`.
- `D:\Felipe\Consultora\caso_inmobiliario_stgo\Trabajo\config\backlog_estrategico_socioterritorial.md`.
- `D:\Felipe\Consultora\caso_inmobiliario_stgo\Trabajo\config\pipeline_contract_v2.yaml`.
- [Listado comunitario de APIs públicas en Chile (CC0-1.0; consultado 2026-09-13)](https://github.com/juanbrujo/listado-apis-publicas-en-chile).
- [MINVU DS19](https://www.minvu.gob.cl/beneficio/vivienda/subsidio-de-integracion-social-y-territorial-ds19/).
- [MINVU Portal IPT](https://portalipt.minvu.cl/instrumentos) y [seguimiento IPT](https://seguimientoipt.minvu.cl/main.php?module=prc).
- [INE Geodatos Abiertos](https://www.ine.gob.cl/herramientas/portal-de-mapas/geodatos-abiertos).
- [SEA, reportes SEIA](https://www.sea.gob.cl/documentacion/reportes) y [estadísticas SEIA](https://www.sea.gob.cl/informacion-estadistica-del-seia).
- [BCN Ley Chile](https://nuevo.leychile.cl/acerca-de-ley-chile) y [esquema de acceso](https://www.leychile.cl/esquemas/accesoLeyesChilenas4.pdf).
- [Diario Oficial](https://www.diariooficial.interior.gob.cl/presente/).
- [API Mercado Público](https://api.mercadopublico.cl/documentos/Documentaci%C3%B3n%20API%20Mercado%20Publico%20-%20Licitaciones.pdf).
- [Ley de Lobby](https://www.leylobby.gob.cl/).
- [SMA/SNIFA Datos Abiertos](https://snifa.sma.gob.cl/DatosAbiertos).
- [Consejo de Monumentos: descargas](https://www.monumentos.gob.cl/indicadores-sobre-monumentos-nacionales) y [servicio geográfico](https://idepat.patrimoniocultural.gob.cl/server/rest/services/Geodatabase_corporativa/Puntos_Monumentos_Nacionales/FeatureServer).
- [DTPM GTFS vigente](https://dtpm.cl/index.php/gtfs-vigente) y [datos y servicios](https://www.dtpm.cl/index.php/sistema-transporte-publico-santiago/datos-y-servicios).
- [Portal Datos.gob.cl](https://datos.gob.cl/es/).

