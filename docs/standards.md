# Estándares de construcción

Cómo construir (o ampliar) un pipeline de este tipo —prensa y documentos públicos → clasificación y
extracción por LLM → identidad de proyecto, caso y conflicto → red de actores y mapa— sin repetir los
errores que costaron la mayor parte del trabajo de este proyecto. Cada estándar dice **qué hacer**, **por
qué** (con la evidencia medida aquí) y **cómo lo hace cumplir este repositorio**.

Úsalo en dos momentos: al **arrancar** un proyecto nuevo (recorre la [lista de arranque](#lista-de-arranque))
y antes de **ampliar** este (¿el cambio toca una unidad de análisis, una decisión humana o un contrato de
extracción? entonces aplica el estándar correspondiente antes de escribir código).

## Resumen: dónde se fue el esfuerzo

La mayor parte de las correcciones no vinieron de errores de programación sino de **decisiones de diseño
tomadas tarde**: unidades de análisis sin definir, vínculos que no se capturaron cuando el dato estaba a la
vista, heurísticas usadas como filtros sin medir su precisión, y validación humana ubicada después de escalar.

| Síntoma que apareció | Causa raíz | Estándar que lo previene |
|---|---|---|
| Una muestra aleatoria de 50 documentos arrojó 24 % de error grave (documentos con varios conflictos bajo una sola unidad) | La unidad «documento» se trató como unidad de conflicto | [E1](#e1-define-las-unidades-y-su-identidad-antes-de-extraer) |
| Seis rondas de correcciones para atribuir a cada proyecto su mención y su comuna | La extracción devolvía nombres sueltos; el vínculo proyecto → mención se intentó reconstruir después por similitud de texto | [E2](#e2-captura-los-vínculos-en-el-momento-de-la-extracción) |
| Un detector textual de respaldo con 45–55 % de precisión sostuvo un filtro público | Una heurística se usó como puerta sin medir su precisión en una muestra ciega | [E4](#e4-una-heurística-no-es-una-puerta-hasta-medir-su-precisión) |
| Al re-extraer con un contrato nuevo, 64 de 98 decisiones humanas dejaron de aplicar sin aviso | Las decisiones estaban llaveadas por el nombre del proyecto y el nombre cambió | [E5](#e5-las-decisiones-son-datos-llaveados-por-identificador-estable) |
| 131 proyectos aparecían en varias comunas; 81 eran un error estructural (0 homónimos reales) | La geografía se resolvía por documento, no por mención | [E2](#e2-captura-los-vínculos-en-el-momento-de-la-extracción), [E8](#e8-prueba-lo-que-no-debe-pasar) |
| Un agrupador de menciones duplicadas juntó edificios distintos citados por la misma frase | La coincidencia de texto se trató como identidad | [E4](#e4-una-heurística-no-es-una-puerta-hasta-medir-su-precisión), [E8](#e8-prueba-lo-que-no-debe-pasar) |
| README, resumen de validación y manifiesto describían un estado distinto del warehouse | Cifras escritas a mano | [E10](#e10-la-documentación-se-genera-no-se-escribe) |
| Hashes que fallaban en otra máquina sin que cambiara ningún dato | Huellas de bytes de archivo; saltos de línea CRLF/LF; estado heredado de una corrida previa | [E9](#e9-reproducibilidad-real) |
| Nombres de versión, de revisores y rutas internas en el repositorio público | Una regla escrita en un documento y no verificada | [E11](#e11-la-higiene-de-la-release-es-una-prueba) |
| Varios agentes y revisores repitieron trabajo y afirmaron cosas contradictorias | Sin un registro único de decisiones ni verificación contra archivos | [E12](#e12-varios-revisores-un-solo-registro) |

La pregunta «¿el problema fue el filtrado de la API de búsqueda?» tiene una respuesta acotada: **no hay
evidencia de que lo fuera**. Las correcciones se originaron aguas abajo del descubrimiento. El descubrimiento
tiene su propia limitación, que nunca se midió (recall contra un denominador externo): ver
[E13](#e13-mide-la-cobertura-del-descubrimiento).

## Los estándares

### E1. Define las unidades y su identidad antes de extraer

**Regla.** Antes de escribir un prompt, escribe qué es un documento, una mención, un proyecto, un caso y un
conflicto, cuál es la clave estable de cada uno y cuál es la relación entre ellos (uno-a-muchos, muchos-a-uno).
Cada nivel es una decisión de identidad separada.

**Por qué.** Un documento puede tratar varios conflictos y un conflicto puede abarcar varios proyectos. Sin
esa separación, el 24 % de una muestra aleatoria tenía error grave y cualquier red construida encima era
inválida. La separación `document → evidence → project → case → conflict → actor` (ver
[metodología](methodology.md)) nació de ese hallazgo, no de una preferencia.

**Cómo se hace cumplir.** `conflict_id` es una función muchos-a-uno de `case_id` (se prueba); los roles
documentales (`focal`, `co_focal`, `contextual_mention`, `panoramic_mention`, `mentioned_unreviewed`) deciden
qué evidencia cuenta como protagonista.

### E2. Captura los vínculos en el momento de la extracción

**Regla.** Si dos entidades extraídas de un mismo documento están relacionadas (un proyecto y la mención de
la que sale; un actor y el proyecto al que pertenece), haz que **el extractor declare el vínculo** en su salida,
con un índice o identificador verificable, y valida el rango al guardarlo. Nunca lo reconstruyas después por
similitud de texto.

**Por qué.** La clasificación y la extracción eran dos llamadas separadas que no se hablaban: el proyecto de un
documento nunca se anclaba a la `case_mention` que lo describía. Cada intento posterior de repararlo con texto
tuvo falsos positivos y negativos medidos (detector textual: 55 % de precisión; geografía por documento: 81 de
131 casos eran un error estructural). Pedirle al modelo el índice de la mención, mostrándole la lista numerada,
lo resolvió de raíz y se validó con revisión ciega: 0 fabricaciones en 809 evaluaciones.

**Cómo se hace cumplir.** El extractor recibe `CASE_MENTIONS EXISTENTES` y devuelve
`proyectos_mencionados[].case_mention_index`; `sanitize_project_associations` limpia un índice fuera de rango
sin descartar el registro (conserva el valor crudo) y el ETL persiste `case_mention_index` y `case_mention_id`
en la misma fila. Sin índice no hay respaldo: no se adivina.

### E3. Piloto, validación humana en tabla, y solo después la escala

**Regla.** Antes de escalar cualquier etapa con LLM: (1) piloto de pocos documentos con resultado esperado
conocido; (2) validación humana de una **muestra aleatoria** con veredicto por caso en una **tabla**
(id, veredicto, motivo), no en un texto narrativo; (3) decisión explícita de escalar, con presupuesto.

**Por qué.** La primera validación ocurrió después de construir todo. Repetirla con una muestra ampliada de 150
conflictos midió 42 % de error grave en el diseño de entonces. Los hallazgos de una revisión narrativa no se
pueden contar ni comparar; una tabla sí.

**Cómo se hace cumplir.** `src/enrich.py` hace un **ensayo por defecto** (no llama a la API), exige
`--confirm-paid-run` y `--max-cost-usd`, procesa por olas y se detiene al alcanzar el tope; una respuesta ya
pagada nunca se pierde (se cuarentena en `invalid_records.jsonl`). La muestra ciega se arma con
`src/build_conflict_holdout.py`.

### E4. Una heurística no es una puerta hasta medir su precisión

**Regla.** Un detector determinista (coincidencia de subcadena, agrupación por texto, lista de exclusión) puede
proponer candidatos, pero **no decide** qué entra a un producto hasta que su precisión y su recall se midieron en
una muestra ciega independiente (con intervalo de confianza) y esa medición se archivó junto al detector. Las
métricas de un detector retirado no se arrastran a la documentación vigente.

**Por qué.** El detector textual de respaldo midió 55 % de precisión y 97 % de recall (holdout de 100); se aceptó
como conservador, y luego se reemplazó por el vínculo declarado por el modelo. El detector de menciones duplicadas
agrupa proyectos distintos cuando comparten una cita genérica (cuatro edificios de un mismo fallo): sirve para
señalar, no para transferir evidencia.

**Ejemplo de puerta bien medida.** El filtro de alcance (`scope_gate.py`) se calibró en una muestra ciega, se evaluó sin cambios en una segunda y, ya integrado, se midió en una tercera: el error grave del universo recomendado bajó de ~43 % a 26 %.

**Cómo se hace cumplir.** La pertenencia a un grupo de duplicados **no transfiere** evidencia ni comuna entre
menciones (`ambiguous_duplicate_group`); solo una adjudicación explícita produce `via_reviewed_duplicate_group`.

### E5. Las decisiones son datos llaveados por identificador estable

**Regla.** Una decisión humana (fusionar, separar, elegir una mención, corregir una unidad de caso) se guarda
como **dato versionado** en `config/`, no como una constante en el código, y se llavea por identificadores
estables (la pareja exacta de `project_id`, el `case_mention_id`, el `document_id`), **nunca por nombre**. Cada
decisión lleva su evidencia (documento, hash, cita literal), se valida al cargar (falla cerrado) y no se
transfiere a otra pareja por parecido de nombres. Todo lo que el pipeline necesita para reconstruirse está en
el repositorio: ninguna decisión vive solo dentro de un warehouse anterior.

**Por qué.** 245 decisiones humanas estaban llaveadas por el texto exacto del nombre de proyecto; una nueva
extracción renombró proyectos y 64 de 98 decisiones dejaron de aplicar en silencio. Otra decisión de revisión
por documento (934 filas) existía solo dentro del warehouse y se «heredaba» de una construcción a la siguiente.

**Cómo se hace cumplir.** `config/project_identity_decisions.json` (95 parejas, cada una con evidencia y
validada por `load_project_identity_decisions`), `config/document_case_unit_review.json` (934 filas),
`config/case_mention_eligibility_adjudications.json`, `config/project_mention_index_corrections.json`,
`config/historical_case_id_resolutions.json`. Cada archivo declara sus conteos y el cargador los verifica.

### E6. Ausencia de evidencia no es evidencia de ausencia

**Regla.** Distingue siempre **falso**, **no resuelto** y **sin evidencia suficiente**, y hazlo visible en el
dato (columna, clase, `match_method`), nunca por omisión. Una fila sin respaldo no es un conflicto falso; una
pareja sin evidencia suficiente no está demostrada ni igual ni distinta.

**Por qué.** «Sin respaldo detectado» se leyó varias veces como «falso». Dos parejas de proyectos quedan en
`insufficient_evidence` precisamente para no afirmar más de lo que la fuente permite, y cada una dice qué dato la
reabriría.

**Cómo se hace cumplir.** Clases de identidad explícitas (`same_identity`, `parent_component_phase`,
`related_plan_or_instrument`, `distinct_entities`, `insufficient_evidence`); estados de respaldo con nombre;
referencias históricas preservadas sin alias forzado.

### E7. Toda cita se verifica literalmente contra la fuente

**Regla.** Una cita que el modelo dice haber extraído es válida solo si es subcadena literal (normalizando
únicamente espacios y mayúsculas) del texto fuente. Si no lo es, se vacía el campo, se marca `_verificada=false` y
se **conserva el original** en `_original_modelo`. Un campo `_verificada=true` con valor vacío es un error de
proceso y se rechaza.

**Por qué.** Sin este gate, una cita inventada entra como evidencia. Conservar el original permite auditar los
errores del modelo en vez de ocultarlos.

**Cómo se hace cumplir.** `enrichment_core.verify_literal_quote_field` y `validate_record_invariants`; el
registro final se valida contra un segundo contrato, `config/enrichment_record_schema.json`, **generado** del
contrato de respuesta del modelo (`build_enrichment_record_schema.py`) y comprobado por una prueba de sincronía.

### E8. Prueba lo que no debe pasar

**Regla.** Junto a los casos felices, escribe pruebas de **invariantes y de rutas negativas**: que una decisión
no se transfiera por nombre, que una fusión transitiva no reconecte una pareja mantenida separada, que la
evidencia no cruce entre menciones agrupadas, que un archivo alterado falle cerrado. Y prueba la lógica contra
**casos reales adversariales** (los que ya fallaron), no contra versiones simplificadas.

**Por qué.** Los errores más caros (fusiones espurias, evidencia trasladada entre proyectos distintos) pasaban
con una suite en verde porque nadie probaba el caso «esto no debe ocurrir».

**Cómo se hace cumplir.** Pruebas de topología (`validate_project_identity_adjudication_topology`), de falla
cerrada ante archivos alterados, de no transferencia por grupo de duplicados, y regresiones con los casos reales.

### E9. Reproducibilidad real

**Regla.**

1. **Una sola definición del orden** de reconstrucción: `src/rebuild.py`. La documentación lo cita; una prueba
   verifica que coinciden.
2. **Huellas de contenido, no de bytes.** Un hash de un archivo SQLite cambia con el orden de las páginas, con
   `VACUUM` o con la versión de SQLite. Ata las decisiones a la huella de las **filas** de las tablas
   (`src/warehouse_digest.py`).
3. **Saltos de línea fijos.** `.gitattributes` fuerza LF y todo hash de texto se calcula sobre contenido
   normalizado; un mismo archivo dio hashes distintos en Windows y Linux.
4. **Sin estado oculto.** Una etapa no lee lo que dejó una construcción anterior salvo que sea la salida
   declarada de la etapa anterior. Las decisiones viven en `config/`.
5. **La raíz publicada es re-extraíble.** El corpus de terceros y la API no se versionan; pero el warehouse
   publicado contiene, idénticas, las tablas que esas etapas produjeron: `src/extract_stage_warehouse.py` las
   recupera y permite ejecutar todas las etapas derivadas sin el corpus ni gasto en LLM.
6. **Dos hashes con función distinta:** la huella de **contenido** ata las decisiones al estado de origen; el
   hash del **archivo** publicado (`audit/run_manifest.json`) certifica exactamente lo que se distribuye.

**Por qué.** Cada «repinneo» manual de un hash fue trabajo que no agregaba calidad y cada desajuste bloqueaba la
publicación por una diferencia que no era de datos.

### E10. La documentación se genera, no se escribe

**Regla.** Ninguna cifra de titular (proyectos, conflictos, hashes, conteos de la cola) se escribe a mano. Se
generan desde el warehouse y el manifiesto, y una prueba falla si el archivo versionado difiere de lo que el
generador produciría.

**Cómo se hace cumplir.** `src/render_docs_stats.py` (bloque entre marcadores en `README.md` y `START_HERE.md`),
`tests/test_docs_stats_in_sync.py`; el manifiesto se genera con `src/generate_run_manifest.py`, nunca a mano.

### E11. La higiene de la release es una prueba

**Regla.** La separación entre lo que se muestra y lo que es proceso interno se verifica automáticamente en cada
`push`: nombres de archivo sin sufijos de versión ni fechas de trabajo, sin nombres de revisores ni de asistentes,
sin rutas a carpetas internas o absolutas, y sin números de versión ni rondas en la prosa. La versión de la
release vive solo en `pyproject.toml`, en `audit/run_manifest.json` y en la tabla `release_metadata`.

**Por qué.** La regla existía como texto y se violó de forma repetida. El historial de decisiones y las
auditorías en bruto se conservan en un archivo privado, no en el repositorio público.

**Cómo se hace cumplir.** `tests/test_release_hygiene.py`, `tests/test_release_metadata.py`. El directorio
`audit/` contiene solo resultados (reportes generados, manifiesto, resumen de validación).

### E12. Varios revisores, un solo registro

**Regla.** Si intervienen varias personas o agentes: (1) un **registro único** de decisiones, hallazgos y estado,
actualizado en el momento y no al cierre; (2) toda afirmación de «ya está» se **reproduce contra los archivos**
(clon limpio, suite completa), no contra el chat; (3) lotes chicos y con alcance declarado; (4) cada entrega
declara **qué no se verificó**; (5) una identidad nunca se fuerza para que un caso cuadre.

**Por qué.** Se repitió trabajo en ramas paralelas, hubo afirmaciones contradictorias sobre un mismo estado y
una corrección humana se pisó en silencio al reclasificar un lote.

### E13. Mide la cobertura del descubrimiento

**Regla.** Antes de interpretar frecuencias, mide el **recall** del descubrimiento contra un denominador externo
(archivos de medios, conteos anuales por medio, una base de conflictos ya documentada) y la **distribución de
fechas por fuente**. Las ventanas de fecha explícitas deben aplicar a todas las fuentes, no solo a una. Un corpus
con más documentos recientes no permite separar «hay más conflicto» de «es más fácil recuperarlo».

**Estado en este proyecto.** No se midió el recall. El corpus (3.884 documentos, 934 con conflicto incluido, 176
dominios) crece hacia lo reciente: 52 % de los incluidos con fecha son de 2022–2026 y 16 % anteriores a 2018; 796
documentos no tienen fecha de publicación. Cualquier análisis de intensidad, silencio o latencia debe declararlo.

### E14. Presupuesto y gasto

**Regla.** Ninguna corrida pagada sin autorización explícita **para esa corrida**; ensayo por defecto; tope de
gasto obligatorio; contabilidad de **todas** las respuestas cobradas (una respuesta con JSON inválido también se
paga); costo registrado por documento. Un chequeo de presupuesto entre tandas paralelas puede pasarse del tope
hasta el costo de una tanda: declara el número real.

## Lista de arranque

Para un proyecto nuevo o una ampliación, en este orden:

1. Escribir las unidades y sus claves ([E1](#e1-define-las-unidades-y-su-identidad-antes-de-extraer)).
2. Definir el contrato de extracción **incluyendo los vínculos entre entidades** y cómo se validan
   ([E2](#e2-captura-los-vínculos-en-el-momento-de-la-extracción), [E7](#e7-toda-cita-se-verifica-literalmente-contra-la-fuente)).
3. Diseñar el descubrimiento con ventanas de fecha por fuente y un denominador externo para medir recall ([E13](#e13-mide-la-cobertura-del-descubrimiento)).
4. Definir dónde viven las decisiones humanas (`config/`, llaveadas por ID) y su formato de evidencia ([E5](#e5-las-decisiones-son-datos-llaveados-por-identificador-estable)).
5. Escribir `rebuild.py` y la prueba de orden **antes** de la segunda etapa ([E9](#e9-reproducibilidad-real)).
6. Activar la prueba de higiene y la generación de documentación desde el primer commit ([E10](#e10-la-documentación-se-genera-no-se-escribe), [E11](#e11-la-higiene-de-la-release-es-una-prueba)).
7. Piloto de 10–30 documentos con resultado esperado conocido; corregir el contrato ([E3](#e3-piloto-validación-humana-en-tabla-y-solo-después-la-escala)).
8. Validación humana de una muestra aleatoria con veredictos en tabla; **decidir** si escalar con base en el error medido.
9. Escalar con tope de gasto y ensayo previo ([E14](#e14-presupuesto-y-gasto)).
10. Toda heurística que filtre el producto: medir precisión y recall en muestra ciega antes de publicarla ([E4](#e4-una-heurística-no-es-una-puerta-hasta-medir-su-precisión)).
11. Antes de cerrar: **validación de cierre** de extremo a extremo con una muestra ciega nueva ([playbook](playbook.md), paso 16).
12. Publicar con manifiesto, huellas y estadísticas generadas; archivar el proceso fuera del repositorio.

## Límites conocidos de esta release

- **Validación ciega de extremo a extremo (ver `audit/blind_validation_report.json`):** sobre 56 conflictos verificables de una
  muestra aleatoria, 66 % de error grave; 44 % entre los que tienen respaldo de evidencia y 100 % entre los que no. El
  respaldo discrimina, pero el universo con respaldo aún contiene error grave, sobre todo disputas inexistentes y fuera de
  alcance temático (filtro de alcance de la clasificación). Un solo revisor (modelo), criterio estricto, muestra pequeña:
  falta replicarla con un revisor humano externo.
- Parte de los 311 conflictos sin respaldo se revisó una sola vez (con verificación de citas y hashes, sin una
  segunda lectura independiente completa). «Sin respaldo» no significa «falso».
- Quedan menciones de proyecto sin vínculo a una `case_mention` (ver las cifras en [START HERE](../START_HERE.md))
  y grupos de menciones duplicadas con señales de riesgo sin adjudicar uno por uno.
- El descubrimiento no tiene recall medido ([E13](#e13-mide-la-cobertura-del-descubrimiento)).
- Los hashes de contrato registrados en los registros de extracción corresponden al contrato tal como se ejecutó;
  las descripciones del contrato se limpiaron después de anotaciones internas sin cambiar sus instrucciones. Los
  hashes se calculaban sobre bytes con CRLF en Windows; desde ahora se normalizan a LF.
- La capa base (clasificación) y la extracción por LLM no son reproducibles desde este repositorio sin el corpus de
  terceros y la API; sí lo es todo lo derivado (ver E9).
