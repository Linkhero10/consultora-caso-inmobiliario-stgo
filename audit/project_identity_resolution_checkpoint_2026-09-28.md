# Checkpoint — reconciliación de identidad PROJECT (2026-09-28)

## Alcance y decisión

Checkpoint de una simulación aislada de `resolve_project_review.py` y del preflight de
referencias históricas. Se mantienen las reglas aprobadas: no crear aliases por semejanza nominal;
preservar referencias históricas sin forzar identidad; `Ukamau` como organización queda como
mención descriptiva, sin `project_id`; el conjunto habitacional Barrio Maestranza sí puede
identificarse separadamente cuando la evidencia describe esa misma unidad. La publicación completa
permanece bloqueada mientras existan pares PROJECT de impacto topológico sin decisión.

## Insumos y reproducibilidad

- Snapshot SQLite de entrada de la rama: `data/warehouse.sqlite`, SHA-256
  `685af6a951356c0c7e7249525fcb89362f8801a4c259f614571d775fb329c33c`.
- Checkout publicado en `main` al verificar: SHA-256
  `378bf7d7686d676dfb1e08cb5c141a2e5bea29b943ad0de6ef4f58d0900c09db`; no se modificó.
- Evidencia local de fulltext y paquete clasificado de `conflict_unit_63` se pasan como argumentos
  a `audit/simulate_project_identity_resolution_2026_09_28.py`; sus hashes exactos y los de cada
  dependencia están en el reporte JSON.
- Comando de reproducción, desde la raíz del repo (sin API ni escritura a la SQLite fuente). Los
  dos insumos locales se mantienen fuera del repositorio; sustituye los marcadores por sus rutas
  disponibles en tu equipo:

  ```powershell
  python audit/simulate_project_identity_resolution_2026_09_28.py `
    --evidence-root <FULLTEXT_CONTENT_DIR> `
    --classified-63 <CLASSIFIED_CONFLICT_UNIT_63_JSON>
  ```

- Reporte completo: [`project_identity_resolution_simulation_2026-09-28.json`](project_identity_resolution_simulation_2026-09-28.json).
- Última reproducción registrada: `2026-09-28T21:42:13Z`; SHA-256 del reporte:
  `1cbd291680339fec47a75865e45d8dbf4749e5b52b5d68ec4e36bc9d68098335`.
- Builder reproducible del suplemento histórico: `audit/build_historical_project_pair_adjudications_2026_09_28.py`.

## Resultado de los 52 pares inicialmente abiertos

La cola tenía 256 filas: 117 `merged`, 87 `kept_separate` y 52 `needs_human_review`. La
simulación adjudica los 52 abiertos así:

| Decisión simulada | Pares |
|---|---:|
| `kept_separate` | 37 |
| `merged` | 7 |
| `needs_human_review` | 8 |

Las siete fusiones exactas quedaron justificadas con evidencia por pareja en el overlay y el
reporte. Las 37 separaciones conservan ambos IDs; no borran entidades ni implican que no estén
relacionadas. Las ocho irresueltas se conservan abiertas por colisión de identidad, granularidad o
evidencia insuficiente: Chaguay/Reserva La Dehesa; Plaza Egaña (pareja de la fila 53); Alto Las
Condes/Cenco Alto Las Condes; Reserva La Dehesa/exChaguay; Recreo/calle Recreo; Fundamenta/Ñuñoa;
dos torres de 30/32 pisos; y proyecto Bellavista/Bellavista.

## Decisiones cerradas anteriores que cambiaron

La simulación también revisó todas las decisiones que el nuevo conjunto de evidencia podía
contradecir. Doce filas previamente cerradas cambian de estado; no se ocultó este efecto:

| Transición | Pares |
|---|---:|
| `merged` → `kept_separate` | 8 |
| `merged` → `needs_human_review` | 2 |
| `kept_separate` → `merged` | 2 |

Los ocho casos que pasan a separación son La Platina/seccional; Bosque Panul/subdivisión;
Laguna artificial/Parque Padre Hurtado; Conjunto Armónico Bellavista/una torre; Mall Sport/su
ampliación; y tres filas que mezclaban la torre Bellavista con el proyecto Bellavista. Se reabren
Santa Petronila (la calle contiene proyectos de granularidad distinta) y Costanera Center/Cenco
Costanera (el ID de fuente mezcla activo e iniciativas corporativas). Se fusionan Nueva El Golf,
con identidad de proyecto respaldada en las fuentes revisadas, y el conjunto habitacional Barrio
Maestranza/Ukamau. Esta última decisión no asigna identidad de proyecto a la organización Ukamau.
IDs, citas y hashes por fila están en el JSON de simulación.

## Estado del gate y límites

- Después de simular las decisiones: 116 `merged`, 130 `kept_separate` y 10
  `needs_human_review` en la cola (256 filas). Los 10 bloqueos son las ocho filas abiertas que
  siguen pendientes más las dos decisiones anteriores que se reabren.
- El preflight histórico simulado preserva 29 referencias sin destino verificado, incluidas cinco
  marcadas como no resolubles; ninguna afecta la topología bajo la política registrada. Eso no
  autoriza inventar aliases ni borrar esas referencias.
- El preflight histórico anterior (`audit/historical_case_reference_preflight.json`) lleva otro
  hash de warehouse (`f89ecd5…`) y está obsoleto para el snapshot usado aquí. No se cita como
  prueba vigente.
- La SQLite se abrió en modo de solo lectura y se simuló sobre una copia en memoria. Integridad:
  `PRAGMA integrity_check = ok`; cero errores de claves foráneas; hash de origen igual antes y
  después.
- `production_promoted=false`, `full_conflict_rebuild_executed=false` y no se publicaron dashboard
  ni manifiesto. La capa CONFLICT que ya aparece en la SQLite de rama es preexistente; sus 819
  filas **no** fueron reconstruidas con esta reconciliación.
- Suite completa del repo: 346 aprobadas, 5 omitidas. La primera ejecución en sandbox no pudo
  crear `tmp_path` ni los temporales predeterminados bajo `D:\Temp`; el conteo válido se obtuvo al
  dirigir ambos a una carpeta temporal aislada con permisos. Las omisiones se conservan como skips
  declarados por la suite, no se cuentan como aprobaciones.
- El snapshot publicado en `main` (941 proyectos, 850 `case_id`, 833 filas de conflicto) también
  permanece intacto. No presentar la simulación ni ninguna de esas capas preexistentes como una
  reconstrucción integral validada.

## Próximo gate

Resolver con evidencia específica los 10 pares todavía ambiguos — o documentar formalmente que su
relación permanece desconocida si el dato no existe. Luego repetir el simulador, obtener cero
bloqueos topológicos, reconstruir la cadena derivada en una copia, verificar conteos/relaciones,
pruebas e integridad y solo entonces preparar una propuesta de publicación. Este checkpoint no
autoriza por sí mismo reconstruir ni publicar el warehouse.
