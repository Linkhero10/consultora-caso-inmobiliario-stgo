# Adjudicación source-first de las 68 parejas de identidad — 2026-09-27

## Alcance, método y límites

Se revisaron los 68 pares del bundle congelado por `project_id`, usando los fulltexts locales adjuntos a ambos lados. La tabla de recomendaciones preliminares se incorporó **después** de congelar la primera pasada; sus 68 filas no tenían URLs ni evidencia externa y no se usaron como fuente.
Se verificaron **219** referencias locales por URL y hashes. **219** tienen ancla literal discriminante; **0** se conservaron con hashes sin cita si no apareció un ancla útil. El JSON publica solo la frase mínima —848 palabras en 153 fuentes, máximo 19 por URL—, no pasajes circundantes. El contexto completo se puede volver a comprobar localmente con URL, hashes y offsets. Un ancla prueba aparición literal, no identidad entre IDs. Métodos: `{'normalized_full_mention': 193, 'normalized_literal_subphrase': 26}`.
No se revalidó en vivo el estado de los sitios externos; los registros del corpus local y sus hashes son los objetos auditados. El cruce de identidad no cambia la elegibilidad `include/exclude/uncertain`, no elimina ni reescribe `project_id` y no modifica SQLite.
Todas las filas conservan `production_promoted=false`; no se reconstruyó el warehouse. Las relaciones tipadas son sugerencias, no se persistieron. El gate de publicación completa sigue bloqueado por los asuntos históricos/topológicos pendientes.
Simulación del resolver real (SQLite read-only): 941 proyectos, 256 filas de cola; 219 referencias verificadas (219 citas literales, 0 sin ancla); 0 reconexiones transitivas; grupos case_id 850→835; integridad `ok`, FK errors=0. Detalle en `identity_topology_simulation.json`.

## Distribución

| Clase | N |
|---|---:|
| `distinct_entities` | 9 |
| `parent_component_phase` | 16 |
| `related_plan_or_instrument` | 10 |
| `same_identity` | 17 |
| `unresolved` | 16 |
| **Total** | **68** |

Recomendación preliminar alineada: **36/68**. Diferente o más específica: **32/68**. Ver comparación individual y evidencia en el JSON.

## Identidades propuestas para merge exacto

| pair_id | canonical_project_id |
|---|---|
| `8dc362667a5f3cc263ce` | `7118b7a4dde32efbb6d1a4b5` |
| `9754384c13e7e7773138` | `3fa82bcc9bd6c8bffba57d08` |
| `287d7367e7072da55414` | `2396059a776af42c809a7195` |
| `ee78c1e312b4da58fd35` | `cc06d5ea5e77c8c4e0bbee16` |
| `207765e9ab0b85977e9a` | `9fecc1b649c23a654df089df` |
| `25f82ae2768789149d45` | `e456549a9815284f66aeb631` |
| `bfbd66f242c66f5b9a72` | `e456549a9815284f66aeb631` |
| `63b49e4bf5ad024c95db` | `e64cb33f7422d75ed07769f9` |
| `2f5b08d4f44283f134b8` | `378e8d25e8e3edf01183be0f` |
| `2a811feeea05c497edf4` | `1ef9a6090c8fed40c1289147` |
| `5098be0ad6412b3aedc8` | `0913ce433cf7906fb082e70c` |
| `439cd7ad97d85de77f8d` | `3221064a885933e8f6ba63b2` |
| `1f25282b033d5121aae4` | `f71d8d73041a68164ecd5413` |
| `5a183f22290b18da4d10` | `49e36d5e154797526cb7ac7f` |
| `76d2fd3d8d10d89a721b` | `06cac2c4b094ac1ed38ac40b` |
| `611f16dc9257f3546c08` | `3bd44a894ede5aaa695bb066` |
| `239b8589884a12d01a7a` | `1d9a63afb35357c5f06f5170` |

## Parejas conservadas como unresolved

No se completaron por obligación numérica; requieren más evidencia y quedan con `no_new_merge`.

