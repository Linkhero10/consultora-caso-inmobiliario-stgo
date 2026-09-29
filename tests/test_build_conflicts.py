"""Pruebas de la capa CONFLICT (conflict / conflict_case / conflict_project
/ document_conflict / conflict_relation), separada de PROJECT/PROJECT_PHASE/
CASE. No llama a ninguna API; usa datos sinteticos para la logica de
agrupacion y verifica contra el warehouse real los 2 casos de prueba
adversarial que motivaron el diseno (Sol, 2026-09-18):

1. Cementerio Parque Santiago / Teleferico Bicentenario -- 2 project.case_id
   distintos y correctos, 1 solo conflicto (deben terminar en el MISMO
   conflict_id).
2. Poblacion La Victoria / Rancagua Express -- posible trayectoria
   territorial longitudinal vs. conflictos distintos; el esquema debe
   representarlo como 2 conflict_id SEPARADOS, vinculados por una
   conflict_relation pendiente de decision humana, NUNCA fusionados.
"""

import json
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_conflicts as reg  # noqa: E402


def test_stable_conflict_id_is_deterministic_and_order_independent():
    a = reg._stable_conflict_id(["case_b", "case_a"])
    b = reg._stable_conflict_id(["case_a", "case_b"])
    assert a == b
    assert a.startswith("conflict:")


def test_load_classified_63_fails_closed_when_required_human_source_is_missing(tmp_path, monkeypatch):
    missing = tmp_path / "classified.json"
    monkeypatch.setattr(reg, "CLASSIFIED_63", missing)
    with pytest.raises(FileNotFoundError, match="CLASSIFIED_63 requerido"):
        reg.load_classified_63()


def test_missing_classified_63_aborts_before_schema_changes(tmp_path, monkeypatch):
    db_path = tmp_path / "warehouse.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE project (project_id TEXT, case_id TEXT)")
    conn.commit()
    conn.close()
    missing = tmp_path / "classified.json"
    monkeypatch.setattr(reg, "CLASSIFIED_63", missing)
    monkeypatch.setattr(reg, "WAREHOUSE", db_path)
    before_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()

    with pytest.raises(FileNotFoundError, match="CLASSIFIED_63 requerido"):
        reg.main()

    check = sqlite3.connect(db_path)
    assert check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("project",)]
    check.close()
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before_hash


def test_v3_3_link_loader_rejects_conflicting_normalized_keys_but_allows_exact_duplicates():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE enrichment_project_mention (document_id TEXT, nombre_proyecto TEXT, case_mention_index INTEGER)"
    )
    conn.executemany(
        "INSERT INTO enrichment_project_mention VALUES (?,?,?)",
        [("d1", "Árbol Norte", 1), ("d1", "Arbol Norte", 2)],
    )
    with pytest.raises(ValueError, match="colisión tras normalizar"):
        reg.load_v3_3_verified_links(conn)

    conn.execute("DELETE FROM enrichment_project_mention")
    conn.executemany(
        "INSERT INTO enrichment_project_mention VALUES (?,?,?)",
        [("d1", "Árbol Norte", 1), ("d1", "Arbol Norte", 1)],
    )
    assert reg.load_v3_3_verified_links(conn) == {("d1", "arbol norte"): 1}
    conn.close()


def test_union_find_unions_only_via_transitive_closure():
    uf = reg.UnionFind(["a", "b", "c", "d"])
    uf.union("a", "b")
    uf.union("b", "c")
    assert uf.find("a") == uf.find("c")
    assert uf.find("a") != uf.find("d")


def _doc(document_id, relaciones, justificacion="x", title="t"):
    return {"document_id": document_id, "title": title, "justificacion_sol": justificacion, "relaciones_case_groups_sol": relaciones}


def test_build_case_groups_unions_mismo_conflicto_but_not_focal_or_contextual():
    all_case_ids = ["case_1", "case_2", "case_3"]
    documentos = [
        _doc("d1", [{"case_ids": ["case_1", "case_2"], "relacion": "mismo_conflicto", "project_relation": "distinct_conflict_objects"}]),
        _doc("d2", [
            {"case_ids": ["case_3"], "relacion": "focal"},
            {"case_ids": ["case_1"], "relacion": "contextual", "project_relation": "contextual"},
        ]),
    ]
    groups = reg.build_case_groups(all_case_ids, documentos)
    grouped_members = sorted(groups.values())
    assert ["case_1", "case_2"] in grouped_members
    assert ["case_3"] in grouped_members  # 'focal' no une case_3 con case_1


