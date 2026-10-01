# START HERE — Conflictividad inmobiliaria en Santiago

Este archivo orienta la lectura del repositorio y da el estado del producto. Para el propósito, alcance y
composición del corpus, sigue con el [README](README.md).

## Estado

<!-- stats:begin -->
| Dato | Valor |
|---|---|
| Versión de la release | 1.0.0 |
| SHA-256 de `data/warehouse.sqlite` | `9c1a5939004815cd6495efecec414ed71a8d6edbe47fb5ef3dd106c97d0742a7` |
| Integridad | `integrity_check=ok`, 0 violaciones de FK |
| Documentos del corpus | 3.884 (934 con extracción estructurada) |
| Proyectos · casos · conflictos | 942 · 835 · 817 |
| Cola de identidad de proyectos | 258 pares: 119 fusionados, 139 separados, 0 abiertos |
| Conflictos con respaldo de evidencia | 506 de 817 (311 sin respaldo detectado) |
| Conflictos con respaldo Y alcance aprobado (universo conservador) | 327 |
| Menciones de proyecto sin vínculo a una `case_mention` | 201 |
| Referencias históricas preservadas | 31 (5 confirmadas como no resolubles) |
<!-- stats:end -->

Cita siempre el hash del warehouse al usar los datos. Las cifras de arriba se generan desde el warehouse
(`python src/render_docs_stats.py`); no se escriben a mano.

**Identidad de proyectos.** Cada pareja de proyectos revisada tiene una decisión con su evidencia en
`config/project_identity_decisions.json`, llaveada por la pareja exacta de `project_id`. Dos parejas quedan como
`insufficient_evidence`: no se afirma que sean iguales ni distintas, y cada una dice qué dato la reabriría.

**Respaldo de evidencia.** Un conflicto está respaldado cuando alguna mención de sus proyectos apunta, por el
índice que el modelo eligió y el pipeline verificó, a una mención incluida con cita literal del objeto.
“Sin respaldo detectado” no significa “conflicto falso”.

**Calidad medida (validación ciega de extremo a extremo).** En una muestra aleatoria de 56 conflictos verificables, el 44 % de los
que tienen respaldo de evidencia y el 100 % de los que no lo tienen fueron error grave para un revisor independiente y estricto.
Una segunda muestra independiente lo confirmó (43 %). Por eso la construcción incluye un filtro de alcance (Jev): la vista `conflict_conservative` reúne los conflictos con respaldo Y alcance aprobado, y una tercera validación ciega midió 26 % de error grave en ese universo (IC 95 % 16–40 %). Usa `conflict_conservative` y trátalo como candidato a revisión, no como verdad (`audit/blind_validation_report_third.json`, `audit/scope_filter_report.json`). Detalle y límites en
[`audit/blind_validation_report.json`](audit/blind_validation_report.json) y en el
[informe de calidad de datos](audit/data_quality_report.md).

**Pendientes documentados, sin bloquear la publicación:** referencias históricas preservadas sin alias, menciones
sin vínculo a una `case_mention`, grupos de menciones duplicadas con señales de riesgo sin adjudicar uno por uno, y
los límites de la validación ciega de extremo a extremo. Ver
[límites conocidos](docs/standards.md#límites-conocidos-de-esta-release).

## Recorrido recomendado

1. [Dashboard](docs/index.html): exploración visual del warehouse publicado.
2. [Metodología](docs/methodology.md): cómo se conectan documentos, evidencia, proyectos, casos, conflictos y
   actores; incluye las limitaciones de cada vínculo.
3. [Arquitectura](docs/architecture.md): componentes, orden de transformación y niveles de reproducibilidad.
4. [Estándares de construcción](docs/standards.md) y [paso a paso de principio a fin](docs/playbook.md): qué falló en el camino y cómo hacerlo bien desde el primer día.
5. [Plan de arcos analíticos](docs/arcos/plan_arcos_analiticos.md): trabajo previsto para redes,
   institucionalidad y evidencia.
6. [Resumen de validación](audit/validation_summary.json) y [calidad de datos](audit/data_quality_report.md).

## Reproducir pruebas

El warehouse se distribuye mediante Git LFS. Instala Git LFS antes de clonar; luego sigue las instrucciones del
[README](README.md). Una reconstrucción integral sigue bloqueada por diseño si reaparece algún par de identidad de
proyecto sin resolver.
