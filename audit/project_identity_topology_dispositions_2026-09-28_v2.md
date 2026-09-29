# PROJECT identity topology — cierre de adjudicación acotada v2

**Fecha:** 2026-09-28 · **Rama:** `codex/historical-case-references` · **Estado:** decisión de desarrollo simulada; `production_promoted=false`.
**Regla:** identidad requiere evidencia positiva por los IDs exactos. Parecido nominal, misma calle, mismo documento o pertenencia a un complejo no bastan. Si falta el dato que distingue identidad de relación parte/entidad, se conserva `unresolved`; no se fuerza un merge para despejar el gate.

## Resultado ejecutivo

La lista de diez bloqueos materiales que venía del checkpoint anterior queda así:

- **2 adjudicados en el overlay candidato v2, sin promover a producción:** una separación y una identidad común.
- **8 siguen irresueltos**. No son ocho decisiones olvidadas: para cada una queda escrito qué dato nuevo permitiría reabrirla. Hasta entonces no se repite la misma búsqueda ni se cambia el estado por inferencia.

La cola completa tenía 256 filas. De las 52 inicialmente abiertas, la simulación resolvió 38 como `kept_separate`, 8 como `merged` y dejó 6 abiertas. Además, reabrió 2 fusiones históricas cuya evidencia era solo una reconexión por substring. Estado final simulado: **117 merged, 131 kept_separate, 8 needs_human_review**. Esas ocho son las seis restantes del grupo inicial más las dos reabiertas (Santa Petronila y Costanera Center).

La simulación se hizo en memoria, con SQLite fuente en solo lectura. SHA-256 del warehouse de la rama antes/después: `685af6a951356c0c7e7249525fcb89362f8801a4c259f614571d775fb329c33c`; `integrity_check=ok`; cero violaciones de FK. **La publicación integral continúa bloqueada** por los ocho pares; el gate de referencias históricas, por separado, queda claro con cinco referencias no resolubles preservadas y sin alias inventados.

## Dos disposiciones nuevas

| Fila / pair_id | IDs exactos | Disposición candidata | Fundamento y límite |
|---|---|---|---|
| 53 / `facad8bf50f968e5f69a` | `89ddfb0616d12dccc7393b63` — iniciativa residencial de >1.700 departamentos en Plaza Egaña; `cf65c362a0dd71489735dc57` — Plaza Egaña | `distinct_entities`, `no_new_merge` | El acta COSOC usa Plaza Egaña como comparación urbana al hablar de Parque Bustamante; no identifica la iniciativa de 1.700 departamentos. La sentencia R-231-2020 identifica aparte Egaña–Comunidad Sustentable. Fuentes en el override v2. No se crea relación tipada entre estos IDs. |
| 175 / `4b4059b24dd41fe0f032` | `bb5755a35f19ada504ca13a4` — proyecto inmobiliario de Fundamenta; `de08d293dbbdbbb72d27e6ae` — Fundamenta en Ñuñoa (cuatro torres) | `same_identity`, `merge_case`; canónico propuesto `bb5755a35f19ada504ca13a4` | La sentencia primaria R-231-2020 coincide en ubicación, titular/proyecto y controversia de sombras; sus atributos oficiales permiten explicar la discrepancia de altura reportada por prensa sin inferir una segunda obra. Se elige el ID histórico de la referencia de 2022 por cronología, no por nombre más completo. Ambos IDs y sus atributos quedan preservados. |

Estas dos decisiones son **solo del overlay de simulación**: el resolver las aplica en memoria, pero no se editaron la SQLite publicada, el dashboard ni el manifiesto de release.

## Ocho pares mantenidos `unresolved`

