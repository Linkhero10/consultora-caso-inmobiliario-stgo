#!/usr/bin/env python3
"""Build the blinded Fix 1A conflict holdout package.

The package deliberately omits every field produced by the backing detector.
The calibration IDs are an explicit input: when they are unavailable the
script still builds a reproducible *candidate*, but marks independence as
unverified and refuses to call it external validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
OUTPUT_DIR = PROJECT_ROOT / "audit" / "holdout_1a"
DEFAULT_CALIBRATION_IDS = OUTPUT_DIR / "calibration_conflict_ids.txt"
DEFAULT_SEED = "fix1a-holdout-20260922"
MAIN_N = 100
STRESS_N = 50

DETECTOR_FIELDS = frozenset(
    {
        "respaldo_evidencia",
        "n_projects_backed",
        "n_projects_unbacked",
        "coverage_backing",
        "label_source_project_id",
        "n_documents_ambiguous_backing",
        "detector_version",
        "match_method",
        "backing_scope",
        "backing_rows",
        "backing_rows_detected_raw",
        "backing_rows_persisted",
        "ambiguous_multi_case_document",
    }
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_key(seed: str, conflict_id: str) -> str:
    return hashlib.sha256(f"{seed}|{conflict_id}".encode("utf-8")).hexdigest()


def _read_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _display_path(path: Path) -> str:
    """Use a project-relative path when possible, absolute otherwise (tests)."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _rows_for_ids(conn: sqlite3.Connection, conflict_ids: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for conflict_id in conflict_ids:
        conflict = conn.execute(
            "SELECT conflict_id, label, n_case_ids, origen FROM conflict WHERE conflict_id = ?",
            (conflict_id,),
        ).fetchone()
        if conflict is None:
            raise ValueError(f"conflict_id no existe en el warehouse: {conflict_id}")
        case_ids = [r[0] for r in conn.execute(
            "SELECT case_id FROM conflict_case WHERE conflict_id = ? ORDER BY case_id",
            (conflict_id,),
        )]
        projects = [dict(r) for r in conn.execute(
            "SELECT cp.project_id, p.canonical_name, cp.case_id "
            "FROM conflict_project cp JOIN project p ON p.project_id = cp.project_id "
            "WHERE cp.conflict_id = ? ORDER BY p.canonical_name, cp.project_id",
            (conflict_id,),
        )]
        documents: list[dict[str, Any]] = []
        for doc_row in conn.execute(
            "SELECT dc.document_id, dc.role, dc.source, dc.unidad_caso_tipo, "
            "d.url, d.title, d.fecha_publicacion "
            "FROM document_conflict dc JOIN document d ON d.document_id = dc.document_id "
            "WHERE dc.conflict_id = ? ORDER BY dc.document_id",
            (conflict_id,),
        ):
            doc = dict(doc_row)
            doc["case_mentions"] = [dict(r) for r in conn.execute(
                "SELECT case_mention_id, mention_index, comuna, codigo_comuna_ine, tipo_objeto_norm "
                "FROM case_mention WHERE document_id = ? ORDER BY mention_index",
                (doc["document_id"],),
            )]
            doc["evidence"] = [dict(r) for r in conn.execute(
                "SELECT evidence_id, case_mention_id, quote_role, quote_index, quote_text "
                "FROM evidence WHERE document_id = ? ORDER BY case_mention_id, quote_role, quote_index",
                (doc["document_id"],),
            )]
            documents.append(doc)
        rows.append(
            {
                "conflict_id": conflict["conflict_id"],
                "label": conflict["label"],
                "n_case_ids": conflict["n_case_ids"],
                "origen": conflict["origen"],
                "case_ids": case_ids,
                "projects": projects,
                "documents": documents,
            }
        )
    return rows


