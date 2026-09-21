# Conflictividad inmobiliaria en Santiago

Proyecto de portafolio de la consultora formada por Felipe Muñoz, Darío Briceño,
Nicolás Gajardo y Christian Nass, construido sobre fuentes de acceso público.
Ver [DATA_NOTICE.md](DATA_NOTICE.md) sobre el estatus de redistribución de los
datos de terceros y [LICENSE](LICENSE) sobre el código y los datos derivados.

## Qué es

Análisis de conflictividad inmobiliaria y urbana en las 32 comunas de la Provincia
de Santiago, 2014-2026. Cubre DS19 (Programa de Integración Social y Territorial,
MINVU) y también densidad/altura, patrimonio, especulación y legalidad
administrativa. El corpus se construyó por scraping de prensa, actas municipales y
fuentes DS19, con clasificación y enriquecimiento asistidos por LLM, validación
humana muestral, auditorías dirigidas y gates de calidad reproducibles.

Objetivo del piloto: producir un conjunto de análisis públicos (LinkedIn y
similares) que demuestren, en un tema nuevo, las capacidades técnicas del equipo.

## Estructura

- `Fuentes/` — datos crudos scrapeados (prensa, actas municipales, DS19) y fuentes
  externas de referencia.
- `Trabajo/` — scripts, prompts, configuración y contratos del pipeline.
- `Auditoria/` — clasificaciones, enriquecimiento, validaciones humanas y
  matrices de evidencia.
- `Productos/` — dashboards, informes y entregables.
- `docs/` — arquitectura del pipeline ([`docs/architecture.md`](docs/architecture.md)) y planes de
  arcos analíticos.

Ver [START_HERE.md](START_HERE.md) para la genealogía técnica completa del pipeline (qué script
genera qué tabla, en qué orden).

## Base de datos

La base de referencia para análisis es
[`Auditoria/integracion_v1/warehouse_v3_2_bridge.sqlite`](Auditoria/integracion_v1/warehouse_v3_2_bridge.sqlite)
(SQLite, versionado con Git LFS). Contiene identidad resuelta de proyecto, caso y
conflicto, la red actor↔conflicto, y el registro de identidad de actores
institucionales. Ver
[`Auditoria/integracion_v1/entrega_dario_2026-09-18/ENTREGA_DARIO_red_actor_conflict.md`](Auditoria/integracion_v1/entrega_dario_2026-09-18/ENTREGA_DARIO_red_actor_conflict.md)
para la guía de uso: qué tablas/vistas usar, qué queda deliberadamente sin
resolver, y qué preguntas de análisis quedan abiertas.

## Arcos de trabajo

1. **Arco 0 (Felipe)** — scraping, clasificación y enriquecimiento del corpus base.
2. **Arco Darío** — red de actores, SNA/ERGM.
3. **Arco Nicolás** — institucionalidad y regulación (DS19, normativa, actas).
4. **Arco Christian** — auditoría de evidencia (marco ESG adaptado).
5. **Cierre (Felipe)** — sentimiento, tópicos, mapa, dashboard integrado.

Plan paso a paso de cada arco analítico (2-4):
[`docs/arcos/plan_arcos_analiticos.md`](docs/arcos/plan_arcos_analiticos.md).

## Estado

El corpus base y la capa de identidad (proyecto → caso → conflicto → actor
institucional) están construidos y verificados. La validación muestral del
enrichment (n=50: 21 ok, 17 error menor, 12 error grave) identificó errores
reales de unidad de caso —documentos que mezclaban más de un conflicto bajo
un mismo registro— y eso fue lo que motivó construir la capa posterior de
gate y resolución PROJECT → CASE → CONFLICT descrita en
[`docs/architecture.md`](docs/architecture.md). Las conclusiones analíticas
de fondo siguen pendientes de que arranquen los arcos sustantivos
(Darío/Nicolás/Christian).

## Notas de lectura

- [`docs/versions.md`](docs/versions.md) — qué versión de cada componente (clasificación,
  enriquecimiento, warehouse) es la vigente.
- [`docs/glossary.md`](docs/glossary.md) — qué significan los nombres propios que aparecen en
  comentarios de código y en `Auditoria/`.

## Correr el proyecto localmente

```bash
git clone <url>
git lfs pull
python -m venv .venv && source .venv/bin/activate  # .venv\Scripts\activate en Windows
pip install -e .[dev]
pytest
```

Este repositorio usa [Git LFS](https://git-lfs.com/) para el archivo `.sqlite` — instalarlo antes
de clonar (`git lfs install`) para no recibir solo el puntero del archivo. Algunos tests dependen
del warehouse y se saltan automáticamente si no está disponible.
