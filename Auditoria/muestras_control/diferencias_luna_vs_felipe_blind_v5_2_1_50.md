# Diferencias entre Luna y Felipe — muestra ciega v5.2.1 (50)

Generado: 2026-09-15T22:09:25.076464+00:00

## Resumen

- Casos revisados: **50**.
- Diferencias estrictas: **17**.
- Acuerdo estricto: **33/50 (66.0%)**.
- Acuerdo operacional: **42/50 (84.0%)**.
- Falsos positivos definidos de Luna: **2**.
- Regla vigente: **0 falsos positivos**; la muestra no habilita producción.

| Categoría | Casos | Lectura |
|---|---:|---|
| Falso positivo del modelo | 2 | Include de Luna que Felipe excluyó |
| Override humano a include | 4 | Felipe incluyó donde Luna no lo hizo |
| Incierto vs exclude | 1 | Felipe resolvió la incertidumbre como exclusión |
| Insuficiente vs exclude | 9 | Misma acción segura, etiqueta distinta |
| Revisión vs insuficiente | 1 | Felipe pidió revisión adicional |

## Casos críticos: falsos positivos de Luna

### Caso 2 — http://www.scielo.org.co/scielo.php?pid=S0124-79132023000300073&script=sci_arttext
- Estrato: `non_residential_signal`; Luna: `include`; Felipe: `confirmar_exclude`.
- Razón de Luna: El artículo analiza la oposición y el rechazo hacia torres de alta densidad, con un caso principal localizado en Estación Central y referencias explícitas a acciones vecinales en Maipú, San Miguel y Peñalolén. Las tres últimas aparecen solo como titulares citados, por lo que se registran como menciones tangenciales.
- Nota de Felipe: Excluir. El artículo académico analiza estigma y rechazo a torres de alta densidad, pero el supuesto caso de Estación Central no documenta una acción contenciosa concreta asociada a un proyecto/caso individualizable. Las referencias a Maipú, San Miguel y Peñalolén son titulares citados y menciones tangenciales sin documentación propia. Incluirlo convertiría evidencia secundaria/general en caso empírico.

### Caso 6 — https://cambio21.cl/pais/dueo-de-la-universidad-sek-y-de-unin-espaola-se-querell-contra-todo-el-mundo-5b01eedccd49b05dda7adfc3
- Estrato: `administrative_permit`; Luna: `include`; Felipe: `confirmar_exclude`.
- Razón de Luna: El artículo contiene un caso urbanístico explícito: la Municipalidad de Independencia invalidó permisos de edificación para levantar un proyecto inmobiliario en los terrenos del estadio Santa Laura. Las otras querellas descritas se refieren principalmente a revelación de secreto e injurias, y se separan como menciones distintas.
- Nota de Felipe: Excluir. El artículo trata principalmente querellas de Jorge Segovia por filtración de secreto e injurias. La invalidación municipal de permisos para un proyecto en Santa Laura aparece en una sola frase como antecedente de un reportaje de CIPER; no está desarrollada como caso secundario sustantivamente documentado. Bajo el contrato de case_mentions corresponde a mención tangencial, no a include.

## Casos donde Felipe incluyó y Luna no

### Caso 19 — https://radionuevomundo.cl/2019/10/preocupacion-en-vecinos-de-santiago-y-recoleta-por-trazado-de-futura-linea-7-del-metro/
- Estrato: `judicial`; Luna: `exclude` (raw `include`); Felipe: `aprobar_include`.
- Razón de Luna: La fuente documenta un conflicto urbano principal y verificable sobre el trazado y las obras de la futura Línea 7 del Metro en Santiago y Recoleta, con solicitudes de estudios, entrega de observaciones y oposición organizada por posibles impactos viales, ambientales y territoriales.
- Nota de Felipe: Aprobar include en el universo urbano amplio. El texto documenta oposición vecinal organizada al trazado y obras de la futura Línea 7 del Metro en Santiago y Recoleta, con solicitudes de estudios y observaciones formales por impactos hídricos, ambientales, patrimoniales y viales. Es infraestructura urbana explícita, geografía en alcance y acción verificable. La exclusión del gate amplio parece demasiado restrictiva para el contrato que admite equipamiento/infraestructura urbana.

