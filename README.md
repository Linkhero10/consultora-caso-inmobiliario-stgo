# Conflictividad inmobiliaria en Santiago

Punto de entrada: [START HERE](START_HERE.md).

Proyecto de portafolio de la consultora formada por Felipe Muñoz, Darío Briceño, Nicolás Gajardo y
Christian Nass, construido sobre fuentes de acceso público. Ver [DATA_NOTICE.md](DATA_NOTICE.md)
sobre el estatus de redistribución de los datos de terceros y [LICENSE](LICENSE) sobre el código y
los datos derivados.

## Qué es

Análisis de conflictividad inmobiliaria y urbana en las 32 comunas de la Provincia de Santiago,
2014-2026. Cubre DS19 (Programa de Integración Social y Territorial, MINVU) y también
densidad/altura, patrimonio, especulación y legalidad administrativa. El corpus se construyó por
scraping de prensa, actas municipales y fuentes DS19, con clasificación y extracción asistidas por
LLM, validación humana muestral, auditorías dirigidas y controles de calidad reproducibles.

## Estado de la release

<!-- stats:begin -->
| Dato | Valor |
|---|---|
| Versión de la release | 1.0.0 |
| SHA-256 de `data/warehouse.sqlite` | `a319833de55f1f7af1dcae9b9b9039417ca8586389709e1166a5573b44f044e7` |
| Integridad | `integrity_check=ok`, 0 violaciones de FK |
| Documentos del corpus | 3.884 (934 con extracción estructurada) |
| Proyectos · casos · conflictos | 942 · 835 · 817 |
| Cola de identidad de proyectos | 258 pares: 119 fusionados, 139 separados, 0 abiertos |
| Conflictos con respaldo de evidencia | 506 de 817 (311 sin respaldo detectado) |
| Menciones de proyecto sin vínculo a una `case_mention` | 201 |
| Referencias históricas preservadas | 31 (5 confirmadas como no resolubles) |
<!-- stats:end -->

“Sin respaldo detectado” no significa “conflicto falso”. Cita siempre el hash del warehouse y los límites
descritos en [Estándares](docs/standards.md#límites-conocidos-de-esta-release).

## Cómo correrlo

```bash
git clone <url>
git lfs pull
python -m venv .venv && source .venv/bin/activate  # .venv\Scripts\activate en Windows
pip install -e .[dev]
pytest
```

Este repositorio usa [Git LFS](https://git-lfs.com/) para `data/warehouse.sqlite`: instalarlo antes de
clonar (`git lfs install`) para no recibir solo el puntero del archivo.

## Estructura

```text
src/            pipeline: discovery -> classify -> enrich -> projects -> conflicts -> actors -> geography
config/         contratos de extracción y decisiones humanas versionadas (llaveadas por ID, con evidencia)
tests/          pruebas automatizadas, CI en cada push (.github/workflows/tests.yml)
data/           warehouse.sqlite (base de datos de referencia, vía Git LFS)
docs/           tablero publicado (docs/index.html), arquitectura, metodología y estándares
audit/          resultados: manifiesto, reportes generados, resumen de validación y calidad de datos
```

## Reconstruir

El orden de reconstrucción tiene una sola definición, `src/rebuild.py` (`python src/rebuild.py --list`).
Cada paso lee lo que dejó el anterior; el manifiesto es el último que toca `data/warehouse.sqlite`:

```bash
python src/build_enrichment_tables.py
python src/build_projects.py
python src/resolve_project_review.py
python src/detect_case_mention_duplicates.py
python src/build_conflicts.py
python src/build_actor_registry.py
python src/build_actor_network.py
python src/apply_actor_registry_to_network.py
python src/build_geography.py
python src/build_geography_manzana.py
python src/build_dashboard.py
python src/generate_run_manifest.py
python src/render_docs_stats.py
pytest -q
```

En la práctica: `python src/rebuild.py`. Las etapas de clasificación y extracción por LLM
(`src/classify.py`, `src/enrich.py`) y el corpus de terceros no se versionan y no forman parte de la
reconstrucción. Sin ellos, las salidas que producen se recuperan del warehouse publicado:

```bash
python src/extract_stage_warehouse.py --stage enrichment
python src/rebuild.py
```

Al publicar una reconstrucción, completar el manifiesto en un commit de seguimiento con
`python src/generate_run_manifest.py --release-commit <SHA>`; el manifiesto conserva además el hash del
warehouse como verificación fuerte.

Ver [`docs/architecture.md`](docs/architecture.md), [`docs/methodology.md`](docs/methodology.md) y los
[estándares de construcción](docs/standards.md) (qué hacer desde el primer día en un proyecto nuevo o al
ampliar este).

## Base de datos

`data/warehouse.sqlite` (SQLite, vía Git LFS) contiene identidad resuelta de proyecto, caso y conflicto, la
red actor↔conflicto y el registro de identidad de actores institucionales. Vista principal para construir la
red: `actor_event_project_link_conflict_safe`.

## Arcos de trabajo

1. **Arco 0 (Felipe)** — scraping, clasificación y extracción del corpus base.
2. **Arco Darío** — red de actores, SNA/ERGM.
3. **Arco Nicolás** — institucionalidad y regulación (DS19, normativa, actas).
4. **Arco Christian** — auditoría de evidencia (marco ESG adaptado).
5. **Cierre (Felipe)** — sentimiento, tópicos, mapa, dashboard integrado.

Plan paso a paso de cada arco analítico (2-4):
[`docs/arcos/plan_arcos_analiticos.md`](docs/arcos/plan_arcos_analiticos.md).
