"""Rutas de archivos intermedios del pipeline.

Los archivos intermedios (clasificacion, extraccion por LLM, warehouses de etapa) son grandes
y se derivan del corpus de terceros, asi que no se versionan. Viven en un directorio
configurable: `PIPELINE_INTERMEDIATE_DIR` o, por defecto, `intermediate/` en la raiz del
repositorio. Solo `data/warehouse.sqlite` (producto publicado) y `config/` (decisiones humanas)
son la fuente de verdad versionada.

Estructura esperada:

    intermediate/
      classification/     salida de classify.py (classifications.jsonl)
      enrichment/         una carpeta por corrida de enrich.py (enrichment.jsonl)
      integration/        warehouses de etapa (base_warehouse.sqlite, warehouse_enrichment.sqlite)
      review_samples/     muestras de control de la clasificacion
      external_sources/   manifiestos de descarga de fuentes externas
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTERMEDIATE_DIR = Path(os.environ.get("PIPELINE_INTERMEDIATE_DIR") or PROJECT_ROOT / "intermediate")

CLASSIFICATION_DIR = INTERMEDIATE_DIR / "classification"
CLASSIFICATIONS_PATH = CLASSIFICATION_DIR / "classifications.jsonl"

ENRICHMENT_DIR = INTERMEDIATE_DIR / "enrichment"
INTEGRATION_DIR = INTERMEDIATE_DIR / "integration"
BASE_WAREHOUSE_PATH = INTEGRATION_DIR / "base_warehouse.sqlite"
ENRICHMENT_WAREHOUSE_PATH = INTEGRATION_DIR / "warehouse_enrichment.sqlite"

REVIEW_SAMPLES_DIR = INTERMEDIATE_DIR / "review_samples"
EXTERNAL_SOURCES_DIR = INTERMEDIATE_DIR / "external_sources"

# Estado de ejecucion (locks, run_state): local, nunca versionado.
RUN_STATE_DIR = PROJECT_ROOT / ".pipeline_state"
