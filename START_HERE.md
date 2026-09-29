# START HERE — Conflictividad inmobiliaria en Santiago

Este archivo orienta la lectura del repositorio y da el estado del snapshot actual. Para el
propósito, alcance y composición del corpus, sigue con el [README](README.md).

## Estado actual (2026-09-29)

El warehouse publicado en `main` es la reconstrucción integral cerrada del 2026-09-29: 942
proyectos, 835 `case_id`, 817 conflictos, SHA-256 `9f328ad4884b26f1b49e98ab2b7c889e6438384e208b41eefd024d2598828926`,
`integrity_check=ok` y sin violaciones de FK. Cita siempre ese hash al usar los datos.

**Identidad de proyectos.** La cola revisada tiene 258 pares: 119 fusionados, 139 mantenidos sin
fusión y 0 abiertos. Recreo se fusiona con el proyecto de calle Recreo (overlay v4, confianza alta,
apoyado por SEA/MINVU). Santa Petronila y Alto Las Condes siguen como `insufficient_evidence`: no se
afirma que sean distintos y cada uno especifica qué dato permitiría reabrirlo. La normalización de
nombres ya no colapsa `Lote 18-A` con `Lote 18` (el sufijo de letra pegado por guion a un número
se conserva); ambos quedan separados como lote completo y parte.

**Huecos de datos.** 498 conflictos tienen respaldo de evidencia y 319 no (sin respaldo detectado no
significa conflicto falso). Quedan 209 menciones sin `case_mention_index` (antes 227) y 0 referencias
históricas con identidad sin resolver: «Alto Norte» es el nombre del permiso de Alto Las Condes 2. Ver el
[cierre de huecos](audit/data_gap_closure_2026-09-29.md), el
[acta de identidad](audit/project_identity_closure_2026-09-29.md) y el
[resumen de validación](audit/validation_summary.json).

**Pendientes documentados, sin bloquear la publicación:** 28 referencias históricas preservadas sin alias
(5 confirmadas como no resolubles), 196 conflictos sin respaldo que no tuvieron lectura semántica, 209
menciones sin índice, y 79 grupos con señales de riesgo de fusión automática sin adjudicar uno por uno.

## Recorrido recomendado

1. [Dashboard](docs/index.html): exploración visual del warehouse publicado.
2. [Metodología](docs/methodology.md): cómo se conectan documentos, evidencia, proyectos, casos,
   conflictos y actores; incluye las limitaciones de cada vínculo.
3. [Arquitectura](docs/architecture.md): componentes y orden de transformación.
4. [Plan de arcos analíticos](docs/arcos/plan_arcos_analiticos.md): trabajo exploratorio previsto
   para redes, institucionalidad y evidencia.
5. [Resumen de validación](audit/validation_summary.json) y [calidad de datos](audit/data_quality_report.md):
   métricas, decisiones y límites de interpretación.

“Sin respaldo detectado” no significa “conflicto falso”. Las métricas y los datos deben citarse
con el hash del warehouse y sus limitaciones, especialmente durante el desarrollo de los tres
arcos analíticos.

## Reproducir pruebas

El warehouse se distribuye mediante Git LFS. Instala Git LFS antes de clonar y descargar los
archivos; luego sigue las instrucciones de instalación y pruebas del [README](README.md). Una
reconstrucción integral sigue bloqueada por diseño si reaparece algún par de identidad PROJECT sin
resolver (hoy: 0).
