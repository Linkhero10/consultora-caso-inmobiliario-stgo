# Auditoría final de capturas y productos — 2026-09-13

## Alcance

Verificación local de los artefactos producidos en la expansión de contexto. No se modificaron snapshots, locks, contratos ni el pipeline de prensa.

## Confirmado

- MINVU: `4.224` filas normalizadas, 32 comunas, años 2002–2026; el primer intento produjo cero filas por dos errores de normalización (tupla/lista y años convertidos a texto), ambos corregidos y re-ejecutados.
- CASEN nacional: DTA `1.608.073.353` bytes, SAV `749.656.107`, RData `1.548.841.010`; hashes en `Auditoria/fuentes_externas/casen_national_capture_20260913.json`. Firmas revisadas; permanecen raw/aislados.
- Literatura: 12 PDFs, 12 Markdown, 0 excepciones en la ingesta custom; el manifiesto FARO reporta 5 documentos con revisión OCR/estructura visual pendiente y 1 advertencia PDF seria de estructura, no un error de lectura global.
- SQLite: 32 Censo, 345 ARClim, 2 GTFS, 4.224 MINVU, 10 CMN, 783 prensa, 12 literatura, 164 aristas y 233 nodos. Las vistas `v_context` (32) y `v_conflict_counts` (58) responden.
- Dashboard: HTML contiene 4.224 filas MINVU, 32 comunas, 783 registros de prensa y 32 geometrías; `node --check` y smoke test SQL pasan. Inspección visual manual en navegador sigue pendiente por bloqueo de `file://`.

## Límites abiertos

- CASEN nacional no se analiza ni se integra sin definir estimando, ponderadores, licencia/PII, variables y presupuesto de cómputo.
- Literatura con páginas vacías/advertencias debe revisarse visualmente antes de usar citas sensibles.
- La prensa continúa provisional: requiere snapshot v3, reconciliación de lineage y gates de clasificación/enrichment.
- El mapa es contextual por comuna; no geocodifica proyectos ni demuestra causalidad.
- No se llamó a GPT-5.6 Sol: sigue bloqueado hasta autorización explícita de Felipe.
