"""El contrato persistido v3.2 debe poder regenerarse byte a byte."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from build_enrichment_record_schema import (  # noqa: E402
    RECORD_SCHEMA_PATH,
    build_record_schema,
)


def test_record_schema_v3_2_matches_regenerated_version():
    committed = json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert committed == build_record_schema()
