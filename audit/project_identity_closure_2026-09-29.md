# Cierre de identidad PROJECT — 2026-09-29

**Estado:** cola de identidad PROJECT sin pares abiertos. Reconstrucción integral ejecutada sobre la rama `codex/historical-case-references`; no promovida a `main` (requiere fusionar el PR #1).
**Regla aplicada:** identidad exige evidencia positiva por los IDs exactos. Mismo nombre, mismo desarrollador o misma calle no bastan. Cuando falta esa evidencia el par queda separado como `insufficient_evidence`, que **no afirma** que los objetos sean distintos.

## Resultado

| Métrica | Valor |
|---|---|
| Proyectos / `case_id` / conflictos | 941 / 835 / 817 |
| Cola de identidad (256 pares) | 118 `merged`, 138 `kept_separate`, 0 abiertos |
| `integrity_check` / FK | `ok` / 0 violaciones |
| SHA-256 `data/warehouse.sqlite` | `ef776d1f9294021751d1b74f602523eaabe6d02e18f7d6b4b68c61bfa6d1436d` |
| Overlay v3 (SHA-256 fijado en el resolver) | `82f8b1d409562033a244fe266be0f75bd42b2c153cd3251d08cd5507d5fc3626` |
| Tests | 354 aprobados, 1 omitido (excluido `test_blind_review_html.py`, archivo local fuera del repo) |

## Los 8 pares que estaban abiertos

| Fila / pair_id | Decisión | Evidencia decisiva (fulltext del corpus, salvo indicación) |
|---|---|---|
| 40 `d0fb99d977176b8fd90c` Chaguay ↔ Reserva La Dehesa, exChaguay | `same_identity` (alta) | Interferencia y Terram: titular de Chaguay = Desarrollos La Dehesa SpA. Cooperativa 2025: «proyecto Reserva La Dehesa, exChaguay, de la empresa Desarrollos La Dehesa SpA». |
| 93 `7dfca97fba3dc5d6abd2` Reserva La Dehesa, exChaguay ↔ Reserva La Dehesa | `distinct_entities` (alta) | El único documento del ID «Reserva La Dehesa» (El Mostrador 2019) trata las 54 casas del Cerro del Medio. Kilómetro Cero (2022) las enumera como proyecto distinto de las parcelas de Chaguay (158 parcelas según Terram). Homonimia de nombre. |
| 126 `f46e5517d7ecee26f64d` Recreo ↔ proyecto en calle Recreo | `insufficient_evidence` | Ambas apuntan a un edificio de Su Ksa en calle Recreo, pero ninguna da número, rol ni permiso. |
| 84 `6b84e4c69373bcadad41` Alto Las Condes ↔ Cenco Alto Las Condes | `insufficient_evidence` | El ID Alto Las Condes mezcla el mall existente (2 menciones, 2014) con el proyecto Alto Las Condes 2 (3 menciones, 2020–2025). |
| 193 `70097cb05f72215db4b3` dos torres 30/32 pisos | `same_identity` (alta) | Emol 2022 y Diario Concepción 2023 describen el proyecto de Inmobiliaria Mirador del Cerro SpA junto al Hotel Sheraton Santiago y su permiso invalidado. La divergencia «dos de 30 y una de 32» vs «30 y 32» se conserva como atributo de fuente. |
| 226 `19a17e893f4747e113e9` proyecto (inmobiliario) Bellavista | `same_identity` (alta) | El Dínamo 2021 y La Tercera 2019: proyecto de Desarrollo Inmobiliario Bellavista S.A. en Recoleta, en conflicto con el alcalde Jadue. |
| 61 `historical_pair:8bf36944edfe85c618e0` Santa Petronila | `insufficient_evidence` | La calle tiene varios desarrollos; nada liga el edificio de PAZ Corp. con la megatorre de 1.053 departamentos. La fusión previa fue por subcadena de nombre. |
| 79 `historical_pair:1a548f6ba2417a0e6aae` Costanera Center ↔ Cenco Costanera | `parent_component_phase` | Complejo (torres, hoteles, oficinas, mall) frente a su componente, el mall (fuentes: Wikipedia en/es, Infobae). |

## Correcciones a decisiones legacy encontradas al cerrar

Dos fusiones heredadas por nombre contradecían las fuentes y bloqueaban el cierre por reconexión transitiva. Se revirtieron en `MANUAL_DECISIONS` con su justificación:

1. `Reserva La Dehesa` ↔ `Reserva La Dehesa (ex Chaguay)`: se había fusionado el proyecto de 54 casas del Cerro del Medio con Chaguay.
2. `proyecto Bellavista` ↔ `edificio de Desarrollo Inmobiliario Bellavista`: se había fusionado por compartir desarrollador; el edificio es de Estación Central y el proyecto es de Recoleta.

## Cambios de mecanismo

- Clase nueva `insufficient_evidence` (no fusiona, no afirma diferencia).
- El overlay ahora puede adjudicar pares del suplemento histórico (además de la revisión base de 68 pares). Overlay v3 (16 pares base + 2 históricos) reemplaza a v2; v1 y v2 se conservan sin modificar.
- `.gitattributes`: los artefactos con hash fijado se fuerzan a LF. Con `core.autocrlf=true` en Windows, el checkout alteraba los bytes y el resolver rechazaba el hash de la adjudicación base.
- Orden de reconstrucción del README: se agrega `detect_case_mention_duplicates.py`, requerido por CONFLICT.

## Lo que NO se verificó ni se resolvió

- Los tres `insufficient_evidence` no están demostrados como distintos ni como iguales; reabrir cada uno requiere el dato indicado en su rationale.
- No se re-auditó fuente por fuente el resto de las 256 decisiones; solo los 8 pares y las dos reversiones legacy.
- Las fuentes web externas (Wikipedia, Absal, SMA) se consultaron por búsqueda, sin guardar copia local con hash.
- Población La Victoria se cerró después, ver addendum. Siguen 29 referencias históricas preservadas sin alias, 5 de ellas confirmadas como no resolubles. Ninguna bloquea la publicación por diseño.
- El substring-reconnection (`_manual_decision_via_normalized_substring`) no se rediseñó.
- Producción: el warehouse, el dashboard y el manifiesto solo cambian en `main` cuando se fusione el PR #1.

## Addendum — Población La Victoria (2026-09-29)

La relación `same_document_distinct_conflicts` de Población La Victoria / Rancagua Express estaba `pending_human_decision` porque el documento (`34c26e5a...`) figuraba como `caso_unico`. Es un artículo académico (Revista Austral de Urbanismo, UACh) que recorre la historia de un solo asentamiento y desarrolla, con fechas y actores propios, la formación (1957), la regularización, las protestas contra el Plan Regulador de Pedro Aguirre Cerda (2005-2006) y contra el proyecto del tren a Rancagua (2012-2014).

**Decisión:** el documento pasa a `multiples_casos_documentados`. Con la definición operativa del pipeline (CONFLICT = grupo de `case_id` unidos por `mismo_conflicto`; `conflictos_distintos` = objetos que no se fusionan), son conflictos distintos unidos por territorio y actor colectivo. No es panorámico (cada episodio se desarrolla) ni caso único. La trayectoria común queda registrada como relación entre conflictos, sin fusionar; la relación pasa a `resolved_keep_separate`.

**Mecanismo:** `config/document_case_unit_decisions_v1.json`, aplicado en `build_enrichment_tables.py` de forma idempotente, con cita literal verificada por test contra el fulltext y sin sobrescribir una corrección distinta a la esperada. El pin `source_warehouse_sha256` del baseline se actualizó al hash reproducible desde el warehouse committeado.

**Efectos medidos:** relaciones pendientes 1 → 0; conflictos siguen en 817; `n_actores_caida_solo_por_gate_documental` 67 → 66 porque los vínculos de actor del documento salen de la vista `case_safe`.

**No se hizo:** los dos `document_conflict` del documento conservan el rol `panoramic_mention` que fijó la relación de Sol, así que siguen fuera de las vistas `safe` y de la red de actores. Incluir a La Victoria en la red exigiría adjudicar como `focal` el conflicto de Población La Victoria; no se hizo.
