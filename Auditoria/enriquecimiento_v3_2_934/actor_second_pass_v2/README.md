# Actor second pass v2 — estado de artefactos

## Estado vigente (2026-09-19)

El archivo canónico actual `actor_second_pass_v2.jsonl` contiene **266 filas**:
25 del canario `seed=42` y 241 de producción. No debe interpretarse como un
canario de 25 filas. Su hash y conteos vigentes están en
`actor_second_pass_v2.canonical_266.run_manifest.json`.

Las vistas auditables separadas son:

- `actor_second_pass_v2.canario_25_seed42.jsonl` (25 filas; hash congelado del
  canario) y `run_manifest_canario_25_seed42_v2.json` (manifiesto corregido).
- `actor_second_pass_v2.produccion_241.jsonl` (241 filas derivadas del
  canónico actual) y el manifiesto histórico
  `actor_second_pass_v2.run_manifest.json` (describe la corrida API original,
  no el postprocesamiento posterior).

La sanitización retroactiva de 71 asociaciones de proyecto no llamó a la API.
El manifiesto vigente registra por separado el hash del script de generación y
el hash del script vigente usado para el postprocesamiento. Los manifiestos
históricos se conservan sin sobrescribir.

La segunda pasada **no está integrada al warehouse principal**. Sí existe un
warehouse puente nuevo (`Auditoria/integracion_v1/warehouse_v3_2_bridge.sqlite`)
con vínculos documento → caso/proyecto → actor/evento, pero las capas antiguas
de entidades/eventos aún no están reconciliadas y los vínculos ambiguos no se
adjudican automáticamente.

La validación dirigida histórica contiene **1 documento**, no 2. El archivo
correcto es `actor_second_pass_v2.validacion_dirigida_1doc.jsonl`; el antiguo
`actor_second_pass_v2.validacion_dirigida_2docs.jsonl` se preserva como
histórico superado y no debe usarse para contar documentos.

El script vigente exige fingerprint de contrato, omite URLs ya presentes y
escribe manifests y `errors.jsonl` separados en corridas reales.

Los análisis posteriores de CONFLICT e identidad de actor se ejecutaron sobre
el bridge en una pasada separada. Su hash, conteos actuales, límites y estado
de revisión están en
`Auditoria/integracion_v1/actor_identity_conflict_v1.run_manifest.json`;
no deben confundirse con el manifiesto histórico de generación API de esta
segunda pasada.
