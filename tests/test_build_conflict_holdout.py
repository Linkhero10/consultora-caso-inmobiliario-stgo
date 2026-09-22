import json
import sqlite3
from pathlib import Path

from src.build_conflict_holdout import DETECTOR_FIELDS, _assert_blind, build_package


def _fixture_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE conflict(conflict_id TEXT PRIMARY KEY, label TEXT, n_case_ids INTEGER, origen TEXT, respaldo_evidencia TEXT);
        CREATE TABLE conflict_case(conflict_id TEXT, case_id TEXT);
        CREATE TABLE conflict_project(conflict_id TEXT, project_id TEXT, case_id TEXT);
        CREATE TABLE project(project_id TEXT PRIMARY KEY, canonical_name TEXT);
        CREATE TABLE document_conflict(document_id TEXT, conflict_id TEXT, role TEXT, source TEXT, unidad_caso_tipo TEXT);
        CREATE TABLE document(document_id TEXT PRIMARY KEY, url TEXT, title TEXT, fecha_publicacion TEXT);
        CREATE TABLE case_mention(case_mention_id TEXT, document_id TEXT, mention_index INTEGER, comuna TEXT, codigo_comuna_ine TEXT, tipo_objeto_norm TEXT);
        CREATE TABLE evidence(evidence_id TEXT, document_id TEXT, case_mention_id TEXT, quote_role TEXT, quote_index INTEGER, quote_text TEXT);
        """
    )
    for i in range(160):
        cid = f"conflict:{i:024x}"
        backing = "sin_respaldo_exact_quote_detectado" if i >= 80 else "respaldo_exact_quote_detectado"
        con.execute("INSERT INTO conflict VALUES (?,?,?,?,?)", (cid, f"Proyecto {i}", 1, "test", backing))
        con.execute("INSERT INTO conflict_case VALUES (?,?)", (cid, f"case:{i}"))
        con.execute("INSERT INTO project VALUES (?,?)", (f"project:{i}", f"Proyecto {i}"))
        con.execute("INSERT INTO conflict_project VALUES (?,?,?)", (cid, f"project:{i}", f"case:{i}"))
        con.execute("INSERT INTO document VALUES (?,?,?,?)", (f"doc:{i}", f"https://example.test/{i}", f"Doc {i}", "2026-01-01"))
        con.execute("INSERT INTO document_conflict VALUES (?,?,?,?,?)", (f"doc:{i}", cid, "focal", "test", "caso_unico"))
        con.execute("INSERT INTO case_mention VALUES (?,?,?,?,?,?)", (f"cm:{i}", f"doc:{i}", 0, "Santiago", "13101", "residencial"))
        con.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?)", (f"ev:{i}", f"doc:{i}", f"cm:{i}", "objeto", 0, f"Proyecto {i}"))
    con.commit()
    con.close()


def test_blind_package_never_contains_detector_fields():
    _assert_blind([{"conflict_id": "x", "documents": [{"evidence": []}]}])
    try:
        _assert_blind([{"respaldo_evidencia": "secret"}])
    except AssertionError:
        pass
    else:
        raise AssertionError("el detector no fue bloqueado por el guard ciego")


def test_candidate_is_marked_unverified_without_calibration_ids(tmp_path):
    db = tmp_path / "warehouse.sqlite"
    _fixture_db(db)
    output = tmp_path / "audit"
    manifest = build_package(warehouse=db, output_dir=output, main_n=10, stress_n=5)
    assert manifest["status"] == "candidate_independence_unverified"
    assert manifest["calibration_exclusion"]["independence_verified"] is False
    main = json.loads((output / "holdout_main_n100.json").read_text(encoding="utf-8"))
    stress = json.loads((output / "stress_sample_n50.json").read_text(encoding="utf-8"))
    assert len(main) == 10 and len(stress) == 5
    assert {r["conflict_id"] for r in main}.isdisjoint({r["conflict_id"] for r in stress})
    assert not DETECTOR_FIELDS.intersection(json.dumps(main, ensure_ascii=False))


def test_calibration_ids_excluded_when_complete(tmp_path):
    db = tmp_path / "warehouse.sqlite"
    _fixture_db(db)
    output = tmp_path / "audit"
    ids = [f"conflict:{i:024x}" for i in range(150)]
    ids_path = output / "calibration_conflict_ids.txt"
    output.mkdir()
    ids_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    manifest = build_package(warehouse=db, output_dir=output, calibration_ids_path=ids_path, main_n=5, stress_n=5)
    assert manifest["status"] == "ready_for_external_review"
    selected = json.loads((output / "holdout_main_n100.json").read_text(encoding="utf-8"))
    assert not {r["conflict_id"] for r in selected}.intersection(ids)
