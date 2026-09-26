# Conflictividad inmobiliaria en Santiago

Proyecto de portafolio de la consultora formada por Felipe Muñoz, Darío Briceño, Nicolás Gajardo y
Christian Nass, construido sobre fuentes de acceso público. Ver [DATA_NOTICE.md](DATA_NOTICE.md)
sobre el estatus de redistribución de los datos de terceros y [LICENSE](LICENSE) sobre el código y
los datos derivados.

## Qué es

Análisis de conflictividad inmobiliaria y urbana en las 32 comunas de la Provincia de Santiago,
2014-2026. Cubre DS19 (Programa de Integración Social y Territorial, MINVU) y también
densidad/altura, patrimonio, especulación y legalidad administrativa. El corpus se construyó por
scraping de prensa, actas municipales y fuentes DS19, con clasificación y enriquecimiento asistidos
por LLM, validación humana muestral, auditorías dirigidas y gates de calidad reproducibles.

## Cómo correrlo

```bash
git clone <url>
git lfs pull
python -m venv .venv && source .venv/bin/activate  # .venv\Scripts\activate en Windows
pip install -e .[dev]
pytest
```

Este repositorio usa [Git LFS](https://git-lfs.com/) para `data/warehouse.sqlite` — instalarlo
antes de clonar (`git lfs install`) para no recibir solo el puntero del archivo.

## Estructura

```text
src/            pipeline: discovery -> classify -> enrich -> projects -> conflicts -> actors -> network
config/         schemas y prompts vigentes
tests/          tests automatizados, CI en cada push (ver .github/workflows/tests.yml)
data/           warehouse.sqlite (base de datos de referencia, via Git LFS)
docs/           dashboard único publicado en GitHub Pages (docs/index.html) + arquitectura/metodología en Markdown
audit/          resumen de validación y calidad de datos
```

Orden completo de reconstrucción (cada paso lee lo que dejó el anterior; `generate_run_manifest.py`
siempre debe ser el último que toca `data/warehouse.sqlite`):

```bash
python src/build_enrichment_tables.py   # enrichment_document/enrichment_project_mention desde v3.3
python src/build_projects.py            # identidad de proyecto/caso
python src/resolve_project_review.py    # fusiona pares revisados de la cola
python src/build_conflicts.py           # capa CONFLICT
python src/build_actor_registry.py      # identidad de actor institucional
python src/build_actor_network.py
python src/apply_actor_registry_to_network.py
python src/build_geography.py           # comuna resuelta + project_mention_geography (Fix 1F)
python src/build_geography_manzana.py   # contexto censal (manzana)
python src/build_dashboard.py           # docs/index.html
python src/generate_run_manifest.py     # regenerar manifiesto tras el warehouse
pytest -q
```

Al publicar una reconstrucción, después del commit que primero incluye el
warehouse y el reporte generado, completar el manifiesto en un commit de
seguimiento: `python src/generate_run_manifest.py --release-commit <SHA-del-commit-de-publicacion>`.
El SHA completo debe existir en el repositorio; el manifiesto conserva además
el hash del warehouse como verificación fuerte.

`src/classify.py` y `src/enrich.py` (o su sucesor `src/_enrich_pipeline_v3_3_*.py`) son pasos
aparte, de costo LLM real — no se re-corren en cada reconstrucción del warehouse. Ver
[`docs/architecture.md`](docs/architecture.md) para el diagrama completo y
[`docs/methodology.md`](docs/methodology.md) para los criterios de cada capa, el gate documental y
qué queda deliberadamente sin resolver.

## Base de datos

`data/warehouse.sqlite` (SQLite, vía Git LFS) contiene identidad resuelta de proyecto, caso y
conflicto, la red actor↔conflicto, y el registro de identidad de actores institucionales. Vista
principal para construir la red: `actor_event_project_link_conflict_safe`.

## Arcos de trabajo

1. **Arco 0 (Felipe)** — scraping, clasificación y enriquecimiento del corpus base.
2. **Arco Darío** — red de actores, SNA/ERGM.
3. **Arco Nicolás** — institucionalidad y regulación (DS19, normativa, actas).
4. **Arco Christian** — auditoría de evidencia (marco ESG adaptado).
5. **Cierre (Felipe)** — sentimiento, tópicos, mapa, dashboard integrado.

Plan paso a paso de cada arco analítico (2-4):
[`docs/arcos/plan_arcos_analiticos.md`](docs/arcos/plan_arcos_analiticos.md).

## Estado

El corpus base y la capa de identidad (proyecto → caso → conflicto → actor institucional) están
construidos y verificados. La validación muestral del enrichment (n=50: 21 ok, 17 error menor, 12
error grave — ver [`audit/validation_summary.json`](audit/validation_summary.json)) identificó
errores reales de unidad de caso que motivaron el gate documental descrito en la metodología. Las
conclusiones analíticas de fondo siguen pendientes de que arranquen los arcos sustantivos
(Darío/Nicolás/Christian).
