# Hallazgos abiertos y verificación final — 2026-09-12

## Estado actualizado — 2026-09-13

El hallazgo 1 queda corregido para futuras corridas: los eventos
`query_completed` llevan `query_hash` y `plan_version`, la reanudación estricta
usa ese hash y la identidad se conserva en el lineage downstream. El hallazgo 2
queda mitigado en el corpus provisional: `corpus_scope` fue materializado en
las 783 clasificaciones y los registros legacy puros se excluyen de corridas
futuras. Ambos siguen condicionados a un snapshot v3 posterior al cierre del
discovery activo; no constituyen un cierre final del corpus actual.

## 1. Discovery: reanudación por consulta (abierto, no tocar mientras corre)

`brightdata_discovery.py::already_queried_combos()` considera completa una
combinación `(comuna, termino, periodo, nivel)` apenas existe una fila. Si el
proceso muere después de escribir los primeros resultados orgánicos, al
reanudar salta toda la consulta y pierde los rangos restantes. El manifest
actual no guarda `query_started`, `query_completed` ni el conjunto de ranks
observados, por lo que no permite distinguir una consulta completa de una
parcial.

Verificación actual: el manifest tenía 5.926 filas válidas, 633 combinaciones
con alguna fila y 1.711 combinaciones aún sin filas de un plan de 2.336. No se
infiere que las 633 estén completas; falta un marcador explícito. El archivo
seguía escribiéndose a las 16:03, por eso no se modificó el script.

Corrección recomendada después del cierre del discovery: escribir eventos
`query_started`/`query_completed` por combinación y reanudar por
`query_id`+`rank`; una fila orgánica nunca debe marcar completa la consulta.

**Actualización 2026-09-12:** el código ya incorpora `query_completed` y el
snapshot excluye esos eventos de control. El proceso actualmente activo fue
cargado antes del fix: su manifest tenía 10.218 filas y 0 marcadores al último
chequeo. La lógica nueva es correcta para futuras corridas, pero la transición
es conservadora y puede repetir los 2.336 combos completos; no se debe crear un
backfill de completitud sin evidencia por consulta.

## 2. Corpus mixto (abierto, provisional)

El snapshot usado para la reparación (`20260912_153729_835`) es pre-v3 y no
tenía `contract_version`. La reparación recuperó lineage para 1.964 filas,
pero 67 filas siguen sin `periodo`/`nivel` y deben aislarse antes de declarar
válida la producción v2. El código nuevo exige `discovery_snapshot_v3` y
`contract_version=discovery_v2` para futuras corridas.

## 3. JSONL corrupto (corregido)

El lector tolerante sigue disponible para reanudación, pero ahora admite
`fail_on_invalid=True`. Dedupe y reparación usan ese modo estricto para no
publicar una vista materializada incompleta ni reescribir un archivo
silenciosamente perdiendo líneas.

## Evidencia de cierre de esta revisión

- 9 pruebas locales de integridad: OK.
- AST de 8 scripts: OK.
- JSONL real validado en modo estricto: fulltext 1.964 filas, eventos dedupe
  1.964, vista dedupe 1.964, clasificaciones 783.
- 67 registros `legacy_like_fulltext` detectados explícitamente.
- No se ejecutaron llamadas API en esta revisión.
