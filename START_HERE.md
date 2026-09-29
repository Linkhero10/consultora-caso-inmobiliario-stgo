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

La rama `codex/historical-case-references` contiene la **reconstrucción integral cerrada** del
2026-09-29, SHA-256 del warehouse `ef776d1f9294021751d1b74f602523eaabe6d02e18f7d6b4b68c61bfa6d1436d`:
941 proyectos, 835 `case_id` y 817 conflictos, con `integrity_check=ok` y sin violaciones de FK. La
cola de identidad PROJECT (256 pares) quedó sin pares abiertos: 118 fusionados y 138 separados. Los
8 pares que seguían abiertos se cerraron con evidencia de fuente: 3 fusiones (Chaguay/Reserva La
Dehesa exChaguay, las torres junto al Hotel Sheraton, el proyecto Bellavista de DIB), 1 separación
(Reserva La Dehesa del Cerro del Medio), 1 relación parte–todo (Costanera Center/Cenco Costanera) y
3 casos `insufficient_evidence` (Santa Petronila, Recreo, Alto Las Condes), que se mantienen
separados **sin afirmar que sean objetos distintos**; cada uno documenta la evidencia que lo
reabriría. Además se revirtieron dos fusiones legacy por nombre contradichas por las fuentes.
Quedan 29 referencias históricas sin destino preservadas sin alias forzado (5 confirmadas como no
resolubles), y 1 relación de conflicto `pending_human_decision` (Población La Victoria) que es
una decisión de la capa de relaciones, no de identidad PROJECT.
Consulta el [cierre de identidad](audit/project_identity_closure_2026-09-29.md), el
[overlay v3](audit/project_identity_adjudication_overrides_2026-09-28_v3.json) y el
[checkpoint previo](audit/project_identity_resolution_checkpoint_2026-09-28.md). La
[acta histórica del 27-09](audit/historical_case_identity_closure_2026-09-27.json) se conserva sin
reescritura.

“Sin respaldo detectado” no significa “conflicto falso”. Las métricas y los datos deben citarse
con el hash del warehouse y sus limitaciones, especialmente durante el desarrollo de los tres
arcos analíticos.

## Reproducir pruebas

El warehouse se distribuye mediante Git LFS. Instala Git LFS antes de clonar y descargar los
archivos; luego sigue las instrucciones de instalación y pruebas del [README](README.md). Una
reconstrucción integral sigue bloqueada por diseño si reaparece algún par de identidad PROJECT sin
resolver (hoy: 0).