def _assert_blind(records: list[dict[str, Any]]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            leaked = DETECTOR_FIELDS.intersection(value)
            if leaked:
                raise AssertionError(f"campos del detector filtrados: {sorted(leaked)}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(records)


def build_package(
    *,
    warehouse: Path = WAREHOUSE,
    output_dir: Path = OUTPUT_DIR,
    calibration_ids_path: Path = DEFAULT_CALIBRATION_IDS,
    seed: str = DEFAULT_SEED,
    main_n: int = MAIN_N,
    stress_n: int = STRESS_N,
) -> dict[str, Any]:
    if not warehouse.exists():
        raise FileNotFoundError(warehouse)
    calibration_ids = _read_ids(calibration_ids_path)
    con = sqlite3.connect(warehouse)
    con.row_factory = sqlite3.Row
    all_ids = [r[0] for r in con.execute("SELECT conflict_id FROM conflict ORDER BY conflict_id")]
    all_id_set = set(all_ids)
    unknown_calibration = sorted(calibration_ids - all_id_set)
    calibration_count = len(calibration_ids)
    if unknown_calibration:
        raise ValueError(f"IDs de calibración ausentes del warehouse: {unknown_calibration[:5]}")
    if calibration_count and calibration_count != 150:
        raise ValueError(f"La lista de calibración debe tener 150 IDs; tiene {calibration_count}")
    eligible_ids = [cid for cid in all_ids if cid not in calibration_ids]
    ordered = sorted(eligible_ids, key=lambda cid: _stable_key(seed, cid))
    main_ids = ordered[:main_n]
    no_backing = {
        r[0] for r in con.execute(
            "SELECT conflict_id FROM conflict WHERE respaldo_evidencia = 'sin_respaldo_exact_quote_detectado'"
        )
    }
    stress_pool = [cid for cid in ordered if cid not in set(main_ids) and cid in no_backing]
    stress_ids = stress_pool[:stress_n]
    if len(main_ids) != main_n or len(stress_ids) != stress_n:
        raise ValueError(f"No se pudo seleccionar {main_n}+{stress_n}: {len(main_ids)}+{len(stress_ids)}")
    main_records = _rows_for_ids(con, main_ids)
    stress_records = _rows_for_ids(con, stress_ids)
    con.close()
    _assert_blind(main_records + stress_records)
    output_dir.mkdir(parents=True, exist_ok=True)
    main_path = output_dir / "holdout_main_n100.json"
    # Neutral filename: the reviewer must not learn which detector side was
    # used to choose the directed stress sample.
    stress_path = output_dir / "stress_sample_n50.json"
    main_path.write_text(json.dumps(main_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stress_path.write_text(json.dumps(stress_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    independence_verified = calibration_count == 150
    manifest = {
        "artifact_version": "fix1a-holdout-v1",
        "status": "ready_for_external_review" if independence_verified else "candidate_independence_unverified",
        "blind": True,
        "model_labels_used": False,
        "detector_fields_excluded": sorted(DETECTOR_FIELDS),
        "warehouse_sha256": _sha256_file(warehouse),
        "warehouse_conflicts_total": len(all_ids),
        "selection_seed": seed,
        "main": {
            "n": len(main_records),
            "method": "simple_random_sample_without_replacement_after_calibration_exclusion",
            "ids_sha256": hashlib.sha256("\n".join(main_ids).encode()).hexdigest(),
            "path": _display_path(main_path),
        },
        "stress": {
            "n": len(stress_records),
            "method": "directed_stress_sample; reported_separately",
            "ids_sha256": hashlib.sha256("\n".join(stress_ids).encode()).hexdigest(),
            "path": _display_path(stress_path),
        },
        "calibration_exclusion": {
            "path": _display_path(calibration_ids_path),
            "ids_present": calibration_count,
            "required": 150,
            "independence_verified": independence_verified,
            "note": "Sin los 150 IDs durables, el paquete es candidato reproducible pero no puede presentarse como validacion externa.",
        },
        "generated_without_api": True,
    }
    (output_dir / "holdout_1a_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration-ids", type=Path, default=DEFAULT_CALIBRATION_IDS)
    args = parser.parse_args()
    print(json.dumps(build_package(calibration_ids_path=args.calibration_ids), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
