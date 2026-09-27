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

## Estado del snapshot — 2026-09-27

El warehouse versionado en `data/warehouse.sqlite` tiene SHA-256
`378bf7d7686d676dfb1e08cb5c141a2e5bea29b943ad0de6ef4f58d0900c09db`: 941 proyectos, 850
`case_id`, 833 conflictos y 15.245 vínculos actor→proyecto. Es un snapshot existente; no es una
nueva reconstrucción de CONFLICT posterior a la reconciliación histórica.

El preflight detecta 48 referencias históricas ausentes: 15 pueden cambiar la topología de los
conflictos y mantienen bloqueada una reconstrucción/publicación integral; 33 referencias no
topológicas se conservarán sin forzar aliases. El dashboard existente sigue describiendo el
snapshot publicado; sus generadores y el manifiesto se bloquean hasta que un build de CONFLICT
termine con los insumos y la topología verificados. Consulta el
[acta de reconciliación](audit/historical_case_identity_closure_2026-09-27.json).

“Sin respaldo detectado” no significa “conflicto falso”. Las métricas y los datos deben citarse
con el hash del warehouse y sus limitaciones, especialmente durante el desarrollo de los tres
arcos analíticos.

## Reproducir pruebas

El warehouse se distribuye mediante Git LFS. Instala Git LFS antes de clonar y descargar los
archivos; luego sigue las instrucciones de instalación y pruebas del [README](README.md). Una
reconstrucción integral permanece bloqueada por diseño mientras sigan sin resolución los 15 IDs
topológicos.