| Fila / pair_id o referencia heredada | IDs y nombres | Por qué no se decide | Evidencia concreta que permitiría reabrir |
|---|---|---|---|
| 40 / `d0fb99d977176b8fd90c` | `803b8601f7f58a2b25f694cd` Chaguay ↔ `a07066976e35eb7bd807ed77` Reserva La Dehesa, exChaguay | La continuidad nominal está respaldada, pero el ID Reserva La Dehesa participa en un cluster que también contiene la iniciativa de Cerro del Medio. Un merge ahora perpetuaría una identidad compuesta. | Separar la procedencia por mención y obtener RCA, rol predial, permiso o expediente que vincule inequívocamente cada ID con el mismo emprendimiento. |
| 61 / hash histórico `525f3354f72e86bc12ad5d71c7200f5fecb1aa4780ff6dc949c69ce957c03e08` | `14537e43f763c717791c5b90` Edificio Santa Petronila ↔ `00a49b2fac5c7887f0c4f628` edificio de la estrecha calle Santa Petronila | El merge previo se reconectó desde una decisión histórica mediante substring. La calle tiene más de un desarrollo plausible; los atributos publicados no fijan el mismo predio/permiso. | Dirección exacta o rol predial compartido, permiso DOM/RCA, titular y configuración que identifiquen la misma obra en ambas menciones. |
| 79 / hash histórico `2d6976f1632fca7ab343288bb69b25facae01aa7c15baaf6982a41d9ef058278` | `e8fd7b147a07358cd8e129e9` Costanera Center ↔ `d18b439c5be31864ad8f1e21` Cenco Costanera (antes Mall Costanera Center) | La reconexión histórica decía “mismo mall”, pero el primer ID puede representar el complejo urbano y el segundo el activo comercial. Identidad y relación componente–complejo son preguntas distintas. | Fuente oficial de Cencosud/registro de activos y plano o expediente que delimite el alcance de cada ID. Si confirma relación parte–todo, registrar relación tipada, no fusionar identidades. |
| 84 / `6b84e4c69373bcadad41` | `2cfcdb67a6274db8af9377f6` Alto Las Condes ↔ `2a40c16d17565173915c550d` Cenco Alto Las Condes | El ID Alto Las Condes mezcla menciones del mall existente y desarrollos/ampliaciones; “Cenco” puede ser marca o activo. No está claro qué unidad representa cada ID. | Delimitar cada ID a un activo/etapa y comprobar con permiso, expediente ambiental, dirección/rol y titularidad coincidentes. |
| 93 / `7dfca97fba3dc5d6abd2` | `a07066976e35eb7bd807ed77` Reserva La Dehesa, exChaguay ↔ `01d6668a9dc5aba908f81090` Reserva La Dehesa | Una fuente refiere 54 casas en Cerro del Medio; otra usa exChaguay. La procedencia de ambos IDs está contaminada y no permite afirmar ni identidad ni diferencia definitiva. | Inventario de menciones fuente por ID y un identificador oficial común o distinto (RCA, rol, permiso, predio, titular). |
| 126 / `f46e5517d7ecee26f64d` | `0a9d6730e059f72c2cdec2d8` Recreo ↔ `ad2b70567df6b8d44f952100` proyecto ubicado en calle Recreo | La SEA identifica Edificio Recreo en 321/331, pero la otra referencia a proyectos de calle Recreo no entrega un vínculo predial equivalente. Mismo sector/titular no basta. | Número, rol predial, permiso/RCA o titular y planos que confirmen que las dos menciones apuntan a la misma obra. |
| 193 / `70097cb05f72215db4b3` | `ffa5c9b29b95f230d34616d9` dos torres de 30 y una de 32 pisos ↔ `4648a378b2f533657c23de7a` dos torres de 30 y 32 pisos, 295 departamentos | Hay discrepancia en número/configuración de torres y no consta una clave común de sitio o titular. La similitud de atributos no identifica una obra. | Identificador de proyecto, dirección/rol, desarrollador, permiso o expediente ambiental que conecte ambas fichas; preservar las cifras como afirmaciones de fuente. |
| 226 / `19a17e893f4747e113e9` | `1c1f2a962eca459282a98baa` proyecto inmobiliario Bellavista ↔ `7a4072da49c6decfd6df3f01` proyecto Bellavista | Bellavista abarca referencias a campus, torre, conjunto y desarrollos de distinta granularidad; no se demuestra que estos dos IDs sean el mismo proyecto. | Dirección/predio y permiso/RCA/titular específicos que separen Dardignac 44, Conjunto Armónico y otras unidades del cluster. |

## Condición de reanudación: antibucles y anti-derivación

Este expediente y [`identity_resolution_execution_log_2026-09-28.md`](identity_resolution_execution_log_2026-09-28.md) son el checkpoint operativo para esta adjudicación. Al reanudar:

1. comprobar solo HEAD, hash del override, hash del warehouse y estado del CI;
2. si no cambió ninguno, **no volver a reconstruir las 52 adjudicaciones ni recontar los diez casos**;
3. avanzar únicamente si aparece uno de los tipos de evidencia especificados arriba, o si Felipe cambia la política de publicación;
4. no ejecutar otra búsqueda genérica sobre nombres ya investigados. Registrar una nueva búsqueda solo si está vinculada a una hipótesis/predicado verificable de una fila concreta;
5. una decisión `unresolved` con criterio de reentrada cumplido es un resultado válido, no una invitación a repetir la misma auditoría.

## Artefactos que fijan este resultado

- Overlay candidato, hash `1dc0cedb34e95a24bcb6d756d56a5be25f913742d0e3405ca400b04f9abd00c4`: [`project_identity_adjudication_overrides_2026-09-28_v2.json`](project_identity_adjudication_overrides_2026-09-28_v2.json).
- Simulación reproducible, hash `efeffd7ae9eed4989dc3c502a8e194b8676bdc8e049679992a1d3494f04bfb51`: [`project_identity_resolution_simulation_2026-09-28_v2.json`](project_identity_resolution_simulation_2026-09-28_v2.json).
- Base de la rama, hash `685af6a951356c0c7e7249525fcb89362f8801a4c259f614571d775fb329c33c`; se usó solo lectura.
- La salida v2 no autoriza una reconstrucción completa ni desbloquea publicación. El gate sigue bloqueado; para reabrir cada uno de los ocho pares se requiere la evidencia concreta indicada arriba y una nueva adjudicación explícita.
