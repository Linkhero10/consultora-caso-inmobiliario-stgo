# Cierre de identidad PROJECT — 2026-09-29

**Estado:** cola de identidad PROJECT sin pares abiertos. Reconstrucción integral ejecutada sobre la rama `codex/historical-case-references`; no promovida a `main` (requiere fusionar el PR #1).
**Regla aplicada:** identidad exige evidencia positiva por los IDs exactos. Mismo nombre, mismo desarrollador o misma calle no bastan. Cuando falta esa evidencia el par queda separado como `insufficient_evidence`, que **no afirma** que los objetos sean distintos.

## Resultado

| Métrica | Valor |
|---|---|
| Proyectos / `case_id` / conflictos | 942 / 835 / 817 |
| Cola de identidad (258 pares) | 119 `merged`, 139 `kept_separate`, 0 abiertos |
| `integrity_check` / FK | `ok` / 0 violaciones |
| SHA-256 `data/warehouse.sqlite` | `9c4d2da86daebf19b1b84aa6007687fc503aecd61cd54ce45eb5e20a5abd4179` |
| Overlay v3 (SHA-256 fijado en el resolver) | `82f8b1d409562033a244fe266be0f75bd42b2c153cd3251d08cd5507d5fc3626` |
| Tests | 366 aprobados, 1 omitido (excluido `test_blind_review_html.py`, archivo local fuera del repo) |

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

**Efectos medidos:** relaciones pendientes 1 → 0; conflictos 817 → 816 tras la fusión de Recreo (ver addendum v4); `n_actores_caida_solo_por_gate_documental` 67 → 66 porque los vínculos de actor del documento salen de la vista `case_safe`.

**No se hizo:** los dos `document_conflict` del documento conservan el rol `panoramic_mention` que fijó la relación de Sol, así que siguen fuera de las vistas `safe` y de la red de actores. Incluir a La Victoria en la red exigiría adjudicar como `focal` el conflicto de Población La Victoria; no se hizo.

## Addendum — revisión de los tres expedientes insuficientes (candidato v4, 2026-09-29)

Se revisaron las tres identidades restantes por ID y por objeto, buscando evidencia primaria cuando estuvo disponible. El overlay v3 se preserva; las adjudicaciones nuevas están en `audit/project_identity_adjudication_overrides_2026-09-29_v4.json`. Este overlay permanece como candidato: `production_promoted=false`, el warehouse publicado no se reconstruyó y no se publicó dashboard ni manifest.

### Recreo ↔ proyecto en calle Recreo — misma identidad, alta confianza

Se cambió únicamente el par exacto `0a9d6730e059f72c2cdec2d8` ↔ `ad2b70567df6b8d44f952100` de `insufficient_evidence` a `same_identity`. La resolución SEA Exenta 528/2017 identifica “Edificio Recreo”, Inmobiliaria Recreo 321 SpA y las direcciones Recreo 321/331; la resolución MINVU Exenta 1802/2025 vuelve a vincular la sociedad con el proyecto de Recreo 321 y su controversia de recepción. El oficio CGR E547184/2024 lista “Recreo 321” y su Permiso de Edificación N.º 221, aprobado el 13-10-2016, más la solicitud de modificación N.º 5. La copia consultada de ese oficio está hospedada en un tercero, no en el dominio de Contraloría; el propio PDF muestra folio y código de validación. Interferencia y CIPER describen los proyectos de Su Ksa en Recreo, y La Tercera nombra Recreo 321 entre los edificios con recepción pendiente. La identidad se sustenta en la convergencia de nombre, dirección, sociedad, permiso y trayectoria del conflicto, no solo en desarrollador/calle compartidos.

La fusión es exclusivamente de identidad PROJECT. En particular, la mención de CIPER sigue vinculada a su propia `case_mention` excluida: no se transfiere ni altera elegibilidad, decisión ni evidencia entre menciones. No se reconstruyó el warehouse para producción.

### Santa Petronila — permanece `insufficient_evidence`

La tabla de permisos reproducida por el artículo académico de Revista de Urbanismo (datos atribuidos a la Municipalidad de Estación Central, 2019) registra Santa Petronila 22 (338 departamentos), 28 (438) y 38 (616), mientras asigna 1.053 departamentos a Coronel Souper 4058–4060. Hogar de Cristo atribuye 1.053 departamentos a la megatorre que llama de Santa Petronila; El Ciudadano identifica otro edificio de PAZ Corp. en esa calle, sin numeración predial. El desajuste es una alerta de localización, no evidencia suficiente para afirmar que los dos IDs son distintos ni que son el mismo activo. No se fusiona. Para reabrir: dirección/rol/permiso DOM del edificio PAZ y correspondencia oficial de la torre descrita por Hogar de Cristo.

### Alto Las Condes ↔ Cenco Alto Las Condes — permanece `insufficient_evidence`

El ID `Alto Las Condes` agrupa menciones al mall existente y a “Alto Las Condes 2”. Cenco identifica su mall en Av. Presidente Kennedy 9001; la prensa ubica Alto Las Condes 2 en Kennedy 8950, frente al mall, y describe usos mixtos. Una fusión global contaminaría las menciones de la ampliación con la identidad del centro comercial. No se fusiona ni se afirma diferencia para todas las menciones. Para reabrir: separar primero las menciones del ID agregado entre mall existente y proyecto Alto Las Condes 2, y adjudicar cada subgrupo con evidencia propia.

### Resultado de la simulación y cierre de alcance

La simulación en SQLite en memoria cambió una sola fila previamente cerrada, Recreo, de `kept_separate` a `merged`; dejó 256 pares (119 `merged`, 137 `kept_separate`, 0 `needs_human_review`). Validó 273/273 referencias literales, `integrity_check=ok`, cero violaciones FK y cero bloqueos topológicos. La fila resultante enlaza explícitamente el overlay v4, su SHA y las referencias de evidencia. El warehouse de entrada conservó su SHA-256 `0af8c08c812113ccb1aac3895783438644b28cdd0ea8bd73c077901aadbe7d47`; el overlay v4 tiene SHA-256 `58ab0191c454a7eab7fa2651ef507ebf39b5c8190c0684e40a4d3d9895d530c3` y el informe de simulación SHA-256 `a65f310e2a760a00d2450382fa392e89459418227d5b0c7aa8eac7c9982403f7`. La relación de Población La Victoria ya figura `resolved_keep_separate`; los 29 IDs históricos sin destino se conservan sin alias, sin bloquear la topología por la política vigente.

**Cierre:** los tres expedientes ya no requieren más búsqueda indiscriminada. Recreo queda adjudicado en el candidato v4; Santa Petronila y Alto Las Condes quedan cerrados por ahora como insuficiencia documentada, con criterios concretos de reapertura. La cola revisada queda sin pares abiertos. Cualquier promoción del candidato requiere la decisión de release correspondiente; este trabajo no la ejecutó.

## Addendum — v4 aplicado en la reconstrucción (2026-09-29)

El overlay v4 de Luna (Recreo `same_identity`) se verificó (CI verde sobre `67e91ba`) y se aplicó en una reconstrucción integral posterior: cola 119 `merged` / 137 `kept_separate` / 0 abiertos, 941 proyectos, 834 `case_id`, 816 conflictos, warehouse `33343379f8b2f267e66af08926b1938e7019a6b0c618e710c76e79f5b87a9ecc`, 358 tests aprobados y 1 omitido. La tabla de arriba refleja este estado. Sigue sin verificarse que la mención de CIPER nombre el número 321: el vínculo se sostiene en que SEA y MINVU identifican un único proyecto de Inmobiliaria Recreo 321 SpA en calle Recreo y en que la fuente del oficio CGR es una copia en sitio tercero.

## Addendum — normalización de `Lote 18-A` (2026-09-29)

La auditoría de huecos de Luna detectó que `normalize_project_name` borraba la `A` de `Lote 18-A` (la puntuación la separaba y `a` cae como stopword) y lo colapsaba con `Lote 18`, aunque las fuentes distinguen el lote completo de una parte. **Corrección:** un sufijo de letra pegado por guion a un número se conserva (`lote 18a`). Solo cambian 2 de los 988 nombres del corpus (`Lote 18-A`, `Lote 18-A1`); los rangos con guion y los nombres con ` - a ` con espacios no se alteran (test).

**Adjudicación:** `Lote 18` ↔ `Lote 18-A` y `Lote 18-A` ↔ `Lote 18-A1` quedan `kept_separate` (relación parte–todo; La Tercera 2017 distingue «todo el Lote 18» de «la parte del Lote 18-A que controla» y usa `Lote 18-A1` para el lote declarado Monumento Nacional). La decisión heredada `Lote 18` ↔ `Lote 18-A1` (`merged`) no se tocó: no se auditó.

**Efectos:** 941 → 942 proyectos, 834 → 835 `case_id`, 816 → 817 conflictos, cola 256 → 258 pares (119 merged, 139 kept_separate). El identificador de `Lote 18-A1` cambió (`23c289bb…` → `e08d8d72…`), lo que rompía una referencia histórica de Sol; se agregó un alias en `config/historical_case_id_resolutions_v1.json` hacia el caso `124a6f29…` que ella ligó como `mismo_conflicto`/`parent_subproject`. El baseline se regeneró con `src/generate_project_case_baseline.py`. Un actor (`inmobiliaria lote 18`) pasa a caer también por el gate documental (66 → 67), verificado comparando los grados contra el warehouse anterior.
Warehouse `33343379f8b2f267e66af08926b1938e7019a6b0c618e710c76e79f5b87a9ecc`; 361 tests aprobados y 1 omitido.
