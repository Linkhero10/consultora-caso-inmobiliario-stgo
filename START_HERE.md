# START HERE — Conflictividad inmobiliaria en Santiago

Este archivo orienta la lectura del repositorio y da el estado del snapshot actual. Para el
propósito, alcance y composición del corpus, sigue con el [README](README.md).

## Recorrido recomendado

1. [Dashboard](docs/index.html): exploración visual del warehouse publicado.
2. [Metodología](docs/methodology.md): cómo se conectan documentos, evidencia, proyectos, casos,
   conflictos y actores; incluye las limitaciones de cada vínculo.
3. [Arquitectura](docs/architecture.md): componentes y orden de transformación.
4. [Plan de arcos analíticos](docs/arcos/plan_arcos_analiticos.md): trabajo exploratorio previsto
   para redes, institucionalidad y evidencia.
5. [Resumen de validación](audit/validation_summary.json) y [calidad de datos](audit/data_quality_report.md):
   métricas, decisiones y límites de interpretación.

## Estado — 2026-09-28

El snapshot publicado en `main` sigue siendo `data/warehouse.sqlite`, SHA-256
`378bf7d7686d676dfb1e08cb5c141a2e5bea29b943ad0de6ef4f58d0900c09db`: 941 proyectos, 850
`case_id` y 833 conflictos. No representa una reconstrucción posterior a las adjudicaciones de
identidad recientes.

La rama de trabajo `codex/historical-case-references` contiene otro snapshot versionado para la
simulación, SHA-256 `685af6a951356c0c7e7249525fcb89362f8801a4c259f614571d775fb329c33c`: 941
proyectos, 837 `case_id` y 819 filas de conflicto preexistentes. Se simuló en memoria la aplicación
del resolver y del preflight; **no** se reconstruyó CONFLICT, el dashboard ni el manifiesto y no se
promovió ese resultado a `main`.

La simulación resolvió los 52 pares inicialmente abiertos en 37 separaciones y 7 fusiones; 8 siguen
sin decisión. También reabrió 2 adjudicaciones previas cuya evidencia no sostiene aún una identidad
inequívoca. Por ello quedan **10 pares PROJECT bloqueantes** para una reconstrucción/publicación
integral. Las 29 referencias históricas sin destino se preservan sin alias forzado; 5 están
documentadas como no resolubles y ninguna bloquea por sí sola la topología en el preflight simulado.
Consulta el [checkpoint de reconciliación](audit/project_identity_resolution_checkpoint_2026-09-28.md)
y su [reporte reproducible](audit/project_identity_resolution_simulation_2026-09-28.json). La
[acta histórica del 27-09](audit/historical_case_identity_closure_2026-09-27.json) se conserva sin
reescritura.

“Sin respaldo detectado” no significa “conflicto falso”. Las métricas y los datos deben citarse
con el hash del warehouse y sus limitaciones, especialmente durante el desarrollo de los tres
arcos analíticos.

## Reproducir pruebas

El warehouse se distribuye mediante Git LFS. Instala Git LFS antes de clonar y descargar los
archivos; luego sigue las instrucciones de instalación y pruebas del [README](README.md). Una
reconstrucción integral permanece bloqueada por diseño mientras sigan sin resolución los 10 pares
de identidad PROJECT.
