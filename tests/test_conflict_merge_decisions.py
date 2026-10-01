"""Decisiones de fusion de conflictos duplicados: datos versionados, llaveados por project_id, con evidencia literal."""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_conflicts as reg  # noqa: E402

PATH = PROJECT_ROOT / "config" / "conflict_merge_decisions.json"


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE project (project_id TEXT, case_id TEXT)")
    c.executemany("INSERT INTO project VALUES (?,?)", [("p1", "c1"), ("p2", "c2"), ("p3", "c3"), ("p4", "c1")])
    return c


def _entry(a="p1", b="p2", **kw):
    e = {"decision_id": "x", "project_ids": [a, b], "decision": "mismo_conflicto", "rationale": "misma disputa",
         "evidence": [{"document_id": "d1", "cita": "texto literal"}]}
    e.update(kw)
    return e


def _write(tmp_path, decisions):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"schema_version": "conflict_merge_decisions", "decisions": decisions}), encoding="utf-8")
    return p


def test_decisions_map_project_pairs_to_case_pairs_and_skip_same_case(tmp_path):
    p = _write(tmp_path, [_entry("p1", "p2"), _entry("p1", "p4", decision_id="y")])
    assert reg.load_conflict_merge_decisions(_conn(), p) == [("c1", "c2")]  # p1 y p4 ya comparten case_id
    assert reg.load_conflict_merge_decisions(_conn(), tmp_path / "no_existe.json") == []


@pytest.mark.parametrize("mutation, message", [
    ({"decision": "distintos"}, "invalida"),
    ({"rationale": ""}, "invalida"),
    ({"evidence": []}, "sin evidencia"),
    ({"evidence": [{"document_id": "d1"}]}, "sin evidencia"),
    ({"project_ids": ["p1", "p1"]}, "dos project_id distintos"),
    ({"project_ids": ["p1", "zzz"]}, "inexistente"),
])
def test_loader_fails_closed(tmp_path, mutation, message):
    p = _write(tmp_path, [_entry(**mutation)])
    with pytest.raises(ValueError, match=message):
        reg.load_conflict_merge_decisions(_conn(), p)


def test_duplicate_pair_and_bad_schema_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicada"):
        reg.load_conflict_merge_decisions(_conn(), _write(tmp_path, [_entry("p1", "p2"), _entry("p2", "p1", decision_id="y")]))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "otro", "decisions": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        reg.load_conflict_merge_decisions(_conn(), bad)


def test_extra_merges_union_conflicts_transitively():
    groups = reg.build_case_groups(["c1", "c2", "c3", "c4"], [], extra_merges=[("c1", "c2"), ("c2", "c3")])
    assert sorted(map(tuple, groups.values())) == [("c1", "c2", "c3"), ("c4",)]


def test_real_decisions_cite_literal_quotes_from_the_source_corpus():
    if not PATH.exists():
        pytest.skip("sin decisiones de fusion")
    decisions = json.loads(PATH.read_text(encoding="utf-8"))["decisions"]
    content_dir = PROJECT_ROOT / "Fuentes" / "fulltext" / "content"
    if not content_dir.exists():
        pytest.skip("corpus local no disponible")
    texts = {}
    for path in content_dir.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        texts[record.get("url")] = re.sub(r"\s+", " ", record.get("text", "")).lower()
    conn = sqlite3.connect(PROJECT_ROOT / "data" / "warehouse.sqlite")
    urls = dict(conn.execute("SELECT document_id, url FROM document"))
    for entry in decisions:
        for ev in entry["evidence"]:
            text = texts.get(urls.get(ev["document_id"]))
            assert text is not None, f"documento sin texto: {ev['document_id']}"
            assert re.sub(r"\s+", " ", ev["cita"]).lower() in text, f"cita no literal en {entry['decision_id']}"