### Caso 21 — https://segreader.emol.cl/2017/05/18/A/M235MCEK/light?gt=134637
- Estrato: `community`; Luna: `uncertain` (raw `include`); Felipe: `aprobar_include`.
- Razón de Luna: El caso principal documenta una oposición vecinal organizada y actuaciones municipales verificables respecto del destino de un paño específico: parque ribereño versus viviendas sociales. El objeto residencial y la geografía están explícitos. El anteproyecto de Sencorp aparece como un caso secundario, pero el texto no vincula de forma inequívoca una acción contenciosa específicamente dirigida contra ese proyecto.
- Nota de Felipe: Aprobar include. El caso principal está suficientemente documentado: existe una pugna por el destino de un paño entre parque ribereño y hasta 562 viviendas sociales, con organización vecinal, reuniones con autoridades y trabajo para modificar el plano regulador. Objeto, acción y geografía son explícitos. El anteproyecto de Sencorp puede mantenerse como mención separada incierta.

### Caso 28 — https://www.biobiochile.cl/noticias/nacional/region-metropolitana/2018/10/21/vecinos-de-las-condes-providencia-y-la-reina-rechazan-construccion-de-laguna-en-parque-padre-hurtado.shtml
- Estrato: `large_project`; Luna: `exclude` (raw `include`); Felipe: `aprobar_include`.
- Razón de Luna: El artículo documenta un conflicto urbano principal por la construcción de una laguna artificial dentro del proyecto de mejoramiento del Parque Padre Hurtado. Existe oposición vecinal organizada y una votación verificable, con geografía explícita en Las Condes, La Reina y Providencia.
- Nota de Felipe: Aprobar include en el universo urbano amplio. El proyecto de mejoramiento del Parque Padre Hurtado y su laguna artificial constituyen una intervención/equipamiento urbano explícito. Miles de vecinos de Las Condes, La Reina y Providencia participaron en una votación y rechazaron la obra. Acción, objeto y geografía están plenamente documentados. No pertenece a la vista residencial.

### Caso 33 — https://www.df.cl/empresas/construccion/abogados-de-vespucio-345-la-suprema-marca-precedente-de-la-oportunidad
- Estrato: `outside_area_signal`; Luna: `uncertain` (raw `include`); Felipe: `aprobar_include`.
- Razón de Luna: El caso principal documenta un conflicto verificable por la construcción del proyecto Vespucio 345 en Las Condes, con seis recursos ante la Tercera Sala de la Corte Suprema y controversias sobre permisos de edificación, plano de fusión y su modificación. La referencia a Parque Pümpin corresponde a una comparación breve y además está fuera del área de estudio.
- Nota de Felipe: Aprobar include en el universo amplio. Vespucio 345 en Las Condes está sustantivamente documentado, con seis recursos ante la Corte Suprema, paralización y disputa por permisos/plano de fusión. El subtipo del proyecto puede permanecer indeterminado para la vista residencial, pero eso no impide la inclusión amplia.

## Diferencias de etiqueta o umbral

