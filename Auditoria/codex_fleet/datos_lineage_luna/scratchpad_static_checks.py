"""Checks read-only for the data-lineage audit.

This file intentionally has no network calls, subprocesses, or writes outside
its own stdout. Run with the FARO runtime from any directory.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\Felipe\Consultora\caso_inmobiliario_stgo")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


snapshot = ROOT / "Fuentes/discovery_snapshots/discovery_snapshot_20260912_153729_835.jsonl"
meta = json.loads(snapshot.with_suffix(".meta.json").read_text(encoding="utf-8"))
snapshot_rows = rows(snapshot)
fulltext = rows(ROOT / "Fuentes/fulltext_v2/fulltext_manifest_v2.jsonl")

actual_snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
assert actual_snapshot_hash == meta["snapshot_sha256"]
assert len(snapshot_rows) == meta["lines_valid"]

missing_period = sum(not record.get("periodo") for record in snapshot_rows)
missing_level = sum(not record.get("nivel") for record in snapshot_rows)
missing_lineage_period = sum(not (record.get("lineage") or {}).get("periodo") for record in fulltext)
missing_lineage_level = sum(not (record.get("lineage") or {}).get("nivel") for record in fulltext)

for record in fulltext:
    assert (record.get("lineage") or {}).get("snapshot_sha256") == meta["snapshot_sha256"]
    assert (ROOT / record["content_file"]).exists()

print(json.dumps({
    "snapshot_rows": len(snapshot_rows),
    "snapshot_sha256": actual_snapshot_hash,
    "snapshot_missing_periodo": missing_period,
    "snapshot_missing_nivel": missing_level,
    "fulltext_rows": len(fulltext),
    "fulltext_missing_lineage_periodo": missing_lineage_period,
    "fulltext_missing_lineage_nivel": missing_lineage_level,
    "fulltext_methods": dict(Counter(record["method"] for record in fulltext)),
    "fulltext_zero_char_count": sum(record.get("char_count", 0) == 0 for record in fulltext),
}, ensure_ascii=False, indent=2))