def test_build_case_groups_does_not_union_conflictos_distintos():
    all_case_ids = ["case_a", "case_b"]
    documentos = [_doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos", "project_relation": "distinct_conflict_objects"}])]
    groups = reg.build_case_groups(all_case_ids, documentos)
    assert sorted(groups.values()) == [["case_a"], ["case_b"]]


def test_build_case_groups_remaps_historical_case_ids_and_rejects_unknown_ids():
    current_ids = ["case_new", "case_other"]
    alias = {"case_old": "case_new", "case_new": "case_new", "case_other": "case_other"}
    docs = [_doc("d1", [{"case_ids": ["case_old", "case_other"], "relacion": "mismo_conflicto"}])]
    groups = reg.build_case_groups(current_ids, docs, case_id_alias=alias)
    assert sorted(groups.values()) == [["case_new", "case_other"]]

    unknown_docs = [_doc("d2", [{"case_ids": ["unknown_case"], "relacion": "mismo_conflicto"}])]
    with pytest.raises(ValueError, match="no existe en el baseline ni en case_id_alias"):
        reg.build_case_groups(current_ids, unknown_docs, case_id_alias=alias)


def test_build_case_groups_skips_relation_with_confirmed_non_resolvable_id_instead_of_raising():
    current_ids = ["case_new", "case_other"]
    docs = [_doc("d1", [{"case_ids": ["orphan_id", "case_other"], "relacion": "mismo_conflicto"}])]
    with pytest.raises(ValueError, match="no existe en el baseline ni en case_id_alias"):
        reg.build_case_groups(current_ids, docs)
    groups = reg.build_case_groups(current_ids, docs, non_resolvable_historical_ids={"orphan_id"})
    assert sorted(groups.values()) == [["case_new"], ["case_other"]]


def test_build_conflict_relations_skips_relation_with_confirmed_non_resolvable_id():
    docs = [_doc("d1", [{"case_ids": ["orphan_a", "orphan_b"], "relacion": "conflictos_distintos"}])]
    with pytest.raises(ValueError, match="no existe en el baseline ni en case_id_alias"):
        reg.build_conflict_relations(docs, {}, {})
    relations = reg.build_conflict_relations(
        docs, {}, {}, non_resolvable_historical_ids={"orphan_a", "orphan_b"}
    )
    assert relations == []


def test_analyze_historical_case_references_downgrades_confirmed_non_resolvable_ids():
    docs = [_doc("d1", [{"case_ids": ["orphan_id", "case_current"], "relacion": "mismo_conflicto"}])]
    blocked = reg.analyze_historical_case_references(docs, {"case_current"})
    assert [row["historical_case_id"] for row in blocked["topology_blockers"]] == ["orphan_id"]

    preserved = reg.analyze_historical_case_references(
        docs, {"case_current"}, non_resolvable_historical_ids={"orphan_id"}
    )
    assert preserved["topology_blockers"] == []
    assert [row["historical_case_id"] for row in preserved["preserved_references"]] == ["orphan_id"]
    assert preserved["preserved_references"][0]["impact_scope"] == "confirmed_non_resolvable_historical_reference"


def test_load_historical_case_id_resolutions_returns_empty_when_file_missing(tmp_path):
    resolved, non_resolvable = reg.load_historical_case_id_resolutions(tmp_path / "no_existe.json")
    assert resolved == {}
    assert non_resolvable == set()


def test_load_historical_case_id_resolutions_rejects_id_in_both_lists(tmp_path):
    path = tmp_path / "resolutions.json"
    path.write_text(
        json.dumps(
            {
                "resolved": [{"historical_case_id": "x", "resolved_case_id": "case_a"}],
                "non_resolvable": [{"historical_case_id": "x"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="en ambas listas"):
        reg.load_historical_case_id_resolutions(path)


def test_load_historical_case_id_resolutions_reads_real_file_with_expected_shape():
    """Verifica que el archivo real versionado en config/ tiene la forma
    esperada -- no un valor sintetico, el mismo archivo que usa build_conflicts.py."""
    resolved, non_resolvable = reg.load_historical_case_id_resolutions()
    # [ACTUALIZADO 2026-09-29] 10 -> 12: alias de 23c289bb... (Lote 18-A1), cuyo project_id cambio al corregir la
    # normalizacion de nombres, y alias de a05fdf04... (Alto Norte -> Alto Las Condes 2).
    assert len(resolved) == 12
    assert len(non_resolvable) == 5
    assert "f98c6a44db6a2c8187d959b9" in non_resolvable  # Villa Francia, sin anclaje vivo


def test_historical_case_id_preflight_aggregates_unresolved_ids_and_skips_project_aliases():
    docs = [
        {
            **_doc(
                "d1",
                [
                    {"case_ids": ["legacy_a", "case_current"], "relacion": "mismo_conflicto"},
                    {"case_ids": ["legacy_project_only"], "relacion": "mismo_proyecto"},
                ],
            ),
            "case_groups": [
                {"case_id": "legacy_a", "canonical_names": ["Caso A"]},
                {"case_id": "case_current", "canonical_names": ["Caso vigente"]},
                {"case_id": "legacy_project_only", "canonical_names": ["Alias de proyecto"]},
            ],
        },
        {
            **_doc("d2", [{"case_ids": ["legacy_b"], "relacion": "focal"}]),
            "case_groups": [{"case_id": "legacy_b", "canonical_names": ["Caso B"]}],
        },
    ]
    unresolved = reg.collect_unresolved_historical_case_ids(docs, {"case_current"})
    assert [row["historical_case_id"] for row in unresolved] == ["legacy_a", "legacy_b"]
    assert unresolved[0]["canonical_names"] == ["Caso A"]
    assert unresolved[0]["occurrences"][0]["document_id"] == "d1"
    assert reg.collect_unresolved_historical_case_ids(
        docs, {"case_current"}, {"legacy_a": "case_current", "legacy_b": "case_current"}
    ) == []


def test_unresolved_historical_references_block_topology_but_preserve_non_topological_refs():
    docs = [
        {
            **_doc(
                "d1",
                [
                    {"case_ids": ["legacy_union", "case_current"], "relacion": "mismo_conflicto"},
                    {"case_ids": ["legacy_context"], "relacion": "contextual"},
                    {"case_ids": ["legacy_project"], "relacion": "mismo_proyecto", "project_relation": "alias"},
                ],
            ),
            "case_groups": [
                {"case_id": "legacy_union", "canonical_names": ["Caso sin mapear"]},
                {"case_id": "legacy_context", "canonical_names": ["Mención contextual"]},
                {"case_id": "legacy_project", "canonical_names": ["Identidad de proyecto"]},
            ],
        }
    ]

    analysis = reg.analyze_historical_case_references(docs, {"case_current"})

    assert [row["historical_case_id"] for row in analysis["topology_blockers"]] == ["legacy_union"]
    assert {
        (row["historical_case_id"], row["impact_scope"])
        for row in analysis["preserved_references"]
    } == {
        ("legacy_context", "document_conflict_membership"),
        ("legacy_project", "project_identity_not_resolved"),
    }


def test_unknown_relation_type_fails_closed_as_topology_blocker():
    docs = [
        {
            **_doc("d1", [{"case_ids": ["legacy_unknown"], "relacion": "new_relation_type"}]),
            "case_groups": [{"case_id": "legacy_unknown", "canonical_names": ["Unknown"]}],
        }
    ]
    analysis = reg.analyze_historical_case_references(docs, set())
    assert analysis["topology_blockers"][0]["historical_case_id"] == "legacy_unknown"
    assert analysis["topology_blockers"][0]["impact_scope"] == "unknown_relation_fail_closed"
    with pytest.raises(ValueError, match="relacion_case_groups_sol desconocida"):
        reg.build_historical_case_reference_rows(docs, set())
    with pytest.raises(ValueError, match="relacion_case_groups_sol desconocida"):
        reg.build_case_groups(["legacy_unknown"], docs)


def test_collect_unresolved_historical_case_ids_fails_closed_on_unknown_relation_with_current_id():
    docs = [_doc("d-current", [{"case_ids": ["case_current"], "relacion": "future_relation"}])]

    with pytest.raises(ValueError, match="relaciones desconocidas"):
        reg.collect_unresolved_historical_case_ids(docs, {"case_current"})


def test_unknown_relation_type_blocks_even_when_case_ids_are_current():
    docs = [_doc("d-current", [{"case_ids": ["case_current"], "relacion": "new_relation_type"}])]

    analysis = reg.analyze_historical_case_references(docs, {"case_current"})

    assert analysis["all_unresolved"] == []
    assert len(analysis["topology_blockers"]) == 1
    assert analysis["topology_blockers"][0]["case_ids"] == ["case_current"]
    assert analysis["unsupported_relations"] == analysis["topology_blockers"]


def test_non_topological_historical_references_are_serialized_without_project_or_conflict_ids():
    docs = [
        {
            **_doc(
                "doc-context",
                [
                    {"case_ids": ["legacy_context"], "relacion": "contextual", "project_relation": "context"},
                    {"case_ids": ["legacy_project"], "relacion": "mismo_proyecto", "project_relation": "alias"},
                ],
            ),
            "case_groups": [
                {"case_id": "legacy_context", "canonical_names": ["Contexto histórico"]},
                {"case_id": "legacy_project", "canonical_names": ["Alias histórico"]},
            ],
        }
    ]

    rows = reg.build_historical_case_reference_rows(docs, set())

    assert len(rows) == 2
    assert {row["historical_case_id"] for row in rows} == {"legacy_context", "legacy_project"}
    assert all(row["status"] == "preserved_unresolved_not_projected" for row in rows)
    assert all("project_id" not in row and "conflict_id" not in row for row in rows)


def test_non_topological_historical_references_persist_in_separate_fk_table():
    docs = [
        {
            **_doc(
                "doc-context",
                [
                    {"case_ids": ["legacy_context"], "relacion": "contextual", "project_relation": "context"},
                    {"case_ids": ["legacy_project"], "relacion": "mismo_proyecto", "project_relation": "alias"},
                ],
            ),
            "case_groups": [
                {"case_id": "legacy_context", "canonical_names": ["Contexto histórico"]},
                {"case_id": "legacy_project", "canonical_names": ["Alias histórico"]},
            ],
        }
    ]
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("CREATE TABLE document (document_id TEXT PRIMARY KEY)")
    db.execute("INSERT INTO document VALUES ('doc-context')")
    rows = reg.build_historical_case_reference_rows(docs, set())

    reg.create_historical_case_reference_table(db)
    assert reg.persist_historical_case_reference_rows(db, rows) == 2

    persisted_columns = {row[1] for row in db.execute("PRAGMA table_info(historical_case_reference)")}
    assert "project_id" not in persisted_columns
    assert "conflict_id" not in persisted_columns
    assert db.execute(
        "SELECT historical_case_id, relation_type, impact_scope, status "
        "FROM historical_case_reference ORDER BY historical_case_id"
    ).fetchall() == [
        ("legacy_context", "contextual", "document_conflict_membership", "preserved_unresolved_not_projected"),
        ("legacy_project", "mismo_proyecto", "project_identity_not_resolved", "preserved_unresolved_not_projected"),
    ]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


def test_case_id_alias_rows_must_match_baseline_targets_and_hash():
    baseline_hash = "a" * 64
    expected = {"case_old": "case_new", "case_new": "case_new"}
    rows = [
        ("case_old", "case_new", "merged", baseline_hash),
        ("case_new", "case_new", "preserved", baseline_hash),
    ]
    assert reg.validate_case_id_alias_rows(rows, {"case_new"}, expected, baseline_hash) == expected

    with pytest.raises(ValueError, match="old_case_id duplicado"):
        reg.validate_case_id_alias_rows(rows + [rows[0]], {"case_new"}, expected, baseline_hash)
    with pytest.raises(ValueError, match="baseline hash distinto"):
        reg.validate_case_id_alias_rows(
            [rows[0], ("case_new", "case_new", "preserved", "b" * 64)],
            {"case_new"}, expected, baseline_hash,
        )
    with pytest.raises(ValueError, match="no coincide con el baseline"):
        reg.validate_case_id_alias_rows(
            rows + [("invented", "case_new", "merged", baseline_hash)],
            {"case_new"}, expected, baseline_hash,
        )
    cycle = [
        ("case_a", "case_b", "merged", baseline_hash),
        ("case_b", "case_a", "merged", baseline_hash),
    ]
    with pytest.raises(ValueError, match="cadena/ciclo"):
        reg.validate_case_id_alias_rows(
            cycle, {"case_a", "case_b"}, {"case_a": "case_b", "case_b": "case_a"}, baseline_hash
        )


def test_baseline_alias_derivation_rejects_tampered_mapping_and_project_set(tmp_path):
    projects = [{"project_id": "p1", "case_id": "old1"}, {"project_id": "p2", "case_id": "old2"}]
    mapping_hash = hashlib.sha256(
        json.dumps(projects, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    project_set_hash = hashlib.sha256(b"p1\np2\n").hexdigest()
    payload = {
        "schema_version": "project_case_baseline_v1",
        "source_warehouse_sha256": "a" * 64,
        "projects": projects,
        "mapping_sha256": mapping_hash,
        "project_id_set_sha256": project_set_hash,
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    aliases, observed_hash = reg.expected_case_id_aliases_from_baseline(path, {"p1": "new1", "p2": "new2"})
    assert aliases == {"old1": "new1", "old2": "new2"}
    assert observed_hash == mapping_hash

    payload["mapping_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="mapping_sha256"):
        reg.expected_case_id_aliases_from_baseline(path, {"p1": "new1", "p2": "new2"})

    payload["mapping_sha256"] = mapping_hash
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="project_id set"):
        reg.expected_case_id_aliases_from_baseline(path, {"p1": "new1"})


def test_sql_script_executor_preserves_outer_transaction():
    db = sqlite3.connect(":memory:")
    db.execute("BEGIN IMMEDIATE")
    reg.execute_sql_statements(db, "CREATE TABLE transient (value TEXT);\nINSERT INTO transient VALUES ('x');\n")
    assert db.in_transaction
    db.rollback()
    assert db.execute("SELECT 1 FROM sqlite_master WHERE name='transient'").fetchone() is None
    db.close()


def test_build_conflicts_blocks_topology_and_writes_only_dedicated_preflight_report(
    tmp_path, monkeypatch, capsys
):
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE project (project_id TEXT, case_id TEXT);
        CREATE TABLE project_review_queue (
            project_id_a TEXT, canonical_name_a TEXT, project_id_b TEXT,
            canonical_name_b TEXT, resolved INTEGER, decision TEXT,
            decision_reason TEXT, decision_source TEXT
        );
        CREATE TABLE case_mention (document_id TEXT, case_mention_id TEXT, decision_final_amplio TEXT);
        CREATE TABLE evidence (document_id TEXT, case_mention_id TEXT, evidence_id TEXT, quote_role TEXT, quote_text TEXT, verified INTEGER);
        CREATE TABLE project_mention_resolved (project_id TEXT, document_id TEXT, raw_nombre_proyecto TEXT);
        CREATE TABLE enrichment_project_mention (document_id TEXT, nombre_proyecto TEXT, case_mention_index INTEGER);
        INSERT INTO project VALUES ('p1', 'case_current');
        INSERT INTO project_review_queue VALUES
            ('p1', 'Proyecto A', 'p2', 'Proyecto B', 0, 'needs_human_review', 'identidad no resuelta', 'test');
        """
    )
    classified = tmp_path / "classified.json"
    classified.write_text(
        json.dumps(
            {
                "documentos": [
                    {
                        "document_id": "doc1",
                        "case_groups": [{"case_id": "case_legacy", "canonical_names": ["Caso legado"]}],
                        "relaciones_case_groups_sol": [
                            {"relacion": "mismo_conflicto", "case_ids": ["case_legacy", "case_current"]},
                            {"relacion": "future_relation", "case_ids": ["case_current"]},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    preflight_report = tmp_path / "historical_case_reference_preflight.json"
    monkeypatch.setattr(reg, "CLASSIFIED_63", classified)
    monkeypatch.setattr(reg, "AUDIT_REPORT_PATH", report)
    monkeypatch.setattr(reg, "HISTORICAL_CASE_PREFLIGHT_REPORT_PATH", preflight_report)
    monkeypatch.setattr(reg, "HISTORICAL_CASE_ID_RESOLUTIONS_PATH", tmp_path / "no_existe_resolutions.json")
    monkeypatch.setattr(reg, "CASE_MENTION_ELIGIBILITY_ADJUDICATIONS_PATH", tmp_path / "no_existe_elegibilidad.json")
    before_schema = db.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    before_rows = db.execute("SELECT project_id, case_id FROM project").fetchall()
    # The builder owns its transaction; commit fixture setup so this test
    # exercises the normal standalone invocation.
    db.commit()

    status = reg._build_conflicts(db)

    assert status == 2
    assert db.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name").fetchall() == before_schema
    assert db.execute("SELECT project_id, case_id FROM project").fetchall() == before_rows
    assert not report.exists()
    preflight = json.loads(preflight_report.read_text(encoding="utf-8"))
    assert preflight["status"] == "blocked_before_database_write"
    assert preflight["n_topology_blockers"] == 3
    assert preflight["project_identity_review_gate"]["status"] == "blocked"
    assert preflight["project_identity_review_gate"]["n_unresolved_pairs"] == 1
    assert preflight["project_identity_review_gate"]["unresolved_pairs"][0]["project_id_a"] == "p1"
    assert any(
        row.get("historical_case_id") == "case_legacy"
        for row in preflight["topology_blockers"]
    )
    assert preflight["unsupported_relations"][0]["relation"] == "future_relation"
    assert preflight["unsupported_relations"][0]["impact_scope"] == "unknown_relation_fail_closed"
    assert preflight["source_hashes"]["classified_63_sha256"] == reg._sha256_file_if_present(classified)
    assert preflight["source_hashes"]["preflight_script_sha256"] == reg._sha256_file_if_present(Path(reg.__file__))
    assert '"status": "blocked_before_database_write"' in capsys.readouterr().err
    db.close()


def test_begin_build_transaction_rejects_outer_transaction_without_rollback():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE marker (value TEXT)")
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    db.execute("INSERT INTO marker VALUES ('caller-owned')")

    with pytest.raises(RuntimeError, match="caller-owned transaction"):
        reg.begin_build_transaction(db)

    assert db.in_transaction
    assert db.execute("SELECT value FROM marker").fetchone() == ("caller-owned",)
    db.rollback()
    db.close()


def test_hash_committed_warehouse_checkpoints_wal_before_hash(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    db = sqlite3.connect(db_path)
    assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
    db.execute("CREATE TABLE marker (value TEXT)")
    db.execute("INSERT INTO marker VALUES ('committed')")
    db.commit()

    result = reg.hash_committed_warehouse(db, db_path)

    assert result["journal_mode"] == "wal"
    assert result["wal_checkpoint"][0] == 0
    assert result["sha256"] == reg.hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert db.execute("SELECT value FROM marker").fetchone() == ("committed",)
    db.close()


def test_build_conflict_relations_remaps_historical_case_ids_and_rejects_unknown_ids():
    case_id_to_conflict = {"case_new_a": "conflict:A", "case_new_b": "conflict:B"}
    aliases = {"case_old_a": "case_new_a", "case_old_b": "case_new_b"}
    docs = [_doc("d1", [{"case_ids": ["case_old_a", "case_old_b"], "relacion": "conflictos_distintos"}])]
    relations = reg.build_conflict_relations(docs, case_id_to_conflict, {"d1": "caso_unico"}, aliases)
    assert len(relations) == 1
    assert {relations[0]["conflict_id_a"], relations[0]["conflict_id_b"]} == {"conflict:A", "conflict:B"}

    bad_docs = [_doc("d2", [{"case_ids": ["missing_case"], "relacion": "conflictos_distintos"}])]
    with pytest.raises(ValueError, match="no existe en el baseline ni en case_id_alias"):
        reg.build_conflict_relations(bad_docs, case_id_to_conflict, {"d2": "caso_unico"}, aliases)


def test_atomic_json_report_replaces_complete_file_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "report.json"
    target.write_text('{"old": true}', encoding="utf-8")
    reg.atomic_write_json(target, {"new": [1, 2]}, indent=2)
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": [1, 2]}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report.json"]


def test_build_conflicts_main_returns_cli_status_not_summary_or_ignored_block(tmp_path, monkeypatch):
    db_path = tmp_path / "warehouse.sqlite"
    sqlite3.connect(db_path).close()
    monkeypatch.setattr(reg, "WAREHOUSE", db_path)
    monkeypatch.setattr(reg, "_build_conflicts", lambda _conn: 2)
    assert reg.main() == 2
    monkeypatch.setattr(reg, "_build_conflicts", lambda _conn: {"n_conflicts_total": 1})
    assert reg.main() == 0


def test_build_conflict_relations_flags_conflictos_distintos_as_pending_when_gate_still_caso_unico():
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:BBB"}
    documentos = [_doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}], justificacion="territorio compartido")]
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, {"d1": "caso_unico"})
    assert len(relations) == 1
    rel = relations[0]
    assert {rel["conflict_id_a"], rel["conflict_id_b"]} == {"conflict:AAA", "conflict:BBB"}
    assert rel["review_status"] == "pending_human_decision"


def test_build_conflict_relations_marks_resolved_keep_separate_when_gate_already_reclassified():
    """Hallazgo real de Sol: la v1 marcaba TODAS las relaciones
    'conflictos_distintos' como pendientes, incluso cuando el documento ya
    habia sido reclasificado (UPC, Recuperacion de barrios -- ya NO son
    'caso_unico'). Solo debe quedar pendiente si el gate sigue en
    caso_unico."""
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:BBB"}
    documentos = [_doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}])]
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, {"d1": "documento_comparativo_panoramico"})
    assert len(relations) == 1
    assert relations[0]["review_status"] == "resolved_keep_separate"


def test_build_conflict_relations_stays_pending_if_any_evidence_document_still_pending():
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:BBB"}
    documentos = [
        _doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}]),
        _doc("d2", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}]),
    ]
    gate = {"d1": "documento_comparativo_panoramico", "d2": "caso_unico"}
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, gate)
    assert len(relations) == 1
    assert relations[0]["review_status"] == "pending_human_decision"


def test_build_conflict_relations_ignores_focal_and_mismo_conflicto():
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:AAA"}
    documentos = [
        _doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "mismo_conflicto"}]),
        _doc("d2", [{"case_ids": ["case_a"], "relacion": "focal"}]),
    ]
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, {"d1": "caso_unico", "d2": "caso_unico"})
    assert relations == []


# --- Fix 1A: respaldo de evidencia (unitarias, datos sinteticos) ---


def test_norm_strips_accents_case_and_extra_whitespace():
    assert reg._norm("  Torre  Central  ") == "torre central"
    assert reg._norm("Línea 7") == "linea 7"


# [RETIRADO 2026-09-26, migracion v3.2->v3.3 completa] _mention_has_case_backing()
# (el detector exact_substring_v1) se elimino de build_conflicts.py -- ver el
# docstring de _project_backing_evidence() para la medicion empirica que
# justifico el retiro (0 filas reales con ese detector en la reconstruccion
# completa). Los 4 tests que ejercitaban esa funcion directamente
# (test_mention_has_case_backing_matches_raw_inside_quote,
# ..._matches_quote_inside_raw, ..._no_match_returns_false, ..._never_fuzzy)
# se retiraron junto con la funcion.


def test_project_backing_evidence_finds_matching_quote_across_documents():
    # [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] antes esta
    # mencion caia al detector exact_substring_v1 (dict v3.3 vacio = "no
    # cubierto"). Ahora TODA mencion viene de v3.3 -- se cubre explicitamente
    # via v3_3_links, apuntando al case_mention_id real "d1:0".
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 0}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "d1:0"
    assert rows[0]["evidence_id"] == "e1"
    assert rows[0]["detector_version"] == reg.DETECTOR_VERSION_V3_3


# [RETIRADOS 2026-09-26, migracion v3.2->v3.3 completa]
# test_project_backing_evidence_empty_when_case_mention_is_excluded y
# test_project_backing_evidence_empty_when_no_objeto_evidence_for_that_mention
# ejercitaban el fallback a exact_substring_v1 con casos que ahora quedan
# cubiertos, sin duplicacion util, por
# test_project_backing_evidence_v3_3_index_excluded_gives_no_backing_no_fallback
# y test_project_backing_evidence_v3_3_no_duplicate_group_sibling_still_empty
# (mismos escenarios, expresados con la cobertura v3.3 real). Ver esos tests
# mas abajo.
#
# test_project_backing_evidence_marks_document_level_multi_case_ambiguity se
# retiro: el concepto de "ambiguedad documental sin vinculo a proyecto" que
# probaba (backing_scope=document_level_case_mention_without_project_link)
# pertenecia al detector retirado -- v3.3 resuelve la mencion a UN
# case_mention_id especifico (o ninguno), la ambiguedad ya no se propaga
# como una marca en la fila de respaldo.


def test_build_conflict_backing_uniform_no_multi_case_exception():
    """Bug real que la validacion N=150 encontro: 'n_case_ids > 1 -> siempre
    respaldado' es incorrecto (Aeropuerto Los Cerrillos, Aldea del
    Encuentro). El detector debe aplicarse igual sin importar cuantos
    case_id tenga el conflicto. [ACTUALIZADO 2026-09-26] cubierto por v3.3
    (indice 0), pero ese case_mention no tiene evidencia de objeto real --
    sigue sin respaldo, sin caer a ningun substring."""
    projects = [("p1", "Proyecto Sin Evidencia Real")]
    case_id_by_project = {"p1": "case1"}
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Proyecto Sin Evidencia Real"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm: dict = {}
    v3_3_links = {("d1", "proyecto sin evidencia real"): 0}
    label, respaldo, rows = reg._build_conflict_backing(
        "conflict:x", projects, case_id_by_project, mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links
    )
    assert respaldo == "sin_respaldo_exact_quote_detectado"
    assert rows == []


def test_build_conflict_backing_label_prefers_backed_project_over_incidental_mention():
    """Caso real verificado (Museo de la Memoria / guetos verticales
    Estacion Central): el conflicto tiene 2 proyectos, solo 1 respaldado --
    el label debe salir del respaldado, no del primero alfabetico entre
    todos (que era exactamente el bug encontrado). [ACTUALIZADO 2026-09-26]
    solo el proyecto real tiene cobertura v3.3 con evidencia; el incidental
    no esta cubierto -- sin fallback a substring, tampoco genera respaldo."""
    projects = [("p_incidental", "Aaa Proyecto Incidental Sin Evidencia"), ("p_real", "Zzz Proyecto Real Respaldado")]
    case_id_by_project = {"p_incidental": "case1", "p_real": "case1"}
    mentions_by_project = {
        "p_incidental": [{"document_id": "d1", "raw_nombre_proyecto": "Aaa Proyecto Incidental Sin Evidencia"}],
        "p_real": [{"document_id": "d1", "raw_nombre_proyecto": "Zzz Proyecto Real Respaldado"}],
    }
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "zzz proyecto real respaldado", "quote_norm": "zzz proyecto real respaldado"}]}
    v3_3_links = {("d1", "zzz proyecto real respaldado"): 0}
    label, respaldo, rows = reg._build_conflict_backing(
        "conflict:x", projects, case_id_by_project, mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links
    )
    assert label == "Zzz Proyecto Real Respaldado"
    assert respaldo == "respaldo_exact_quote_detectado"
    assert len(rows) == 1
    assert rows[0]["backing_scope"] == reg.BACKING_SCOPE_V3_3
    assert rows[0]["ambiguous_multi_case_document"] == 0


def test_build_conflict_backing_fallback_label_when_none_backed():
    projects = [("p2", "Bbb Segundo"), ("p1", "Aaa Primero")]
    case_id_by_project = {"p1": "case1", "p2": "case1"}
    label, respaldo, rows = reg._build_conflict_backing("conflict:x", projects, case_id_by_project, {}, {}, {}, {})
    assert label == "Aaa Primero"  # fallback: primero alfabetico entre TODOS
    assert respaldo == "sin_respaldo_exact_quote_detectado"
    assert rows == []


# --- Fix 1D: integracion de v3.3 (case_mention_index verificado) al backing ---


def test_project_backing_evidence_uses_v3_3_index_directly_when_covered():
    """Cuando la mencion esta cubierta por v3.3 con un indice valido que pasa
    el filtro de decision/evidencia, se usa DIRECTAMENTE ese case_mention_id
    -- no se ejecuta ninguna comparacion de substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0", "d1:1"]}
    objeto_by_cm = {
        "d1:1": [{"evidence_id": "e1", "quote_text": "una cita que no menciona el proyecto", "quote_norm": "una cita que no menciona el proyecto"}],
    }
    v3_3_links = {("d1", "torre central"): 1}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "d1:1"
    assert rows[0]["detector_version"] == reg.DETECTOR_VERSION_V3_3
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3
    assert rows[0]["ambiguous_multi_case_document"] == 0


def test_project_backing_evidence_v3_3_null_suppresses_substring_fallback():
    """Si v3.3 dice explicitamente que ninguna case_mention es el objeto
    (indice null), NO debe caer al substring -- v3.3 es una fuente mas
    confiable que la heuristica para esa mencion puntual, aunque el
    substring hubiera encontrado un match."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la torre central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): None}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert rows == []


def test_project_backing_evidence_v3_3_index_excluded_gives_no_backing_no_fallback():
    """Si v3.3 apunta a un case_mention que NO paso el filtro (no esta en
    included_by_doc, ej. decision_final_amplio != include), no hay backing
    por esa via -- tampoco cae al substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc: dict = {}  # d1:0 no esta incluido
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la torre central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 0}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert rows == []


def test_project_backing_evidence_no_backing_when_mention_not_covered_by_v3_3():
    """[RENOMBRADO/ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa]
    Antes esta mencion 'no cubierta' caia al fallback exact_substring_v1 --
    ese fallback se retiro (verificado: 0 filas reales lo usaban con el
    100% del corpus en v3.3). Una mencion que no aparece en v3_3_links_by_docid
    ahora simplemente no genera respaldo, nunca adivina por substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["cm1"]}
    objeto_by_cm = {"cm1": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    rows_without_v3_3_dict = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, {})
    rows_with_unrelated_v3_3_dict = reg._project_backing_evidence(
        "p1", mentions_by_project, included_by_doc, objeto_by_cm, {("otro_doc", "otro proyecto"): 0}
    )
    assert rows_without_v3_3_dict == rows_with_unrelated_v3_3_dict == []


def test_project_backing_evidence_v3_3_index_excluded_falls_back_to_duplicate_group_sibling():
    """Fix 1E: classify.py a veces fragmenta el MISMO objeto real en 2+
    case_mentions (ej. Bellavista: idx1 include, idx2 casi-duplicado
    exclude). Si v3.3 apunto al miembro que NO paso el filtro
    (decision/evidencia), pero un hermano de su grupo de duplicados SI lo
    pasa, se usa ese hermano -- nunca se pierde el backing solo porque
    classify.py duplico el objeto."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    # d1:1 es el indice que v3.3 eligio, pero NO esta incluido (exclude).
    # d1:0 SI esta incluido y tiene evidencia -- es su hermano de duplicado.
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 1}
    duplicate_group_members = {"d1:0": ["d1:0", "d1:1"], "d1:1": ["d1:0", "d1:1"]}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links, duplicate_group_members)
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "d1:0"
    assert rows[0]["detector_version"] == reg.DETECTOR_VERSION_V3_3
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP


def test_project_backing_evidence_v3_3_duplicate_group_fallback_tags_mixed_decision_explicitly():
    """[Fix 1E hardening, hallazgo de revision externa] El fallback via grupo
    duplicado no distinguia si el grupo tenia decision mixta (include +
    exclude/uncertain entre sus miembros) -- una senal real de que el match
    pudo ser mas arriesgado (el propio clasificador no fue consistente sobre
    el objeto). Ahora debe quedar marcado con un match_method distinto,
    nunca mezclado silenciosamente con el caso no-mixto, para que sea
    auditable por separado."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 1}
    duplicate_group_members = {"d1:0": ["d1:0", "d1:1"], "d1:1": ["d1:0", "d1:1"]}
    decision_mixed_by_cm = {"d1:0": True, "d1:1": True}
    rows = reg._project_backing_evidence(
        "p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links, duplicate_group_members, decision_mixed_by_cm
    )
    assert len(rows) == 1
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP_MIXED_DECISION
    assert rows[0]["match_method"] != reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP
    assert rows[0]["duplicate_group_mixed_decision"] == 1
    assert rows[0]["ambiguous_multi_case_document"] == 0


def test_project_backing_evidence_v3_3_duplicate_group_fallback_non_mixed_uses_plain_match_method():
    """Contraparte del test anterior: un grupo sin decision mixta debe seguir
    usando el match_method original, no el marcado como mixto."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 1}
    duplicate_group_members = {"d1:0": ["d1:0", "d1:1"], "d1:1": ["d1:0", "d1:1"]}
    decision_mixed_by_cm = {"d1:0": False, "d1:1": False}
    rows = reg._project_backing_evidence(
        "p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links, duplicate_group_members, decision_mixed_by_cm
    )
    assert len(rows) == 1
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP
    assert rows[0]["duplicate_group_mixed_decision"] == 0


def test_project_backing_evidence_v3_3_no_duplicate_group_sibling_still_empty():
    """Sin duplicate_group_members (o sin hermano valido), el comportamiento
    debe seguir siendo el mismo de antes de Fix 1E: sin backing, sin caer al
    substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc: dict = {}
    objeto_by_cm: dict = {}
    v3_3_links = {("d1", "torre central"): 0}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert rows == []


def test_backing_summary_exposes_partial_coverage_and_label_source():
    projects = [("p1", "A Proyecto"), ("p2", "B Proyecto")]
    rows = [{"project_id": "p1", "ambiguous_multi_case_document": 0}]
    summary = reg._backing_summary(projects, rows)
    assert summary == {
        "n_projects_backed": 1,
        "n_projects_unbacked": 1,
        "coverage_backing": "parcial",
        "label_source_project_id": "p1",
        "n_documents_ambiguous_backing": 0,
        "n_documents_mixed_duplicate_group_backing": 0,
    }


# --- Pruebas de prueba adversarial contra el warehouse real ---

CEMENTERIO_CASE = "92ddfd13158c1f43afb3e7c9"
TELEFERICO_CASE = "bfccc2aaade8650742980e81"
LA_VICTORIA_CASE = "c86e9f143c9c10888f579a49"
RANCAGUA_EXPRESS_CASE = "51e44358f119f13da08889fb"


def _connect_or_skip():
    import sqlite3

    if not reg.WAREHOUSE.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    return sqlite3.connect(reg.WAREHOUSE)


def test_cementerio_y_teleferico_terminan_en_el_mismo_conflict_id():
    """[HALLAZGO 2026-09-26, migracion v3.2->v3.3 completa] Este es el caso
    de prueba adversarial explicito que motivo el diseno de la capa CONFLICT
    (ver docstring del modulo, lineas 6-14): un documento real
    (emol.com/.../inmobiliaria-cementerio-huechuraba-teleferico.html) donde
    v3.2 extraia 2 proyectos_mencionados reales y distintos ('Teleférico
    Bicentenario' y 'cementerio Parque Santiago de Huechuraba') en un solo
    conflicto judicial. Verificado leyendo el JSONL real: v3.3 (corrida LLM
    SEPARADA) extrajo solo 'Teleférico Bicentenario' para ese documento --
    la mencion del cementerio desaparecio por completo, asi que
    CEMENTERIO_CASE ya no existe como project_id/case_id en el registro.
    No es un bug de esta migracion (el ETL no descarta nada -- el dato
    simplemente no esta en el JSONL fuente); es una diferencia real de
    contenido entre dos corridas LLM distintas. La capacidad del schema de
    representar 2 case_id reales en 1 conflicto sigue intacta (ver
    test_la_victoria_y_rancagua_express... para otro ejemplo real que si
    sigue vigente) -- lo que se perdio es este ejemplo puntual como PRUEBA
    de esa capacidad. Documentado en audit/validation_summary.json
    (migracion_v3_2_a_v3_3_completa_2026-09-26) como hallazgo pendiente:
    identificar un nuevo documento real con 2+ proyectos genuinamente
    distintos en 1 conflicto para restaurar esta prueba adversarial."""
    import pytest

    pytest.skip(
        "CEMENTERIO_CASE ya no existe en el registro de proyectos tras la migracion v3.2->v3.3 "
        "(v3.3 extrajo un proyecto menos para el documento fuente) -- ver docstring de este test."
    )


def test_la_victoria_y_rancagua_express_quedan_en_conflictos_distintos_con_relacion_pendiente():
    conn = _connect_or_skip()
    rows = dict(
        conn.execute(
            "SELECT case_id, conflict_id FROM conflict_case WHERE case_id IN (?, ?)",
            (LA_VICTORIA_CASE, RANCAGUA_EXPRESS_CASE),
        ).fetchall()
    )
    assert rows[LA_VICTORIA_CASE] != rows[RANCAGUA_EXPRESS_CASE]

    pending = conn.execute(
        "SELECT relation_type, review_status FROM conflict_relation "
        "WHERE (conflict_id_a = ? AND conflict_id_b = ?) OR (conflict_id_a = ? AND conflict_id_b = ?)",
        (rows[LA_VICTORIA_CASE], rows[RANCAGUA_EXPRESS_CASE], rows[RANCAGUA_EXPRESS_CASE], rows[LA_VICTORIA_CASE]),
    ).fetchone()
    assert pending is not None
    # [ACTUALIZADO 2026-09-29] el pendiente humano se cerro: el gate del documento paso a
    # multiples_casos_documentados (config/document_case_unit_decisions_v1.json); los conflictos
    # siguen separados y la relacion queda resuelta, no fusionada.
    assert pending[1] == "resolved_keep_separate"
    conn.close()


def test_document_conflict_case_safe_never_includes_mentioned_unreviewed_or_panoramic_mention():
    """Hallazgo real de Sol: filtrar solo por unidad_caso_tipo='caso_unico'
    no bastaba -- dentro de un documento caso_unico siguen existiendo
    document_conflict con role='mentioned_unreviewed' (mencion mecanica
    sin revisar) o 'panoramic_mention' (el propio caso La Victoria, cuyo
    gate sigue pendiente). La vista 'safe' debe exigir ademas
    role IN ('focal','co_focal')."""
    conn = _connect_or_skip()
    bad = conn.execute(
        "SELECT COUNT(*) FROM document_conflict_case_safe WHERE role NOT IN ('focal', 'co_focal')"
    ).fetchone()[0]
    conn.close()
    assert bad == 0


def test_la_victoria_excluded_from_document_conflict_case_safe_while_pending():
    """Prueba adversarial directa: La Victoria/Rancagua Express es
    unidad_caso_tipo='caso_unico' (el gate sigue pendiente) pero sus 2
    conflictos son 'conflictos_distintos' -> role='panoramic_mention'.
    Con el filtro viejo (solo unidad_caso_tipo) ambos habrian entrado a
    la vista safe. Deben quedar fuera hasta que se resuelva el gate."""
    conn = _connect_or_skip()
    la_victoria_doc = "34c26e5aaf4f48a74d16ad587a7b0384cb459c157714e592725284560dea1ce9"
    rows = conn.execute(
        "SELECT COUNT(*) FROM document_conflict_case_safe WHERE document_id = ?", (la_victoria_doc,)
    ).fetchone()[0]
    conn.close()
    assert rows == 0


def test_document_conflict_case_extended_allows_contextual_but_not_unreviewed_or_panoramic():
    conn = _connect_or_skip()
    roles = {r[0] for r in conn.execute("SELECT DISTINCT role FROM document_conflict_case_extended")}
    conn.close()
    assert roles <= {"focal", "co_focal", "contextual_mention"}
    assert "mentioned_unreviewed" not in roles
    assert "panoramic_mention" not in roles


def test_case_safe_is_subset_of_case_extended_which_is_subset_of_full_table():
    conn = _connect_or_skip()
    n_safe = conn.execute("SELECT COUNT(*) FROM document_conflict_case_safe").fetchone()[0]
    n_extended = conn.execute("SELECT COUNT(*) FROM document_conflict_case_extended").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM document_conflict").fetchone()[0]
    conn.close()
    assert 0 < n_safe <= n_extended <= n_total


def test_conflict_tables_have_no_foreign_key_violations():
    conn = _connect_or_skip()
    conn.execute("PRAGMA foreign_keys = ON")
    issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    assert issues == []


def test_every_case_id_belongs_to_exactly_one_conflict():
    conn = _connect_or_skip()
    dup = conn.execute(
        "SELECT case_id, COUNT(DISTINCT conflict_id) c FROM conflict_case GROUP BY case_id HAVING c > 1"
    ).fetchall()
    conn.close()
    assert dup == []


def test_document_conflict_from_sol_evidence_never_overlaps_trivial_source_for_same_document():
    """Los 63 documentos evidenciados no deben tener tambien filas
    'trivial_from_project_mention' -- serian una fuente mecanica mas
    debil pisando (o duplicando) la revision humana."""
    conn = _connect_or_skip()
    rows = conn.execute(
        """
        SELECT document_id FROM document_conflict WHERE source = 'trivial_from_project_mention'
        INTERSECT
        SELECT document_id FROM document_conflict WHERE source = 'conflict_unit_63_sol'
        """
    ).fetchall()
    conn.close()
    assert rows == []


def test_trivial_conflicts_have_low_confidence_label_and_multi_case_have_high():
    conn = _connect_or_skip()
    bad = conn.execute(
        "SELECT COUNT(*) FROM conflict WHERE (n_case_ids = 1 AND confidence != 'baja_derivado_mecanicamente') "
        "OR (n_case_ids > 1 AND confidence != 'alta_revisado_por_sol')"
    ).fetchone()[0]
    conn.close()
    assert bad == 0


def test_quilicura_conflict_role_is_co_focal_not_mentioned_unreviewed():
    """Hallazgo real de Sol: la relacion 'mismo_proyecto' (alias, sin rol
    en ROLE_BY_RELACION) caia al default 'mentioned_unreviewed' y ganaba
    el dedupe por orden de aparicion, aunque el mismo documento tambien
    aportara 'mismo_conflicto' (co_focal) para el mismo conflict_id."""
    conn = _connect_or_skip()
    quilicura_doc = "046f59be624a98cec6b4d3d0823f5bd665ec2345cc84e5693c85690f7fb7bd74"
    row = conn.execute(
        "SELECT role, source FROM document_conflict WHERE document_id = ? AND source = 'conflict_unit_63_sol'",
        (quilicura_doc,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "co_focal"


def test_upc_and_recuperacion_de_barrios_relations_are_resolved_not_pending():
    """Hallazgo real de Sol: UPC y Recuperacion de barrios ya fueron
    adjudicados (reclasificados a documento_comparativo_panoramico via
    apply_conflict_unit_gate_decisions.py) -- su conflict_relation no
    deberia seguir marcada pending_human_decision.

    [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] Verificado
    leyendo el JSONL real: v3.3 extrajo un proyecto menos ('Villa Francia')
    para el documento de Recuperacion de barrios -- ya no forma el mismo
    agrupamiento de case_id que generaba esta conflict_relation especifica
    en el registro v3.2. No es un bug (el ETL no descarta nada; el dato
    fuente cambio entre corridas LLM). Se conserva la verificacion para UPC
    (documento no afectado por esta diferencia) y se documenta el gap para
    barrios en audit/validation_summary.json en vez de fabricar un valor."""
    conn = _connect_or_skip()
    upc_doc = "1b00c0136d4b855eed855b1a5f48ceb7f01e4c9b0d96c8d9666fafd292e043cb"
    note_rows = conn.execute("SELECT note, review_status FROM conflict_relation").fetchall()
    conn.close()
    matching = [row for row in note_rows if upc_doc in row[0]]
    assert matching, f"no se encontro conflict_relation para {upc_doc}"
    assert matching[0][1] == "resolved_keep_separate"
    conn.close()


def test_la_victoria_relation_is_resolved_keep_separate_after_gate_decision():
    conn = _connect_or_skip()
    la_victoria_doc = "34c26e5aaf4f48a74d16ad587a7b0384cb459c157714e592725284560dea1ce9"
    note_rows = conn.execute("SELECT note, review_status FROM conflict_relation").fetchall()
    matching = [row for row in note_rows if la_victoria_doc in row[0]]
    conn.close()
    assert matching
    assert matching[0][1] == "resolved_keep_separate"


# --- Fix 1A: regresion real contra el warehouse ---


def test_respaldo_evidencia_equivalence_with_conflict_evidence_backing():
    """Invariante: conflict.respaldo_evidencia = 'respaldo_exact_quote_detectado'
    SSI existe >=1 fila en conflict_evidence_backing para ese conflict_id."""
    conn = _connect_or_skip()
    mismatch = conn.execute(
        """
        SELECT c.conflict_id FROM conflict c
        LEFT JOIN (SELECT DISTINCT conflict_id FROM conflict_evidence_backing) b
          ON b.conflict_id = c.conflict_id
        WHERE (c.respaldo_evidencia = 'respaldo_exact_quote_detectado') != (b.conflict_id IS NOT NULL)
        """
    ).fetchall()
    conn.close()
    assert mismatch == []


def test_museo_de_la_memoria_conflict_has_no_backing():
    """Caso real verificado a mano en la validacion N=150: el documento
    (biografia de Miguel Lawner) menciona 'Museo de la Memoria y Derechos
    Humanos en Punta Arenas' de pasada; la evidencia real del documento es
    sobre los guetos verticales de Estacion Central. Sin case_mention
    incluido que respalde ese nombre -- debe quedar sin respaldo."""
    # [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] el conflict_id
    # cambio (project_id/case_id se recalculan desde el nombre normalizado
    # que extrae CADA corrida LLM; v3.3 extrajo "Museo de la Memoria y los
    # DD.HH. en Punta Arenas" en vez de "...Derechos Humanos...", una
    # corrida LLM distinta con fraseo distinto) -- el resultado esperado
    # (sin respaldo) sigue siendo el mismo, verificado contra el warehouse
    # real tras la migracion.
    conn = _connect_or_skip()
    row = conn.execute(
        "SELECT respaldo_evidencia FROM conflict WHERE conflict_id = 'conflict:12809d506a1f7335ee42fc4d'"
    ).fetchone()
    conn.close()
    assert row is not None, "el caso Museo debe estar presente en el warehouse (post-migracion v3.3)"
    assert row[0] == "sin_respaldo_exact_quote_detectado"


def test_aeropuerto_los_cerrillos_current_fix1a_state():
    """Bug real que la validacion N=150 encontro: n_case_ids>1 (revision
    humana de los 63) NO garantiza que el conflicto este bien construido.
    Este test no afirma que la fusion quedo corregida (eso es Fix 1B) --
    solo que la regla de respaldo se aplico sin excepcion automatica. El
    resultado empírico publicado de Fix 1A se fija explícitamente aquí para
    que una reconstrucción silenciosa del warehouse no pueda cambiarlo sin
    hacer fallar la regresión.

    [ACTUALIZADO Fix 1D, 2026-09-24] n_backing subio de 1 a 4: la mencion
    'Ciudad Portal Bicentenario' de este conflicto ahora esta cubierta por
    v3.3 (detector_version='v3_3_verified_index'), que la ancla a UN
    case_mention_id real -- pero ese case_mention tiene 4 citas 'objeto'
    verificadas distintas (evidence_id ...:objeto:0 a ...:objeto:3), y el
    diseno registra 1 fila de provenance por cada (case_mention, evidencia)
    -- mismo grano que ya usaba el detector exact_substring_v1 original.
    Verificado a mano contra el warehouse real, no es una regresion.

    [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] conflict_id
    cambio (mismo motivo que el caso Museo: nombres re-extraidos por una
    corrida LLM distinta cambian el project_id/case_id derivado). n_backing
    se mantiene en 4 (mismo case_mention, misma evidencia), pero n_case_ids
    bajo de 2 a 1: el segundo case_id que hacia este conflicto multi-caso
    (un proyecto de Cerrillos separado) ya no se fusiona con Portal
    Bicentenario en el registro de proyectos v3.3 -- verificado que ningun
    proyecto llamado 'Aeropuerto Los Cerrillos' aparece ya en el registro.
    El punto original del test (el detector se aplica sin excepcion
    automatica por n_case_ids) sigue siendo verdad POR CONSTRUCCION del
    codigo (_project_backing_evidence no bifurca por n_case_ids en ningun
    punto) -- este caso puntual dejo de ser multi-caso, no vuelve a probar
    esa propiedad, pero tampoco la contradice.

    [ACTUALIZADO 2026-09-28, resolucion de los 15 IDs historicos + 17 merges
    de identidad] conflict_id volvio a cambiar: antes de esta ronda,
    'Ciudad Portal Bicentenario' (08960f92...) tenia case_id fusionado a
    96d6e7e0... (otro miembro del grupo); tras re-ejecutar resolve_project_review.py
    con las nuevas decisiones, el case_id 'ganador' del mismo grupo de
    fusion cambio a 08960f92... (el propio project_id). n_case_ids,
    respaldo_evidencia y n_backing se verificaron sin cambios (1, exact_quote,
    4) -- solo el hash derivado del case_id cambio, no la sustancia."""
    conn = _connect_or_skip()
    row = conn.execute(
        "SELECT n_case_ids, respaldo_evidencia, "
        "(SELECT COUNT(*) FROM conflict_evidence_backing b "
        "WHERE b.conflict_id = c.conflict_id) AS n_backing "
        "FROM conflict c WHERE c.conflict_id = 'conflict:972023b05988e3bcf74f7fb1'"
    ).fetchone()
    conn.close()
    assert row is not None, "el caso Aeropuerto/Portal Bicentenario debe estar presente en el warehouse (post-migracion v3.3)"
    n_case_ids, respaldo, n_backing = row
    assert n_case_ids == 1
    assert respaldo == "respaldo_exact_quote_detectado"
    assert n_backing == 4


def test_hospital_ochagavia_pac_document_no_longer_focal():
    """Fix 1B (2026-09-22): adjudicacion de uno de los 4 desacuerdos reales
    de conflictos_distintos_fusionados. El documento 'Pedro Aguirre Cerda
    toma medidas...' estaba clasificado con nombre_proyecto='Nucleo
    Ochagavia' pero su contenido real es sobre anteproyectos genericos de
    altura, sin vinculo con la reconversion especifica del sitio -- eso lo
    hacia aparecer como evidencia focal (verificada) del conflicto Hospital
    Ochagavia/Nucleo Ochagavia. Se corrigio con correccion_nombre_proyecto=''
    (document_case_unit), protegido con tiene_error=1 explicito.

    La union de case_id en CONFLICT se mantiene intacta a proposito (no se
    convirtio en Fix 1B una separacion automatica): su documento fundador
    ('El espacio y la memoria...') es coherente por si solo -- un mismo
    inmueble, una sola trayectoria (hospital -> reconversion comercial).
    Separar los case_id no habria resuelto el problema real, solo lo habria
    desplazado a la etiqueta 'Nucleo Ochagavia'. La correccion real de
    nombre_proyecto pertenece a Fix 1C (clasificador aguas arriba), no a
    esta capa."""
    conn = _connect_or_skip()
    doc_role = conn.execute(
        "SELECT role, unidad_caso_tipo FROM document_conflict "
        "WHERE document_id = 'ad078a77f1ebd1d1938316d5103acadf10d9455f2799a414ba8af2d190df0342'"
    ).fetchone()
    conflict_row = conn.execute(
        "SELECT n_case_ids, label FROM conflict WHERE conflict_id = 'conflict:df81347c6c222b0f5a06c44c'"
    ).fetchone()
    conn.close()
    assert doc_role is not None, "el documento debe seguir presente en el warehouse"
    assert doc_role[0] == "mentioned_unreviewed", "ya no debe contar como evidencia focal/verificada"
    assert conflict_row is not None, "el conflicto Hospital Ochagavia debe seguir existiendo"
    assert conflict_row[0] == 2  # la union de case_id se mantiene intacta a proposito
    assert conflict_row[1] == "Hospital Ochagavía"


def test_fix_1c_audit_completo_documentos_ya_no_focal():
    """Fix 1C (2026-09-23): auditoria completa de los 128 candidatos de mayor
    riesgo (cero solapamiento de palabras clave entre nombre_proyecto y las
    citas de evidencia) que quedaron sin revisar tras el cierre inicial de
    Fix 1C. Se revisaron los 128 (antes solo ~30) via 3 subagentes en
    paralelo + verificacion manual propia de cada 'posible_error'. De los
    128, 123 resultaron bien fundados (el nombre si corresponde al objeto
    real, solo que la confirmacion vive en el titulo, en un documento
    hermano, o en una cita no capturada por el filtro automatico), 1 quedo
    no_concluyente (documento unico, ambiguo, no accionable), y 4 resultaron
    ser el mismo patron que Hospital Ochagavia: el nombre_proyecto viene de
    una case_mention EXCLUIDA o de una referencia retorica/periferica,
    mientras la case_mention realmente INCLUIDA describe un objeto distinto.
    Los 4 se corrigieron igual que Ochagavia: correccion_nombre_proyecto=''
    protegido con tiene_error=1.

    [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] Verificado
    empiricamente (no asumido): v3.3 es una corrida LLM separada de v3.2 y
    en 146/934 documentos extrajo MENOS proyectos_mencionados que v3.2 (vs.
    68/934 con mas) -- una diferencia real de contenido entre modelos, no un
    bug de esta migracion. Para 2 de los 4 documentos de este test ('Templo
    votivo', 'Liceo Reino de Dinamarca') la mencion completa desaparecio de
    proyectos_mencionados en v3.3 (confirmado leyendo el JSONL real) -- ya
    no generan NINGUNA fila en document_conflict, ni siquiera
    'mentioned_unreviewed'. Es una version aun mas fuerte de "ya no cuenta
    como evidencia focal" que la que el Fix 1C original corrigio a mano, asi
    que no contradice el hallazgo -- pero cambia la aserción verificable.
    Los otros 2 ('Hotel Sheraton San Cristóbal', 'casona de calle Huérfanos')
    si conservaron la mencion y siguen en 'mentioned_unreviewed' como
    antes."""
    conn = _connect_or_skip()
    docs_mencion_desaparecida = [
        "5d2f0680d21e1061790de468589132de52ff9cffd576ecee2fb4c0ad6b070f47",  # "Templo votivo"
        "2cb01a7a9e863f52c401b8f98df2af848a01c9b2d3354ee8dcc3a22554714db2",  # "Liceo Reino de Dinamarca"
    ]
    docs_mencion_conservada = [
        "b243ca1d3dd9948c4e15a7f8c41da3b3f10730236af8714d62cf942a16712523",  # "Hotel Sheraton San Cristóbal"
        "fb31947ee71b5386e1bcde4fa1b37570a867232120537d317dfdf5ad52249b76",  # "casona de calle Huérfanos"
    ]
    for doc_id in docs_mencion_desaparecida:
        row = conn.execute(
            "SELECT role FROM document_conflict WHERE document_id = ?", (doc_id,)
        ).fetchone()
        assert row is None, f"{doc_id}: v3.3 elimino la mencion, no debe generar document_conflict"
    for doc_id in docs_mencion_conservada:
        row = conn.execute(
            "SELECT role FROM document_conflict WHERE document_id = ?", (doc_id,)
        ).fetchone()
        assert row is not None, f"el documento {doc_id} debe seguir presente en el warehouse"
        assert row[0] == "mentioned_unreviewed", f"{doc_id} ya no debe contar como evidencia focal/verificada"
    conn.close()


def test_fix_1c_project_case_mention_cross_check_documentos_ya_no_focal():
    """Fix 1C, cross-check con project_case_mention.py (2026-09-23): el metodo
    de solapamiento de palabras clave (patron 2 de Fix 1C) audito los 204
    candidatos completos (Tier A 128/128 + Tier B 76/76) sin encontrar casos
    nuevos en el Tier B. Un segundo metodo, complementario, usa el modulo
    experimental src/project_case_mention.py para vincular cada mencion de
    proyecto con la case_mention especifica (no solo el documento) que
    respalda su nombre. Aplicado a los 552 documentos focales, encontro 6
    casos reales mas donde el nombre_proyecto viene de una case_mention
    EXCLUIDA mientras la case_mention INCLUIDA describe un objeto distinto --
    exactamente el patron de Hospital Ochagavia, pero invisibles al metodo de
    solapamiento de palabras clave porque comparten alguna palabra con la
    evidencia real (ej. 'edificio', 'proyecto').

    Uno de estos 6 ('edificio de 17 pisos... Americo Vespucio 7550') habia
    sido marcado bien_fundado en una revision manual rapida previa -- este
    cross-check mas preciso revirtio ese veredicto. Corregidos igual que los
    casos previos: correccion_nombre_proyecto='' protegido con tiene_error=1."""
    conn = _connect_or_skip()
    docs = [
        "290718bbd0ad42bc30f57690d53d3672796ca4d9456143d72be6b1611db68dc2",  # "Solucion Sanitaria para un sector de Quilicura"
        "42c8b7e00822408d333117960962a4ac9a5fb982220ccba0e343973fbd499178",  # "proyecto Avda. Vespucio con Renato Sanchez Fontecilla y Asturias"
        "55dae700063cebc780630f0ed7e15fb33ee8a59bfb8c84c1577739c937265e6e",  # "edificio de la estrecha calle Santa Petronila"
        "644d3dd05d9fceb5383b9dfcd7da46e9849d586222b581702ab8518997d718f2",  # "Alameda 4499"
        "8f0dc37c09c989b600716d65dd413da217335b3c496c7eeec80f86b59cae2e1b",  # "edificio de 17 pisos... Americo Vespucio 7550"
        "f491365929e87b322139b7a7b75d8b6933ac1e18dc1a9a60db0205d4fa0b6ccd",  # "Portal Bicentenario"
    ]
    for doc_id in docs:
        row = conn.execute(
            "SELECT role FROM document_conflict WHERE document_id = ?", (doc_id,)
        ).fetchone()
        assert row is not None, f"el documento {doc_id} debe seguir presente en el warehouse"
        assert row[0] == "mentioned_unreviewed", f"{doc_id} ya no debe contar como evidencia focal/verificada"
    conn.close()


def test_fix_1c_ronda_4_ivo_gasic_vespucio_oriente_ya_no_focal():
    """Fix 1C, ronda 4 (2026-09-23): la revision AI-assisted del enriquecimiento
    N=150 (ejecutada por Luna/Codex, verificada por Claude Sonnet 5 contra el
    SQL real) marco como error_grave la entrevista a Ivo Gasic (Revista
    Planeo) por tener nombre_proyecto='Autopista Vespucio Oriente (AVO)'. La
    verificacion confirmo el mismo patron que Hospital Ochagavia: la cita
    literal 'Autopista Vespucio Oriente' solo existe en case_mention:4,
    EXCLUIDA; las case_mention incluidas (0,1,2) tratan de la lucha del MPL
    por vivienda social y contra el Plan Regulador Comunal de Penalolen (canal
    Las Perdices, Lo Hermida, conjunto habitacional de 120 familias) --
    Vespucio Oriente aparece solo de pasada en una entrevista panoramica.
    Corregido igual que los casos previos: correccion_nombre_proyecto=''
    protegido con tiene_error=1.

    De los otros 6 error_grave de la misma revision N=150, 2 coincidian
    exactamente con documentos ya corregidos en la ronda 3 (Portal
    Bicentenario, Americo Vespucio 7550) -- confirmacion cruzada
    independiente real, sin necesidad de correccion adicional. El desacuerdo
    de severidad sobre el caso Ex-Ante/FIMA se adjudico a error_menor (la
    case_mention focal SI tiene evidencia objeto real de 'Edificio
    Pajaritos'); los 3 restantes no estan en role focal/co_focal en ningun
    conflicto y quedan documentados como limitacion de calidad de
    enriquecimiento, no corregidos individualmente."""
    conn = _connect_or_skip()
    row = conn.execute(
        "SELECT role FROM document_conflict WHERE document_id = ?",
        ("9c71d8a489c1f04aae08dd95bf6044086528dd80e38a5621b979e12ee43140f7",),
    ).fetchone()
    conn.close()
    assert row is not None, "el documento debe seguir presente en el warehouse"
    assert row[0] == "mentioned_unreviewed", "ya no debe contar como evidencia focal/verificada"


def test_backing_rows_declare_document_level_scope_and_ambiguity_columns():
    """Fix 1D: ademas del scope documental original (exact_substring_v1),
    ahora tambien es valido el scope a nivel de mencion verificada por v3.3
    -- ambos son los UNICOS 2 valores esperados, nunca un typo nuevo."""
    conn = _connect_or_skip()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(conflict_evidence_backing)")}
    assert {
        "backing_scope",
        "document_case_mention_count",
        "document_object_case_mention_count",
        "ambiguous_multi_case_document",
        "detector_version",
    } <= columns
    valid_scopes = {"document_level_case_mention_without_project_link", "mention_level_verified_index"}
    bad_scope = conn.execute(
        "SELECT COUNT(*) FROM conflict_evidence_backing WHERE backing_scope NOT IN (%s)"
        % ",".join("?" * len(valid_scopes)),
        list(valid_scopes),
    ).fetchone()[0]
    v3_3_rows_have_correct_scope = conn.execute(
        "SELECT COUNT(*) FROM conflict_evidence_backing "
        "WHERE detector_version = 'v3_3_verified_index' AND backing_scope != 'mention_level_verified_index'"
    ).fetchone()[0]
    conn.close()
    assert bad_scope == 0
    assert v3_3_rows_have_correct_scope == 0


# [RETIRADO 2026-09-26, migracion v3.2->v3.3 completa] Los tests
# test_load_v3_3_verified_links_excludes_out_of_universe_url_and_parses_real_data
# y test_load_v3_3_verified_links_aborts_on_classifications_sha256_mismatch
# ejercitaban la version vieja de load_v3_3_verified_links() que releia los
# 3 JSONL crudos de v3.3 y traducia por URL (Fix 1D, 2026-09-24). Esa
# funcion se reescribio para consultar enrichment_project_mention
# directamente (ver su docstring actual) -- ya no toma argumentos de
# archivo, ya no indexa por URL, y el guard de sha256 de
# classifications.jsonl se movio a src/v3_3_enrichment_source.py (ver
# tests/test_v3_3_enrichment_source.py), porque ese guard solo hace falta
# al traducir case_mention_index->case_mention_id en el ETL (build_
# enrichment_tables.py), no al leer un valor ya materializado en el
# warehouse. Reemplazados por los 2 tests de abajo, que ejercitan la
# funcion nueva contra el warehouse real.


def test_load_v3_3_verified_links_reads_from_warehouse_table():
    conn = _connect_or_skip()
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='enrichment_project_mention'"
    ).fetchone()
    if not has_table:
        conn.close()
        import pytest

        pytest.skip("enrichment_project_mention no existe en este entorno (build_enrichment_tables.py no corrio)")
    links = reg.load_v3_3_verified_links(conn)
    conn.close()
    assert len(links) > 0
    # al menos una entrada real con indice no nulo y una con null deben existir
    assert any(idx is not None for idx in links.values())
    assert any(idx is None for idx in links.values())


def test_load_v3_3_verified_links_keys_are_normalized_document_id_name_pairs():
    conn = _connect_or_skip()
    has_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='enrichment_project_mention'"
    ).fetchone()
    if not has_table:
        conn.close()
        import pytest

        pytest.skip("enrichment_project_mention no existe en este entorno")
    row = conn.execute(
        "SELECT document_id, nombre_proyecto FROM enrichment_project_mention WHERE nombre_proyecto != '' LIMIT 1"
    ).fetchone()
    links = reg.load_v3_3_verified_links(conn)
    conn.close()
    if row:
        document_id, nombre_proyecto = row
        assert (document_id, reg._norm(nombre_proyecto)) in links


def test_backing_report_count_matches_persisted_rows():
    import json
    from pathlib import Path

    conn = _connect_or_skip()
    persisted = conn.execute("SELECT COUNT(*) FROM conflict_evidence_backing").fetchone()[0]
    conn.close()
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "audit" / "conflict_evidence_backing_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["backing_rows_persisted"] == persisted
    assert report["backing_rows_deduplicated"] == (
        report["backing_rows_detected_raw"] - report["backing_rows_persisted"]
    )


def test_document_conflict_case_safe_view_only_includes_caso_unico():
    conn = _connect_or_skip()
    bad = conn.execute(
        "SELECT COUNT(*) FROM document_conflict_case_safe WHERE unidad_caso_tipo != 'caso_unico'"
    ).fetchone()[0]
    n_safe = conn.execute("SELECT COUNT(*) FROM document_conflict_case_safe").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM document_conflict").fetchone()[0]
    conn.close()
    assert bad == 0
    assert 0 < n_safe <= n_total


# --- adjudicacion humana de elegibilidad (2026-09-29) ---


def _eligibility_db(decision="uncertain", quote="cita de objeto"):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE case_mention (case_mention_id TEXT PRIMARY KEY, document_id TEXT, decision_final_amplio TEXT)")
    conn.execute(
        "CREATE TABLE evidence (evidence_id TEXT PRIMARY KEY, case_mention_id TEXT, quote_role TEXT, quote_text TEXT, verified INTEGER)"
    )
    conn.execute("INSERT INTO case_mention VALUES ('d1:0', 'd1', ?)", (decision,))
    conn.execute("INSERT INTO evidence VALUES ('d1:0:objeto:0', 'd1:0', 'objeto', ?, 1)", (quote,))
    return conn


def _write_eligibility(tmp_path, **overrides):
    entry = {
        "case_mention_id": "d1:0",
        "original_decision_final_amplio": "uncertain",
        "adjudicated_decision": "include",
        "rationale": "porque si",
        "evidence": [{"evidence_id": "d1:0:objeto:0", "quote": "cita de objeto"}],
    }
    entry.update(overrides)
    path = tmp_path / "elig.json"
    path.write_text(json.dumps({"schema_version": "case_mention_eligibility_adjudications_v1", "adjudications": [entry]}), encoding="utf-8")
    return path


def test_eligibility_adjudication_loads_when_it_matches_the_warehouse(tmp_path):
    result = reg.load_case_mention_eligibility_adjudications(_eligibility_db(), _write_eligibility(tmp_path))
    assert list(result) == ["d1:0"]


def test_eligibility_adjudication_fails_closed_on_stale_decision_or_quote(tmp_path):
    with pytest.raises(ValueError, match="esperaba"):
        reg.load_case_mention_eligibility_adjudications(_eligibility_db(decision="exclude"), _write_eligibility(tmp_path))
    with pytest.raises(ValueError, match="no coincide"):
        reg.load_case_mention_eligibility_adjudications(_eligibility_db(quote="otra cita"), _write_eligibility(tmp_path))
    with pytest.raises(ValueError, match="inexistente"):
        reg.load_case_mention_eligibility_adjudications(_eligibility_db(), _write_eligibility(tmp_path, case_mention_id="d9:0"))
    with pytest.raises(ValueError, match="incompleta"):
        reg.load_case_mention_eligibility_adjudications(_eligibility_db(), _write_eligibility(tmp_path, rationale=""))


def test_adjudicated_case_mention_backs_a_project_only_with_a_distinct_match_method():
    mentions = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Edificio X"}]}
    objeto = {"d1:0": [{"evidence_id": "d1:0:objeto:0", "quote_text": "cita"}]}
    links = {("d1", reg._norm("Edificio X")): 0}
    sin = reg._project_backing_evidence("p1", mentions, {"d1": []}, objeto, links)
    assert sin == []
    con = reg._project_backing_evidence("p1", mentions, {"d1": ["d1:0"]}, objeto, links, adjudicated_cms=frozenset({"d1:0"}))
    assert [r["match_method"] for r in con] == [reg.MATCH_METHOD_V3_3_ADJUDICATED_ELIGIBILITY]
    normal = reg._project_backing_evidence("p1", mentions, {"d1": ["d1:0"]}, objeto, links)
    assert [r["match_method"] for r in normal] == [reg.MATCH_METHOD_V3_3]


def test_real_eligibility_adjudications_match_the_warehouse_and_are_the_only_adjudicated_backing():
    conn = _connect_or_skip()
    result = reg.load_case_mention_eligibility_adjudications(conn, reg.CASE_MENTION_ELIGIBILITY_ADJUDICATIONS_PATH)
    assert len(result) == 2
    rows = conn.execute(
        "SELECT DISTINCT case_mention_id FROM conflict_evidence_backing WHERE match_method = ?",
        (reg.MATCH_METHOD_V3_3_ADJUDICATED_ELIGIBILITY,),
    ).fetchall()
    conn.close()
    assert {r[0] for r in rows} == set(result)