- `6b84e4c69373bcadad41` — Alto Las Condes ↔ Cenco Alto Las Condes: Alto Las Condes mezcla menciones de varios desarrollos; Cenco es una etiqueta corporativa. La evidencia no aísla qué activo representa cada ID.
- `7d3556ba528bb38bd627` — Carlos Valdovinos ↔ proyecto de SuKasa en avenida Carlos Valdovinos: Carlos Valdovinos aparece en un registro contaminado por otros proyectos; la mención SuKasa no prueba que el ID amplio sea ese proyecto.
- `d0fb99d977176b8fd90c` — Chaguay ↔ Reserva La Dehesa, exChaguay: Chaguay aparece dentro de un registro con otros proyectos precordilleranos. “Reserva La Dehesa, exChaguay” sugiere continuidad, pero no identifica una sola entidad del cluster.
- `d05ad73929fbcd8a82b6` — Humedal San Luis ↔ Humedal San Luis Norte: Una fuente secundaria distingue Humedal San Luis y Humedal San Luis Norte, pero falta delimitación oficial para afirmar si son polígonos separados o subunidades.
- `871166e38c932b2ee95c` — Mega proyecto inmobiliario de 25 edificios en altura, calle Vital Apoquindo números 1.400, 1450 y 1.500 ↔ Vital Apoquindo: El cluster Vital Apoquindo apunta a un desarrollo común, pero alterna conteos de 25/27 edificios y etiquetas competidoras; no fusionar una parte aisladamente.
- `6af7e1570bff9ddbb3be` — Mega proyecto inmobiliario de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500 ↔ Vital Apoquindo: La mención coincide con el cluster Vital Apoquindo, pero las cifras 25/27 y los IDs competidores impiden cerrar este enlace por separado.
- `f46e5517d7ecee26f64d` — Recreo ↔ proyecto ubicado en calle Recreo: “Recreo” puede ser sector y el proyecto en calle Recreo un desarrollo puntual; falta rol/dirección o titular compartido que los conecte.
- `7dfca97fba3dc5d6abd2` — Reserva La Dehesa, exChaguay ↔ Reserva La Dehesa: Reserva La Dehesa exChaguay y Reserva La Dehesa pueden compartir historia, pero falta vínculo verificable de predio, RCA, rol o titular; Chaguay además integra un cluster mixto.
- `e4c1fbe6d25cd8141677` — Vital Apoquindo 1.400-1.450-1.500 ↔ Vital Apoquindo: El cluster Vital Apoquindo parece común, pero la fuente y los IDs mantienen discrepancias de alcance/conteo; no se propaga identidad desde otra pareja.
- `8171815b9845b0a3eb2c` — cuatro megaproyectos seguidos emplazados en calle Toro Mazzote ↔ cuatro megaproyectos seguidos emplazados en calle Toro Mazzote, de la Inmobiliaria SuKsa: Ambas menciones describen una colección de cuatro megaproyectos contiguos en Toro Mazzotte, no un proyecto individual; se conserva referencia agregada sin fusionar entidades singulares.
- `facad8bf50f968e5f69a` — iniciativa de más de 1.700 departamentos en Plaza Egaña ↔ Plaza Egaña: El acta COSOC y la mención Plaza Egaña no aportan dirección, titular, permiso ni atributos para identificarla con la iniciativa de 1.700 viviendas.
- `be23ed3f93026a81292d` — proyecto de 25 edificios en la calle Vital Apoquindo ↔ Mega proyecto inmobiliario de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500: El proyecto detallado y el ID genérico parecen del cluster Vital Apoquindo, pero hay desacuerdo 25/27 y canonicals competidores; no merge aislado.
- `3695e490944a9c19c06d` — proyecto de Rotonda Atenas ↔ vivienda sociales en la Rotonda Atenas: La columna de 2018 habla de viviendas sociales anunciadas en la Rotonda Atenas, pero no aporta dirección/unidades para probar que esa mención sea la torre construida después.
- `70097cb05f72215db4b3` — proyecto de dos torres de 30 y una de 32 pisos ↔ dos torres de 30 y 32 pisos, con 295 departamentos en total y casi 35 mil metros cuadrados construidos: Las fuentes difieren entre dos torres de 30 y una de 32, versus dos torres de 30 y 32; sin titular/ubicación coincidentes, no merge.
- `19a17e893f4747e113e9` — proyecto inmobiliario Bellavista ↔ proyecto Bellavista: Bellavista puede referir al desarrollo DIB de Dardignac 44, pero el ID es amplio y el cluster incluye campus, edificio y torres de distinta granularidad; falta delimitarlo.
- `4b4059b24dd41fe0f032` — proyecto inmobiliario de Fundamenta ↔ proyecto inmobiliario de Fundamenta en Ñuñoa (4 torres de 32 pisos): Ambos registros apuntan a Fundamenta en Ñuñoa, pero difieren entre tres residenciales más una oficina y cuatro torres de 32; falta identificación predial/RCA inequívoca.

## Decisiones de límite

- Ukamau se conserva como organización/mención descriptiva; no se fusiona con Barrio Maestranza ni con un proyecto habitacional.
- Los grupos Vital Apoquindo y Bellavista se mantienen parcialmente abiertos para evitar propagación transitiva mientras haya discrepancias de alcance/granularidad.
- Los pares de componente, predio, plan, tienda, torre o infraestructura quedan separados; las relaciones sugeridas no se guardan hasta definir el contrato tipado.
- El artefacto no promueve ni aplica decisiones. Una reconstrucción posterior debe pasar sus gates de evidencia/topología y el gate histórico de publicación.