| Nº | Estrato | Luna amplia | Felipe | URL | Nota |
|---:|---|---|---|---|---|
| 25 | residential_density | uncertain | confirmar_exclude | https://www.archdaily.com/es/895554/las-personas-quieren-ciudad-no-solo-vivienda-un-llama… | Excluir, no mantener uncertain. Es un comunicado/agenda nacional sobre hacinamiento, densificación e integración urbana en Chile; no identifica una comuna del área de estudio ni un caso territorial concreto. La falta de geografía local es evidencia suficiente… |
| 1 | regulatory_instrument | insufficient_content | confirmar_exclude | http://latribunadern.cl/mediomi.html | Confirmar exclusión. El fulltext recuperado solo contiene una referencia a una nota sobre mortalidad por consumo de drogas; no hay objeto urbano/inmobiliario ni acción contenciosa. La etiqueta operacional de insufficient_content del gate es razonable, pero co… |
| 16 | residential_density | insufficient_content | confirmar_exclude | https://norte-verde.cl/ | Confirmar exclusión. Es una página corporativa sobre un canal general de denuncias; no contiene un caso, objeto disputado ni geografía específica de conflicto inmobiliario/urbano. |
| 17 | residential_density | insufficient_content | confirmar_exclude | https://pintana.cl/?page_id=3386 | Confirmar exclusión. Es una página institucional de la DOM de La Pintana que describe funciones y trámites; no documenta un conflicto específico ni una acción contenciosa. |
| 18 | administrative_permit | insufficient_content | confirmar_exclude | https://providencia.cl/provi/explora/noticias/municipalidad/concejo-municipal-martes-9-de… | Confirmar exclusión con el texto disponible. La página es una tabla/agenda de Concejo Municipal de Providencia y no desarrolla un conflicto inmobiliario o urbano, un objeto específico ni una acción contenciosa vinculada a ese ámbito. |
| 26 | community | insufficient_content | confirmar_exclude | https://www.bcn.cl/leychile/navegar?idNorma=30785 | Confirmar exclusión. El texto es normativa general sobre juntas de vecinos y organizaciones comunitarias; no documenta un conflicto inmobiliario/urbano específico. |
| 40 | regulatory_instrument | insufficient_content | confirmar_exclude | https://www.ex-ante.cl/politica/jorge-ramirez-presidente-de-comunes-el-frente-amplio-debe… | Confirmar exclusión. La entrevista política solo contiene referencias generales a vivienda; no documenta proyecto, disputa urbana, acción contenciosa ni caso territorial específico. |
| 46 | community | insufficient_content | confirmar_exclude | https://www.recoleta.cl/directivas-organizaciones-comunitarias/ | Confirmar exclusión. Es un directorio/mapa de juntas de vecinos de Recoleta, sin conflicto, acción ni objeto inmobiliario/urbano específico. |
| 47 | large_project | insufficient_content | confirmar_exclude | https://www.semanaeconomica.com/sectores-empresas/inmobiliario/armando-paredes-esperamos-… | Confirmar exclusión con el texto disponible. La entrevista empresarial trata ventas e internacionalización de una inmobiliaria, sin controversia, acción contenciosa ni caso territorial disputado. |
| 48 | large_project | insufficient_content | confirmar_exclude | https://www.soychile.cl/Antofagasta/Sociedad/2017/02/20/447835/Pesar-por-la-muerte-del-to… | Confirmar exclusión. La nota trata del fallecimiento y funerales de un músico; no existe relación sustantiva con conflictividad inmobiliaria/urbana. |
| 20 | gentrification | insufficient_content | requiere_mas_revision | https://revista180.udp.cl/index.php/revista180/article/view/283/311 | Requiere más revisión. El fulltext local solo conserva la portada/título de un artículo sobre acceso solar, gentrificación y Estación Central. El título es potencialmente pertinente, pero no hay cuerpo suficiente para verificar objeto y acción. Debe reacquiri… |

## Qué analizar ahora

1. Resolver primero los dos falsos positivos: ambos deben convertirse en regresiones automatizadas.
2. Revisar los cuatro overrides de Felipe para decidir si el gate amplio está excluyendo infraestructura urbana o conflictos residenciales bien documentados.
3. Mantener separadas las etiquetas `insufficient_content` y `exclude`, aunque operacionalmente ambas queden fuera del corpus incluido.
4. No cambiar producción todavía: corregir el prompt/gate, repetir la muestra ciega y exigir nuevamente cero falsos positivos.
5. El bundle local de Sol no contiene veredictos independientes caso a caso; no se usa como una tercera etiqueta.

## Fuentes de comparación

- Revisión humana: `D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\revision_humana_blind_v5_2_1_50_felipe.json`
- Expediente Luna: `D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\review_sample_blind_v5_2_1_50.json`
- Bundle preparado para Sol: `D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\sol_review_bundle_blind_v5_2_1_50.json`
- Comparación base: `D:\Felipe\Consultora\caso_inmobiliario_stgo\Auditoria\muestras_control\comparison_human_vs_ai_blind_v5_2_1_50.json`
