# Cierre de los huecos de datos — 2026-09-29

Trabajo posterior a la auditoría de huecos de Luna (rama local `audit-open-data-gaps`, informes no publicados). Se atendieron sus tres seguimientos sobre el warehouse vigente.

**Warehouse:** `9f328ad4884b26f1b49e98ab2b7c889e6438384e208b41eefd024d2598828926` · 942 proyectos · 835 `case_id` · 817 conflictos.

## Resultado

| Hueco | Antes | Después |
|---|---:|---:|
| Menciones sin `case_mention_index` | 227 | 209 |
| Conflictos con respaldo de evidencia | 488 | 498 |
| Conflictos sin respaldo detectado | 329 | 319 |
| Referencias históricas con identidad sin resolver | 1 (Alto Norte) | 0 |

## 1. Menciones sin índice (perfil de 227)

Se adjudicó una por una cada una de las 26 candidatas del perfil (20 unívocas, 6 ambiguas) y 2 menciones focales que la regla literal no alcanzaba.

- **17 enlaces** (`config/verified_project_mention_index_corrections_v1.json`): 15 de las 26 y 2 focales (Hotel Sheraton 2021, Parque Mapocho). Cada uno cita el `evidence_id` verificado y su texto, y un test comprueba que la case_mention es `include`, que la evidencia existe en el warehouse y que la cita aparece en el fulltext.
- **11 de las 26 no se enlazaron:** `Renca` (nombre de comuna), `Torre Entel` (hito, no el proyecto), `complejo deportivo Titán`, `Estadio Nacional`, `Remodelación Parque San Luis`, `Manantiales`, `Autopista Costanera Sur` (la cita trata otro objeto), `Ciudad de Los Valles`, `Izarra de Lo Aguirre`, `La Cumbre Oriente` y `Mirador Pie Andino` (los candidatos son `exclude`).
- Las dos ambiguas de duplicado (Cerrillos Data Center; Vespucio / Renato Sánchez) se enlazaron a la `case_mention` canónica del grupo duplicado, porque ambas describen el mismo objeto.
- **Quedan 209 sin índice:** las 11 candidatas no enlazadas y 198 sin candidata literal. La cuenta de 18 enlaces materializados incluye el de Línea 7, que ya estaba configurado pero no había surtido efecto (ver abajo). Enlazar las 198 exige una revisión semántica de cada una.

**Defecto encontrado y corregido:** las correcciones de índice solo se aplicaban a los registros en memoria del registro de proyectos, que no usa el índice. Ninguna llegaba a `enrichment_project_mention`, la tabla que consumen CONFLICT y geografía, así que el enlace de Línea 7 ya existente nunca tuvo efecto. `build_projects.py` ahora las materializa en la tabla y falla si una corrección no encuentra exactamente una mención sin índice.

## 2. Los 133 conflictos con el nombre en una cita verificada

Detalle por conflicto en `audit/eligibility_review_133_2026-09-29.json`.

| Veredicto | Conflictos |
|---|---:|
| A · fuera del área de estudio (otra región o país) | 38 |
| B · mención pasajera, ejemplo o comparación | 49 |
| C · no es una disputa (listado, perfil, decreto, lobby, inversión) | 27 |
| D · disputa real pero secundaria dentro de un documento cuyo caso principal es otro | 17 |
| U · elegibilidad adjudicada a `include` | 2 |

La exclusión de etapa 1 se confirmó en 131 de 133. Las dos adjudicaciones (`config/case_mention_eligibility_adjudications_v1.json`) son el permiso N.º 68/2013 del edificio de la CChC en Las Condes y los terrenos del ex vertedero Departamental de Macul. Solo afectan el respaldo de evidencia, quedan marcadas con `match_method='v3_3_verified_index_adjudicated_eligibility'` y no modifican `case_mention.decision_final_amplio`.

Los 12 vínculos focales se revisaron: Puyai, Collahuasi y Punta Piqueros están fuera del área de estudio; Patio Chiloé es un perfil de arquitectura; Parque Pumpin (Valparaíso) y Club de Campo Vitacura (una noticia de inversión) no son disputas del área; CChC y ex vertedero se adjudicaron; Sheraton, Vespucio / Renato Sánchez y Parque Mapocho se resolvieron con enlaces; queda sin adjudicar Pastor Fernández 18.580 (dos case_mention plausibles).

## 3. Alto Norte

El propio artículo de Diario Financiero (2023) llama «Alto Norte» al permiso de edificación caducado del proyecto Alto Las Condes 2 («el fallo de segunda instancia que declaraba caducado el permiso de edificación de Alto Norte»). Sol ya había adjudicado la relación `mismo_proyecto`/`alias` con `5f33de46…`, hoy fusionado en el caso `008d2f36…` (Alto Las Condes 2). Se agregó el alias `a05fdf04… → 008d2f36…` en `config/historical_case_id_resolutions_v1.json`, citando la clasificación de Sol. Las memorias 2020-2021 de Cencosud y el registro de Ley Lobby que reunió Luna apoyan el mismo vínculo; no se leyó el expediente de la DOM.

## No verificado

- No se revisaron semánticamente los 196 conflictos sin respaldo que no están entre los 133; su diagnóstico sigue siendo el estructural de Luna.
- Las 198 menciones sin candidata literal siguen sin índice.
- Los 79 grupos con señales de riesgo de fusión automática no se adjudicaron uno por uno.
- La lectura de los 133 fue de contexto por conflicto, no de cada documento completo; las fuentes externas que apoyan Alto Norte no se guardaron con hash.
