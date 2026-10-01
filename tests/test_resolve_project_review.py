"""Pruebas de la resolucion de la cola de revision de proyectos.

No llaman a ninguna API. Verifican las reglas automaticas (numeral/etapa,
lista de nombres genericos) contra casos reales del corpus, y que las 253
filas reales de la cola quedan todas cubiertas (por regla o por decision
manual explicita) antes de aplicar nada a la base de datos.
"""

import sys
import sqlite3
import hashlib
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import resolve_project_review as rpq  # noqa: E402
import build_projects as bridge  # noqa: E402



def test_conflicting_numeral_blocks_merge():
    assert rpq.has_conflicting_numeral("Alto Las Condes", "Alto Las Condes 2") is True
    assert rpq.has_conflicting_numeral("Distrito Cordillera I", "Distrito Cordillera II") is True
    assert rpq.has_conflicting_numeral("Mall Vivo Santiago Etapa II", "Mall Vivo Santiago") is True


def test_same_numeral_does_not_block_merge():
    assert rpq.has_conflicting_numeral("Alto Las Condes 2", "Mall Alto Las Condes 2") is False
    assert rpq.has_conflicting_numeral("Mall Vivo Santiago Etapa II", "Centro Comercial Mall Vivo Santiago Etapa II") is False


def test_no_numeral_does_not_block_merge():
    assert rpq.has_conflicting_numeral("torre Bellavista", "proyecto Bellavista") is False


def test_generic_blocklist_blocks_merge_with_specific_name():
    assert rpq.is_generic_bare_name("Data Center", "Data Center de Google") is True
    assert rpq.is_generic_bare_name("Vespucio", "Jardines de Vespucio") is True


def test_generic_blocklist_does_not_flag_two_specific_names():
    assert rpq.is_generic_bare_name("torre Bellavista", "proyecto Bellavista") is False


def test_mixed_alto_las_condes_project_cluster_is_not_merged_with_existing_mall():
    # The project_id "Alto Las Condes" currently aggregates five documents:
    # two describe the proposed Alto Las Condes 2 expansion, while others
    # mention the existing mall. A project-level merge would therefore pull
    # the expansion into the existing-mall case. Keep the pair unresolved
    # until project mentions can be split/attributed at finer granularity.
    decision, _ = rpq.classify("Alto Las Condes", "Cenco Alto Las Condes")
    assert decision is None

    # The adjacent proposed expansion remains explicitly distinct.
    expansion_decision, _ = rpq.classify("Alto Las Condes", "Alto Las Condes 2")
    assert expansion_decision is False


def test_portal_la_dehesa_brand_name_is_same_mall_identity():
    decision, reason = rpq.classify("Portal La Dehesa", "Cenco Portal La Dehesa")
    assert decision is True
    assert "La Tercera" in reason
    assert "Infobae" in reason


def test_decision_provenance_is_structured_not_inferred_from_reason_text():
    decision, reason, source, actor = rpq.classify_with_provenance(
        "Portal La Dehesa", "Cenco Portal La Dehesa"
    )
    assert decision is True
    assert "La Tercera" in reason
    assert "Infobae" in reason
    assert source == "manual_adjudication"
    assert actor is None

    decision, _, source, actor = rpq.classify_with_provenance("Data Center", "Data Center en Chile")
    assert decision is False
    assert source == "deterministic_rule"
    assert actor is None

    decision, _, source, actor = rpq.classify_with_provenance("nombre sin regla", "otro")
    assert decision is None
    assert source == "unresolved"
    assert actor is None


def test_exact_project_id_adjudication_wins_and_does_not_leak_by_name():
    adjudications = [
        {
            "project_ids": ["project-a", "project-b"],
            "project_names": {
                "project-a": "Portal La Dehesa",
                "project-b": "Cenco Portal La Dehesa",
            },
            "identity_class": "same_identity",
            "resolver_action": "merge_case",
            "pair_id": "pair-exact",
            "rationale": "same named shopping center",
        },
        {
            "project_ids": ["project-c", "project-d"],
            "project_names": {
                "project-c": "Portal La Dehesa",
                "project-d": "Cenco Portal La Dehesa",
            },
            "identity_class": "unresolved",
            "resolver_action": "no_new_merge",
            "pair_id": "pair-same-names-different-ids",
            "rationale": "the records have different source scope",
        },
    ]

    exact = rpq.classify_project_pair_with_adjudications(
        "project-a", "Portal La Dehesa", "project-b", "Cenco Portal La Dehesa", adjudications
    )
    assert exact == (
        True,
        "same named shopping center",
        rpq.PROJECT_IDENTITY_DECISION_SOURCE,
        None,
    )

    # A name-level rule would merge these names, but a reviewed ID pair with
    # another identity must not transfer its decision to different IDs.
    unresolved = rpq.classify_project_pair_with_adjudications(
        "project-c", "Portal La Dehesa", "project-d", "Cenco Portal La Dehesa", adjudications
    )
    assert unresolved[0] is None
    assert unresolved[2] == rpq.PROJECT_IDENTITY_DECISION_SOURCE

    # An unreviewed ID pair with the same names is also fail-closed once those
    # names have an ID-scoped adjudication; it must not inherit it by text.
    other_ids = rpq.classify_project_pair_with_adjudications(
        "project-x", "Portal La Dehesa", "project-y", "Cenco Portal La Dehesa", adjudications
    )
    assert other_ids[0] is None
    assert other_ids[2] == "reviewed_name_scope_guard"


def test_exact_reviewed_nonidentity_is_persisted_as_kept_separate():
    adjudications = [
        {
            "project_ids": ["site", "component"],
            "project_names": {"site": "Villa San Luis", "component": "Block 14 de Villa San Luis"},
            "identity_class": "parent_component_phase",
            "resolver_action": "no_new_merge",
            "pair_id": "site-component",
            "rationale": "El block 14 es una parte del conjunto, no su alias.",
        }
    ]
    result = rpq.classify_project_pair_with_adjudications(
        "site", "Villa San Luis", "component", "Block 14 de Villa San Luis", adjudications
    )
    assert result == (
        False,
        "El block 14 es una parte del conjunto, no su alias.",
        rpq.PROJECT_IDENTITY_DECISION_SOURCE,
        None,
    )


def test_exact_reviewed_unresolved_pair_stays_pending():
    adjudications = [
        {
            "project_ids": ["a", "b"],
            "project_names": {"a": "Vital Apoquindo", "b": "Vital Apoquindo 25 edificios"},
            "identity_class": "unresolved",
            "resolver_action": "no_new_merge",
            "pair_id": "vital-uncertain",
            "rationale": "El cluster tiene conteos incompatibles y no se resuelve pairwise.",
        }
    ]
    result = rpq.classify_project_pair_with_adjudications(
        "a", "Vital Apoquindo", "b", "Vital Apoquindo 25 edificios", adjudications
    )
    assert result[0] is None
    assert result[2] == rpq.PROJECT_IDENTITY_DECISION_SOURCE


def test_exact_project_id_adjudication_rejects_stale_names():
    adjudications = [
        {
            "project_ids": ["project-a", "project-b"],
            "project_names": {"project-a": "Name A", "project-b": "Name B"},
            "identity_class": "same_identity",
            "resolver_action": "merge_case",
            "pair_id": "pair-exact",
            "rationale": "verified identity",
        }
    ]
    with pytest.raises(ValueError, match="canonical_name mismatch"):
        rpq.classify_project_pair_with_adjudications(
            "project-a", "Renamed A", "project-b", "Name B", adjudications
        )


def test_identity_adjudication_scope_requires_exact_queue_pair_and_names():
    projects = {"p-a": "Project A", "p-b": "Project B"}
    entries = [
        {
            "pair_id": "p-a-b",
            "project_ids": ["p-a", "p-b"],
            "project_names": {"p-a": "Project A", "p-b": "Project B"},
            "identity_class": "same_identity",
            "resolver_action": "merge_case",
            "rationale": "same source-backed identity",
        }
    ]
    rpq.validate_project_identity_adjudication_scope(
        projects, [(7, "p-a", "Project A", "p-b", "Project B")], entries
    )
    with pytest.raises(ValueError, match="absent from project_review_queue"):
        rpq.validate_project_identity_adjudication_scope(
            projects, [(7, "p-a", "Project A", "p-x", "Project X")], entries
        )
    with pytest.raises(ValueError, match="canonical_name mismatch"):
        rpq.validate_project_identity_adjudication_scope(
            {"p-a": "Renamed A", "p-b": "Project B"},
            [(7, "p-a", "Renamed A", "p-b", "Project B")],
            entries,
        )


DECISIONS_PATH = PROJECT_ROOT / "config" / "project_identity_decisions.json"


def _mutated_decisions(tmp_path, mutator):
    payload = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    mutator(payload)
    path = tmp_path / "decisions.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_identity_decisions_file_loads_with_its_declared_counts():
    decisions = rpq.load_project_identity_decisions()
    assert len(decisions) == 95
    assert {
        identity_class: sum(entry["identity_class"] == identity_class for entry in decisions)
        for identity_class in ("same_identity", "parent_component_phase", "distinct_entities",
                               "related_plan_or_instrument", "insufficient_evidence", "unresolved")
    } == {"same_identity": 39, "parent_component_phase": 25, "distinct_entities": 15,
          "related_plan_or_instrument": 14, "insufficient_evidence": 2, "unresolved": 0}
    assert sum(entry["resolver_action"] == "merge_case" for entry in decisions) == 39


def test_identity_decisions_loader_fails_closed_on_tampered_files(tmp_path):
    def bad_canonical(payload):
        next(e for e in payload["decisions"] if e["resolver_action"] == "merge_case")["canonical_project_id"] = "not-a-project-id"

    def duplicated_pair(payload):
        payload["decisions"].append(json.loads(json.dumps(payload["decisions"][0])))
        payload["decisions"][-1]["pair_id"] = "otra-clave"
        payload["counts"]["pairs"] = len(payload["decisions"])

    def wrong_declared_count(payload):
        payload["counts"]["pairs"] += 1

    def wrong_declared_classes(payload):
        payload["counts"]["by_identity_class"]["same_identity"] += 1

    def one_side_only(payload):
        entry = payload["decisions"][0]
        entry["source_evidence"] = [ref for ref in entry["source_evidence"] if ref["side"] == "a"]

    def unknown_cited_reference(payload):
        next(e for e in payload["decisions"] if e.get("cited_evidence_ref_ids"))["cited_evidence_ref_ids"] = ["no-existe"]

    def merge_with_wrong_action(payload):
        next(e for e in payload["decisions"] if e["resolver_action"] == "merge_case")["resolver_action"] = "no_new_merge"

    def no_merge_with_canonical(payload):
        entry = next(e for e in payload["decisions"] if e["resolver_action"] == "no_new_merge")
        entry["canonical_project_id"] = entry["project_ids"][0]

    def missing_rationale(payload):
        payload["decisions"][0]["rationale"] = ""

    for mutator, message in (
        (bad_canonical, "exact canonical_project_id"),
        (duplicated_pair, "duplicate"),
        (wrong_declared_count, "declared pair count"),
        (wrong_declared_classes, "declared class counts"),
        (one_side_only, "each side"),
        (unknown_cited_reference, "does not hold"),
        (merge_with_wrong_action, "merge_case"),
        (no_merge_with_canonical, "must not merge"),
        (missing_rationale, "rationale"),
    ):
        with pytest.raises(ValueError, match=message):
            rpq.load_project_identity_decisions(_mutated_decisions(tmp_path, mutator))


def test_identity_source_evidence_requires_exact_hashes_urls_and_literal_quotes(tmp_path):
    text = "El proyecto verificable se llama Proyecto Alfa, en Ñuñoa."
    record = {"url": "https://example.test/alfa", "text": text}
    raw = json.dumps(record, ensure_ascii=False).encode("utf-8")
    content_dir = tmp_path / "Fuentes" / "fulltext" / "content"
    content_dir.mkdir(parents=True)
    content_path = content_dir / "record.json"
    content_path.write_bytes(raw)
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    record_sha = hashlib.sha256(raw).hexdigest()
    entries = [
        {
            "pair_id": "pair-alfa",
            "project_ids": ["p-a", "p-b"],
            "project_names": {"p-a": "Proyecto Alfa", "p-b": "Proyecto Alfa (Ñuñoa)"},
            "identity_class": "same_identity",
            "resolver_action": "merge_case",
            "rationale": "La mención literal identifica el mismo proyecto.",
            "source_evidence": [
                {
                    "side": "a",
                    "project_id": "p-a",
                    "project_name": "Proyecto Alfa",
                    "document_id": text_sha,
                    "url": "https://example.test/alfa",
                    "raw_project_mention": "Proyecto Alfa",
                    "content_file": "Fuentes/fulltext/content/record.json",
                    "source_text_sha256": text_sha,
                    "content_record_sha256": record_sha,
                    "evidence_status": "literal_anchor_verified",
                    "quote": "Proyecto Alfa",
                    "matched_fragment": "Proyecto Alfa",
                }
            ],
        }
    ]

    summary = rpq.validate_project_identity_adjudication_evidence(entries, tmp_path)
    assert summary["valid_references"] == 1

    bad = json.loads(json.dumps(entries))
    bad[0]["source_evidence"][0]["quote"] = "Texto que no está en el artículo"
    with pytest.raises(ValueError, match="quote no es substring literal"):
        rpq.validate_project_identity_adjudication_evidence(bad, tmp_path)


def test_no_new_merge_cannot_be_reconnected_transitively():
    baseline = {"p-a": "p-a", "p-b": "p-b", "p-c": "p-c"}
    plan = rpq.ResolutionPlan(
        project_to_case={"p-a": "p-a", "p-b": "p-a", "p-c": "p-a"},
        row_decisions={},
        homonym_vetoes=0,
    )
    entries = [
        {
            "pair_id": "pair-a-c",
            "project_ids": ["p-a", "p-c"],
            "identity_class": "unresolved",
            "resolver_action": "no_new_merge",
            "rationale": "No compartir grupo automáticamente.",
        }
    ]
    with pytest.raises(ValueError, match="no_new_merge pair became connected"):
        rpq.validate_project_identity_adjudication_topology(
            plan.project_to_case, baseline, entries
        )


def test_no_new_merge_topology_accepts_unchanged_baseline_members():
    baseline = {"p-a": "p-a", "p-b": "p-a"}
    plan = rpq.ResolutionPlan(
        project_to_case={"p-a": "p-a", "p-b": "p-a"},
        row_decisions={},
        homonym_vetoes=0,
    )
    entries = [
        {
            "pair_id": "pair-a-b",
            "project_ids": ["p-a", "p-b"],
            "project_names": {"p-a": "Project A", "p-b": "Project B"},
            "identity_class": "unresolved",
            "resolver_action": "no_new_merge",
            "rationale": "El baseline ya los agrupaba antes de esta auditoría.",
        }
    ]
    assert rpq.validate_project_identity_adjudication_topology(
        plan.project_to_case, baseline, entries
    ) == {"checked": 1, "transitive_reconnections": 0}


def test_source_adjudications_are_exactly_keyed_and_have_structured_evidence_refs():
    pairs = [
        ("Portal La Dehesa", "Cenco Portal La Dehesa"),
        ("Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)", "Centro Nacional de Arte Contemporáneo Cerrillos"),
        ("Flor del Valle", "proyecto de condominio de viviendas sociales Flor del Valle"),
        ("Línea 3 de Metro", "Línea 3 del Metro de Santiago"),
        ("Línea 3 de Metro", "nueva Línea 3 del Metro"),
        ("San Nicolás", "proyecto inmobiliario San Nicolás"),
        ("Supermercado Líder San Francisco", "supermercado Líder San Francisco de Walmart Chile"),
        ("Torres Alameda", "tres torres Alameda"),
        ("block 14 de la Villa San Luis", "block 14"),
        ("edificio de la UNCTAD III (hoy GAM)", "edificio UNCTAD III"),
    ]
    assert len(pairs) == len(set(pairs))
    assert set(pairs) == set(rpq.MANUAL_DECISION_EVIDENCE)
    for a, b in pairs:
        decision, _, source, actor = rpq.classify_with_provenance(a, b)
        ref = rpq.decision_provenance_ref(a, b, source)
        assert decision is True
        assert source == "manual_adjudication"
        assert actor is None
        payload = json.loads(ref)
        assert payload["source"] == "manual_adjudication"
        assert len(payload["references"]) >= 2
        for evidence in payload["references"]:
            assert evidence["source_text_sha256"] == evidence["document_id"]
            assert evidence["content_record_sha256"]
            assert evidence["quote"]


def test_manual_evidence_bundle_has_fixed_complete_pair_set():
    assert set(rpq.MANUAL_DECISION_EVIDENCE) == set(rpq.REQUIRED_SOURCE_BACKED_MANUAL_PAIRS)
    assert all(rpq.MANUAL_DECISIONS[pair][0] is True for pair in rpq.REQUIRED_SOURCE_BACKED_MANUAL_PAIRS)


def test_case_component_roots_are_order_independent_and_preserve_registered_ids():
    projects = {"p-z": "Z", "p-a": "A", "p-m": "M", "p-b": "B"}
    rows = [
        (1, "p-z", "Z", "p-a", "A"),
        (2, "p-m", "M", "p-b", "B"),
    ]
    decisions = {
        frozenset(("Z", "A")): (True, "same", "manual_adjudication", None),
        frozenset(("M", "B")): (True, "same", "manual_adjudication", None),
    }

    def classify_pair(name_a, name_b):
        return decisions[frozenset((name_a, name_b))]

    forward = rpq.resolve_case_components(
        projects, rows, {}, {"p-z": "p-z", "p-a": "p-a", "p-m": "p-m", "p-b": "p-b"}, classify_pair
    )
    reverse = rpq.resolve_case_components(
        projects, list(reversed(rows)), {}, {"p-z": "p-z", "p-a": "p-a", "p-m": "p-m", "p-b": "p-b"}, classify_pair
    )
    assert forward.project_to_case == reverse.project_to_case
    assert forward.project_to_case == {"p-z": "p-a", "p-a": "p-a", "p-m": "p-b", "p-b": "p-b"}


def test_transitive_merge_cannot_violate_explicit_kept_separate():
    projects = {"a": "A", "b": "B", "c": "C"}
    rows = [(1, "a", "A", "b", "B"), (2, "b", "B", "c", "C"), (3, "a", "A", "c", "C")]
    decisions = {
        frozenset(("A", "B")): (True, "merge", "manual_adjudication", None),
        frozenset(("B", "C")): (True, "merge", "manual_adjudication", None),
        frozenset(("A", "C")): (False, "do not merge", "manual_adjudication", None),
    }
    try:
        rpq.resolve_case_components(projects, rows, {}, {p: p for p in projects}, lambda a, b: decisions[frozenset((a, b))])
    except ValueError as exc:
        assert "kept_separate" in str(exc)
    else:
        raise AssertionError("merge transitivo contradijo una decision explicitamente separada")


def test_review_queue_preflight_rejects_missing_or_mismatched_project_names():
    projects = {"p1": "Proyecto uno", "p2": "Proyecto dos"}
    with pytest.raises(ValueError, match="missing project_id"):
        rpq.validate_review_queue_rows(projects, [(1, "p1", "Proyecto uno", "missing", "Otro")])
    with pytest.raises(ValueError, match="canonical_name mismatch"):
        rpq.validate_review_queue_rows(projects, [(1, "p1", "Nombre viejo", "p2", "Proyecto dos")])


def test_atomic_resolution_rolls_back_mutations_on_late_error():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE state (value TEXT)")
    conn.execute("INSERT INTO state VALUES ('before')")

    def failing_operation(connection):
        connection.execute("UPDATE state SET value='partial'")
        raise RuntimeError("late validation failed")

    with pytest.raises(RuntimeError, match="late validation failed"):
        rpq.run_atomically(conn, failing_operation)
    assert conn.execute("SELECT value FROM state").fetchone()[0] == "before"
    conn.close()


def test_main_holds_immediate_transaction_across_preflight_and_resolution(tmp_path, monkeypatch):
    db_path = tmp_path / "warehouse.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE state (value TEXT)")
    conn.execute("INSERT INTO state VALUES ('before')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(rpq, "WAREHOUSE", db_path)
    monkeypatch.setattr(rpq, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rpq, "validate_initial_baseline_source", lambda *_args, **_kwargs: True)

    def preflight(connection, project_root):
        assert project_root == tmp_path
        assert connection.in_transaction
        assert connection.execute("SELECT value FROM state").fetchone()[0] == "before"
        return {"pairs": 10, "references": 20, "literal_raw_mentions": 20, "nonliteral_raw_mentions": []}

    def resolve(connection):
        assert connection.in_transaction
        connection.execute("UPDATE state SET value='after'")
        return 0

    monkeypatch.setattr(rpq, "validate_manual_decision_evidence", preflight)
    monkeypatch.setattr(rpq, "_resolve_database", resolve)
    assert rpq.main() == 0
    check = sqlite3.connect(db_path)
    assert check.execute("SELECT value FROM state").fetchone()[0] == "after"
    check.close()


def _project_warehouse(path, names=("A", "B")):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE project (project_id TEXT, canonical_name TEXT)")
    conn.execute("CREATE TABLE project_mention_resolved (mention_id TEXT, project_id TEXT)")
    for i, name in enumerate(names):
        conn.execute("INSERT INTO project VALUES (?, ?)", (f"p{i}", name))
        conn.execute("INSERT INTO project_mention_resolved VALUES (?, ?)", (f"m{i}", f"p{i}"))
    conn.commit()
    return conn


def test_initial_baseline_content_is_checked_once_and_skipped_after_alias_table_exists(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    conn = _project_warehouse(db_path)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"schema_version": "project_case_baseline",
                    "source_content_sha256": rpq.project_source_content_sha256(conn)}),
        encoding="utf-8",
    )
    assert rpq.validate_initial_baseline_source(conn, baseline_path) is True

    # La huella es de CONTENIDO: reordenar el almacenamiento fisico (VACUUM, otro orden de insercion) no la altera.
    conn.execute("VACUUM")
    reordered = _project_warehouse(tmp_path / "reordered.sqlite", names=("A", "B"))
    assert rpq.validate_initial_baseline_source(reordered, baseline_path) is True
    reordered.close()

    # Un dato distinto SI la altera.
    changed = _project_warehouse(tmp_path / "changed.sqlite", names=("A", "otro"))
    with pytest.raises(ValueError, match="source_content_sha256 no coincide"):
        rpq.validate_initial_baseline_source(changed, baseline_path)
    changed.close()

    conn.execute("CREATE TABLE case_id_alias (old_case_id TEXT)")
    assert rpq.validate_initial_baseline_source(conn, baseline_path) is False
    conn.close()


def test_initial_baseline_rejects_a_malformed_hash(tmp_path):
    conn = _project_warehouse(tmp_path / "w.sqlite")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"schema_version": "project_case_baseline", "source_content_sha256": "zz"}), encoding="utf-8")
    with pytest.raises(ValueError, match="64 caracteres"):
        rpq.validate_initial_baseline_source(conn, baseline_path)
    conn.close()


def test_manual_decision_source_provenance_discloses_not_checking_structured_evidence_rows():
    decision, _, source, _ = rpq.classify_with_provenance("Portal La Dehesa", "Cenco Portal La Dehesa")
    payload = json.loads(rpq.decision_provenance_ref("Portal La Dehesa", "Cenco Portal La Dehesa", source))
    assert decision is True
    assert payload["validation_scope"] == "source_text_quote_and_project_mention_not_structured_evidence_row"
    assert payload["structured_evidence_row_checked"] is False


def test_manual_decision_evidence_validator_checks_project_url_hash_and_literal_quote(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE project (project_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL);
        CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT NOT NULL);
        CREATE TABLE project_mention_resolved (
            document_id TEXT NOT NULL, project_id TEXT NOT NULL, raw_nombre_proyecto TEXT NOT NULL
        );
        """
    )
    source_text = "El proyecto es Portal La Dehesa y también Cenco Portal La Dehesa."
    document_id = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    source_url = "https://example.test/source"
    content_file = tmp_path / "Fuentes" / "fulltext" / "content" / "source.json"
    content_file.parent.mkdir(parents=True)
    content_file.write_text(
        json.dumps({"url": source_url, "text": source_text}, ensure_ascii=False), encoding="utf-8"
    )
    record_sha256 = hashlib.sha256(content_file.read_bytes()).hexdigest()
    conn.executemany(
        "INSERT INTO project VALUES (?,?)",
        [
            ("p1", "Portal La Dehesa"),
            ("p2", "Cenco Portal La Dehesa"),
        ],
    )
    conn.execute("INSERT INTO document VALUES (?,?)", (document_id, source_url))
    conn.executemany(
        "INSERT INTO project_mention_resolved VALUES (?,?,?)",
        [(document_id, "p1", "Portal La Dehesa"), (document_id, "p2", "Cenco Portal La Dehesa")],
    )
    refs = {
        ("Portal La Dehesa", "Cenco Portal La Dehesa"): {
            "source": "manual_adjudication",
            "references": [
                {
                    "project_id": "p1",
                    "project_name": "Portal La Dehesa",
                    "raw_mention": "Portal La Dehesa",
                    "document_id": document_id,
                    "url": source_url,
                    "content_file": "Fuentes/fulltext/content/source.json",
                    "source_text_sha256": document_id,
                    "content_record_sha256": record_sha256,
                    "quote": "Portal La Dehesa",
                },
                {
                    "project_id": "p2",
                    "project_name": "Cenco Portal La Dehesa",
                    "raw_mention": "Cenco Portal La Dehesa",
                    "document_id": document_id,
                    "url": source_url,
                    "content_file": "Fuentes/fulltext/content/source.json",
                    "source_text_sha256": document_id,
                    "content_record_sha256": record_sha256,
                    "quote": "Cenco Portal La Dehesa",
                },
            ],
        }
    }

    rpq.validate_manual_decision_evidence(conn, tmp_path, refs)

    refs[("Portal La Dehesa", "Cenco Portal La Dehesa")]["references"][1]["quote"] = "Cenco Portals"
    with pytest.raises(ValueError, match="quote no es substring literal"):
        rpq.validate_manual_decision_evidence(conn, tmp_path, refs)
    refs[("Portal La Dehesa", "Cenco Portal La Dehesa")]["references"][1]["quote"] = "Cenco Portal La Dehesa"
    refs[("Portal La Dehesa", "Cenco Portal La Dehesa")]["references"][1]["content_file"] = "../outside.json"
    with pytest.raises(ValueError, match="queda fuera de Fuentes/fulltext/content"):
        rpq.validate_manual_decision_evidence(conn, tmp_path, refs)
    conn.close()


def test_no_duplicate_keys_in_manual_decisions():
    """Hallazgo real de la revisión (segunda auditoria, 2026-09-18): las 31 correcciones
    se habian agregado al final del diccionario para 'sobrescribir' la decision
    anterior via el ultimo-valor-gana de Python -- dejaba 24 claves duplicadas
    en el codigo fuente, confuso para cualquiera que lo lea despues. Se
    eliminaron las 24 entradas viejas (stale), dejando solo la version
    corregida. Este test evita que vuelva a pasar."""
    import ast

    src = Path(rpq.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MANUAL_DECISIONS":
            keys = [tuple(ast.literal_eval(elt) for elt in k.elts) for k in node.value.keys]
            assert len(keys) == len(set(keys)), "hay claves duplicadas en MANUAL_DECISIONS"
            return
    raise AssertionError("no se encontro la definicion de MANUAL_DECISIONS")


def test_cencosud_argentina_san_isidro_kept_separate_from_chilean_ones():
    """Tras la correccion completa de la revisión sobre los 934 documentos, el
    documento de Cencosud en Argentina paso a mencionar 'Proyecto de
    Cencosud en San Isidro' en vez de 'Costanera Center' -- genera 2 pares
    nuevos en la cola contra los 2 'San Isidro' chilenos ya conocidos
    (Toro Mazotte/Estacion Central y Quilicura). Ninguno debe fusionarse:
    San Isidro, Buenos Aires (Argentina) no tiene relacion con ninguno."""
    d1, r1 = rpq.classify("Proyecto de Cencosud en San Isidro", "San Isidro")
    d2, r2 = rpq.classify("Proyecto de Cencosud en San Isidro", "proyecto San Isidro")
    assert d1 is False
    assert d2 is False


def test_phase_family_id_column_no_longer_exists():
    """[revisión] La primera
    version del modelo de fase fusionaba matriz y fase en un solo
    phase_family_id simetrico -- eso esta conceptualmente invertido
    ("Urbanya" es la matriz, "Urbanya Etapa I" es UNA fase dentro de ella,
    no un alias de la misma fase). Se elimino esa columna; el modelo nuevo
    usa las tablas project_phase / project_phase_link con 2 relaciones
    explicitas (phase_of, same_phase_alias)."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(project)").fetchall()}
    conn.close()
    assert "phase_family_id" not in cols


def test_urbanya_has_phase_and_etapa_i_represents_it():
    """[revisión] Caso que expuso el
    error conceptual: 'Urbanya' (matriz) debe tener un link has_phase (antes
    'phase_of', renombrado) hacia el phase_id de 'Urbanya Etapa I'. Y
    'Urbanya Etapa I' -- al ser el UNICO project_id que representa esa fase,
    sin ningun alias real -- debe quedar como 'represents_phase', NO
    'same_phase_alias' (esa relacion es solo para 2+ nombres que son la
    MISMA fase, como 'Fase IV' / 'Enea Fase IV')."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    pid_urbanya = conn.execute("SELECT project_id FROM project WHERE canonical_name='Urbanya'").fetchone()[0]
    pid_etapa_i = conn.execute("SELECT project_id FROM project WHERE canonical_name='Urbanya Etapa I'").fetchone()[0]

    link_urbanya = conn.execute(
        "SELECT phase_id, relation_type FROM project_phase_link WHERE project_id=?", (pid_urbanya,)
    ).fetchall()
    link_etapa_i = conn.execute(
        "SELECT phase_id, relation_type FROM project_phase_link WHERE project_id=?", (pid_etapa_i,)
    ).fetchall()
    conn.close()

    assert link_urbanya == [(link_urbanya[0][0], "has_phase")]
    assert link_etapa_i == [(link_etapa_i[0][0], "represents_phase")]
    assert link_urbanya[0][0] == link_etapa_i[0][0]  # apuntan al mismo phase_id


def test_phase_label_is_deterministic_shortest_name_without_etapa_priority():
    """Hallazgo de la revisión: phase_side_pids es un set, y el codigo anterior
    iteraba ese set directamente para decidir que alias quedaba como
    phase_label -- el mismo export podia mostrar un alias distinto entre
    corridas identicas (el phase_id y las relaciones no cambiaban, solo la
    etiqueta). Corregido con una regla explicita y determinista (preferir
    Etapa/Fase explicita, luego el nombre mas corto, luego orden
    lexicografico). Este test fija los 3 phase_label reales esperados."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    labels = {r[0] for r in conn.execute("SELECT phase_label FROM project_phase")}
    conn.close()
    assert labels == {"Urbanya Etapa I", "Fase IV", "Mall Vivo Santiago Etapa II"}


def test_project_phase_link_has_no_duplicate_rows_and_declares_constraints():
    """Hallazgo de la revisión: 2 pares de PHASE_OF_PAIRS_BY_REVIEW resuelven al MISMO
    phase_id para la misma matriz (ej. 'Mall Vivo' es matriz tanto de 'Mall
    Vivo Santiago Etapa II' como de su alias 'Centro Comercial...'), lo que
    sin deduplicar violaria la PRIMARY KEY (project_id, phase_id,
    relation_type). Tambien verifica que la tabla declara PK y FOREIGN KEY,
    no solo que funcione."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    rows = conn.execute("SELECT project_id, phase_id, relation_type FROM project_phase_link").fetchall()
    assert len(rows) == len(set(rows))

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='project_phase_link'"
    ).fetchone()[0]
    conn.close()
    assert "PRIMARY KEY" in schema
    assert "FOREIGN KEY" in schema


def test_fase_iv_and_enea_fase_iv_are_same_phase_alias_not_phase_of():
    """Caso que la revisión senalo como la prueba mas clara de que la semantica
    estaba invertida: 'Fase IV' y '...Enea Fase IV...' SI son la misma fase
    (redactada distinto), deben compartir phase_id via same_phase_alias --
    ninguno de los 2 es 'matriz' del otro (no hay relacion phase_of aqui)."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    pid_a = conn.execute("SELECT project_id FROM project WHERE canonical_name='Fase IV'").fetchone()[0]
    pid_b = conn.execute(
        "SELECT project_id FROM project WHERE canonical_name='Radial Aeropuerto Nº 14080, Enea Fase IV, Lote 3E-2'"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT project_id, phase_id, relation_type FROM project_phase_link WHERE project_id IN (?,?)",
        (pid_a, pid_b),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert {r[2] for r in rows} == {"same_phase_alias"}
    assert len({r[1] for r in rows}) == 1  # mismo phase_id


def test_vital_apoquindo_has_no_phase_links_at_all():
    """La revisión clasifico Vital Apoquindo como 'mismo_referente_numero_no_es_fase'
    -- ninguna de sus variantes debe tener ningun link en project_phase_link
    (ni phase_of ni same_phase_alias).

    Los nombres
    exactos de las variantes cambiaron (la extraccion vigente es una corrida LLM separada
    con fraseo distinto para el mismo objeto real, mismo patron verificado
    en toda la migracion) -- se recalcularon buscando 'Vital Apoquindo' en
    canonical_name contra el warehouse real (ahora 6 variantes en vez de
    5). El punto sustantivo (cero phase links) se mantiene."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    names = (
        "Vital Apoquindo",
        "Vital Apoquindo 1.400-1.450-1.500",
        "proyecto de 25 edificios en la calle Vital Apoquindo",
        "Mega proyecto inmobiliario de 25 edificios en altura, calle Vital Apoquindo números 1.400, 1450 y 1.500",
        "Mega proyecto inmobiliario de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500",
        "proyecto de la Inmobiliaria Mirador Oriente S.A. a emplazarse en su terreno de calle Vital Apoquindo",
    )
    pids = [
        conn.execute("SELECT project_id FROM project WHERE canonical_name=?", (n,)).fetchone()[0] for n in names
    ]
    q = ",".join("?" * len(pids))
    n_links = conn.execute(
        f"SELECT COUNT(*) FROM project_phase_link WHERE project_id IN ({q})", pids
    ).fetchone()[0]
    conn.close()
    assert n_links == 0


def test_project_phase_case_id_matches_the_matrix_and_phase_shared_case():
    """El case_id guardado en project_phase debe coincidir con el case_id
    real que comparten la matriz y su fase (verificacion cruzada, no solo
    que el campo este poblado con algo)."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    case_id_urbanya = conn.execute("SELECT case_id FROM project WHERE canonical_name='Urbanya'").fetchone()[0]
    case_id_etapa_i = conn.execute("SELECT case_id FROM project WHERE canonical_name='Urbanya Etapa I'").fetchone()[0]
    phase_case_id = conn.execute(
        "SELECT case_id FROM project_phase WHERE phase_label='Urbanya Etapa I'"
    ).fetchone()[0]
    conn.close()
    assert case_id_urbanya == case_id_etapa_i == phase_case_id


def test_known_homonyms_stay_separate_in_project_id_and_case_id():
    """Hallazgo BLOQUEANTE de la revisión (tercera auditoria, 2026-09-18): separar un
    homonimo a nivel de project_id no basta -- Costanera Center Chile y
    Argentina volvian a conectarse por case_id porque ambas pasaban por el
    mismo par con nombre identico ('Costanera Center' vs 'mall Costanera
    Center' -> merged), y classify() decide por nombre sin saber que hay 2
    project_id detras. Corregido con homonym_partition + veto de
    reconexion transitiva en union(). Este test fija, para los 3 homonimos
    conocidos, que project_id Y case_id permanecen distintos tras resolver
    la cola completa contra la base real."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    # se agrupa por la BASE del homonimo (antes de "::" en homonym_partition),
    # no por canonical_name -- San Isidro produce 2 canonical_name distintos
    # ("San Isidro" y "proyecto San Isidro"), Plaza Egaña produce el mismo
    # canonical_name para ambas mitades.
    # [ACTUALIZADO 2026-09-18, tras aplicar la correccion completa de la revisión
    # sobre los 934 documentos] "costanera center": la revisión corrigio
    # proyectos_mencionados del documento de Cencosud en Argentina
    # (reemplazo "Costanera Center" por "Proyecto de Cencosud en San
    # Isidro"), asi que ese documento ya no genera esa mencion especifica --
    # el homonimo se resolvio en el DATO, no solo en el project_id, y el
    # split de KNOWN_HOMONYM_SPLITS para ese caso quedo inerte (se deja en
    # el codigo, sin efecto, documentado como historico).
    #
    # "san isidro"
    # tambien quedo inerte por el mismo mecanismo, verificado leyendo el
    # JSONL real: la extraccion vigente (corrida LLM separada) extrajo para el documento
    # fuente ('...segreader.emol.cl/2017/04/13/A/JI3512LK...') dos menciones
    # completamente re-fraseadas ('departamentos en Las Rejas norte',
    # 'lo que quieren vender en calle Toro Mazotte') -- ninguna normaliza a
    # "san isidro", asi que la entrada de KNOWN_HOMONYM_SPLITS para ese
    # documento nunca vuelve a activarse. Solo "plaza egana" sigue activo
    # (su documento fuente conserva el nombre "Plaza Egaña" en la extraccion vigente)."""
    rows = conn.execute("SELECT project_id, case_id, homonym_partition FROM project WHERE homonym_partition IS NOT NULL").fetchall()
    by_base: dict[str, list[tuple[str, str]]] = {}
    for project_id, case_id, partition in rows:
        base = partition.split("::", 1)[0]
        by_base.setdefault(base, []).append((project_id, case_id))
    for base in ("plaza egana",):
        entries = by_base.get(base, [])
        assert len(entries) == 2, f"se esperaban 2 project_id homonimo para base {base!r}, hay {len(entries)}"
        project_ids = {e[0] for e in entries}
        case_ids = {e[1] for e in entries}
        assert len(project_ids) == 2, f"project_id no distintos para base {base!r}"
        assert len(case_ids) == 2, f"case_id SE RECONECTARON para base {base!r}: {entries}"
    conn.close()


def test_manual_audit_31_corrections():
    """Regresion: la revisión externa audito los 253 pares con evidencia real y
    reporto 31 desacuerdos con las decisiones originales de la revisión. Cada uno
    de los 31 fue reverificado por la revisión contra la evidencia real (comuna/
    direccion/URL de los documentos, no solo el nombre) antes de aceptarlo --
    18 falsas separaciones que en realidad eran el mismo proyecto (numeros de
    DIRECCION mal tratados como numeros de ETAPA/FASE: General Amengual 480,
    Pajaritos 4600, Vital Apoquindo 1400-1500, y el cluster Mall Vivo/Urbanya
    donde 'Etapa' era una fase del mismo caso, no un proyecto distinto), y
    13 fusiones agresivas que en realidad eran proyectos distintos (nombre de
    empresa/institucion confundido con proyecto especifico: Nueva El Golf,
    Universidad San Sebastian, Fundamenta en Ñuñoa; o coincidencia de nombre
    generico sin evidencia geografica real: Rotonda Atenas, Barrio Maestranza,
    Barrio Parque, Parque Bicentenario Cerrillos, Hospital del Salvador,
    Carlos Valdovinos, Toro Mazotte, San Isidro). Este test fija esas 31
    decisiones para que no se reviertan por accidente en un refactor futuro."""
    esperado_merge = {
        ("General Amengual", "edificio de 38 pisos y más de 300 departamentos ubicado en calle General Amengual 480"),
        ("Edificio Pajaritos", "Pajaritos 4600"),
        ("Mall Vivo Santiago Etapa II", "Mall Vivo"),
        ("Mall Vivo Santiago Etapa II", "Mall Vivo Santiago"),
        ("Urbanya Etapa I", "Urbanya"),
        ("Mall Vivo", "Mall Vivo Ñuñoa"),
        ("Mall Vivo", "Centro Comercial Mall Vivo Santiago Etapa II"),
        ("Mall Vivo", "Mall Vivo Santiago: Etapa de Demolición, Excavación y Socalzados"),
        ("Mall Vivo", "Mall Vivo Santiago"),
        ("Edificio Capital", "Condominio Eco Capital"),
        ("Eco Egaña", "Eco Egaña Poniente"),
        ("Centro de Salud Familiar (Cesfam)", "tercer Centro de Salud Familiar (Cesfam) de Las Condes"),
        ("calle Vital Apoquindo 1.400-1.450-1.500", "Vital Apoquindo"),
        ("Las Américas", "Colegio Las Américas"),
        ("Mall Vivo Santiago", "Centro Comercial Mall Vivo Santiago Etapa II"),
        ("Vital Apoquindo", "Proyecto de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500"),
        ("Vital Apoquindo", "Vital Apoquindo números 1.400, 1450 y 1.500"),
        ("Vital Apoquindo", "proyecto de 25 edificios en la calle Vital Apoquindo"),
    }
    esperado_separado = {
        ("Rotonda Atenas", "proyecto social de 2023 de la rotonda Atenas"),
        ("proyecto de Inmobiliaria Nueva El Golf", "proyecto que impulsa la inmobiliaria Nueva El Golf"),
        ("proyecto de Inmobiliaria Nueva El Golf", "Nueva El Golf"),
        ("planta de tratamiento de aguas servidas de la Empresa San Isidro", "San Isidro"),
        ("calle Toro Mazotte", "cuatro megaedificios ubicados en calle Toro Mazotte"),
        ("Carlos Valdovinos", "tres torres de 15 pisos y dos subterráneos, cada uno en un sector de avenida Carlos Valdovinos"),
        ("proyecto inmobiliario de Fundamenta en Ñuñoa", "proyecto inmobiliario de Fundamenta"),
        ("Universidad San Sebastián", "Proyecto de la Universidad San Sebastián en la manzana delimitada por las calles Bellavista, Ernesto Pinto Lagarrigue, Dardignac y Pío Nono"),
        ("Nueva El Golf", "proyecto que impulsa la inmobiliaria Nueva El Golf"),
        ("Barrio Maestranza 1", "barrio Maestranza"),
        ("Barrio Parque", "Barrio Parque de Quinta Normal"),
        ("Parque Bicentenario Cerrillos", "Parque Bicentenario"),
        ("Hospital del Salvador", "nuevo Hospital del Salvador"),
    }
    assert len(esperado_merge) == 18
    assert len(esperado_separado) == 13
    for a, b in esperado_merge:
        decision, _ = rpq.classify(a, b)
        assert decision is True, f"deberia fusionar: {a!r} / {b!r}"
    for a, b in esperado_separado:
        decision, _ = rpq.classify(a, b)
        assert decision is False, f"deberia mantenerse separado: {a!r} / {b!r}"


def test_renamed_names_do_not_inherit_a_manual_decision_by_substring(monkeypatch):
    fake_manual = {("Torre Central", "proyecto Torre Central"): (True, "mismo proyecto")}
    monkeypatch.setattr(rpq, "MANUAL_DECISIONS", fake_manual)
    result = rpq.classify_with_provenance(
        "Torre Central 2024", "proyecto Torre Central en Ñuñoa"
    )
    assert result[0] is None
    assert result[2] == "unresolved"


def test_generic_blocklist_still_blocks_unqualified_name(monkeypatch):
    """A generic bare name remains a deterministic non-merge guard."""
    fake_manual = {("Vespucio", "Jardines de Vespucio"): (True, "no deberia aplicar aqui")}
    monkeypatch.setattr(rpq, "MANUAL_DECISIONS", fake_manual)
    decision, reason = rpq.classify("edificio en Avenida Vespucio 7550", "Vespucio")
    assert decision is False
    assert "generico" in reason


def test_review_queue_is_covered_and_reviewed_pairs_keep_their_exact_outcomes():
    """La cola de revision real queda cubierta: toda fila tiene una decision (por regla, por decision manual
    explicita o por adjudicacion de la pareja exacta de project_id). El numero de pares de la cola NO es estable
    por diseno -- depende de las menciones extraidas --, asi que lo que protege es que las decisiones manuales de
    las unidades de conflicto sigan presentes y decididas 'merged', y que las adjudicaciones por ID sigan
    coincidiendo con la cola y con los nombres vigentes."""
    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        pytest.skip("warehouse.sqlite no existe en este entorno")
    with sqlite3.connect(warehouse) as conn:
        id_rows = conn.execute(
            "SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b FROM project_review_queue"
        ).fetchall()
        projects = dict(conn.execute("SELECT project_id, canonical_name FROM project"))
    assert len(id_rows) == 258

    # find_review_candidates() ignora en silencio un par de MANUAL_EXTRA_REVIEW_PAIRS si el nombre ya no existe en
    # el registro (necesario para fixtures sinteticos); este test es la proteccion contra que un par real desaparezca
    # sin aviso. ("Alto Las Condes 2", "Alto Norte") esta inerte: sus documentos fuente ya no mencionan "Alto Norte".
    pares_reales = {frozenset((row[2], row[4])) for row in id_rows}
    pares_inertes = {frozenset(("Alto Las Condes 2", "Alto Norte"))}
    for name_a, name_b, _reason in bridge.MANUAL_EXTRA_REVIEW_PAIRS:
        if frozenset((name_a, name_b)) in pares_inertes:
            continue
        assert frozenset((name_a, name_b)) in pares_reales, (
            f"par manual '{name_a}' / '{name_b}' ya no esta en project_review_queue -- verificar si el nombre cambio"
        )
        assert rpq.classify(name_a, name_b)[0] is True, f"'{name_a}' / '{name_b}' deberia estar merged"

    decisions = rpq.load_project_identity_decisions()
    rpq.validate_project_identity_adjudication_scope(projects, id_rows, decisions)
    adjudicated_ids = {tuple(sorted(entry["project_ids"])) for entry in decisions}
    observed = {True: 0, False: 0, None: 0}
    for _rowid, pid_a, name_a, pid_b, name_b in id_rows:
        if tuple(sorted((pid_a, pid_b))) in adjudicated_ids:
            observed[rpq.classify_project_pair_with_adjudications(pid_a, name_a, pid_b, name_b, decisions)[0]] += 1
    assert observed == {True: 39, False: 56, None: 0}


def test_historical_pairs_are_decided_by_exact_id_and_uncertainty_stays_explicit():
    """Las 27 parejas historicas recuperadas se deciden solo por pareja exacta de project_id, con evidencia literal."""
    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        pytest.skip("warehouse.sqlite no existe en este entorno")
    decisions = rpq.load_project_identity_decisions()
    historical = [entry for entry in decisions if entry["pair_id"].startswith("historical_pair:")]
    assert len(historical) == 27
    by_pair = {tuple(sorted(entry["project_ids"])): entry for entry in historical}
    outcomes = {}
    for pair, entry in by_pair.items():
        pid_a, pid_b = entry["project_ids"]
        outcomes[pair] = rpq.classify_project_pair_with_adjudications(
            pid_a, entry["project_names"][pid_a], pid_b, entry["project_names"][pid_b], decisions
        )[0]
    assert {value: list(outcomes.values()).count(value) for value in (True, False, None)} == {True: 10, False: 17, None: 0}
    # Cenco Costanera mezcla activo e iniciativas en un solo project_id: no se fusiona, queda separado por evidencia insuficiente.
    costanera = tuple(sorted(("e8fd7b147a07358cd8e129e9", "d18b439c5be31864ad8f1e21")))
    assert outcomes[costanera] is False
    assert by_pair[costanera]["identity_class"] == "parent_component_phase"
    for pair in (("17f3b690577f9fd996b9c4bd", "69daf84c98731696f403b9da"), ("a812c5dd74897808e543d008", "a7582eea55bbe9571084de75"),
                 ("5f4d9617fe0e8aed5c2a5413", "07f2e2ce4fe660358aba5d28"), ("f8ddadd1807ecdd4188c0847", "69daf84c98731696f403b9da"),
                 ("6787fa6cc302091a8ea27645", "a812c5dd74897808e543d008")):
        assert outcomes[tuple(sorted(pair))] is False


def test_reviewed_pairs_keep_the_reviewed_identity_class_per_exact_ids():
    decisions = rpq.load_project_identity_decisions()
    by_pair = {tuple(sorted(entry["project_ids"])): entry for entry in decisions}
    expected = {
        ("91f2112803222891bec22245", "2501823afe7521d105456260"): "same_identity",
        ("803b8601f7f58a2b25f694cd", "a07066976e35eb7bd807ed77"): "same_identity",
        ("52431d07bb532a107713c2bd", "bcf9a9d46577aec285a3b590"): "distinct_entities",
        ("5997fefd9709a67727316bc2", "fe0f38566717aa34de32376a"): "same_identity",
        ("e37655355ac179806569a998", "fe0f38566717aa34de32376a"): "same_identity",
        ("0a9d6730e059f72c2cdec2d8", "ad2b70567df6b8d44f952100"): "same_identity",
        ("a07066976e35eb7bd807ed77", "01d6668a9dc5aba908f81090"): "distinct_entities",
        ("922533b858c751fc8f5a8e3b", "fe0f38566717aa34de32376a"): "same_identity",
        ("cb1087cc68bd26d203011f18", "8e88d3996773e1c8ecf04a7c"): "same_identity",
        ("bb5755a35f19ada504ca13a4", "de08d293dbbdbbb72d27e6ae"): "same_identity",
        ("89ddfb0616d12dccc7393b63", "cf65c362a0dd71489735dc57"): "distinct_entities",
        ("e986c115668629af6342f449", "e37655355ac179806569a998"): "same_identity",
        ("06cac2c4b094ac1ed38ac40b", "d8612c60e4f66ef4627d31c5"): "same_identity",
        ("06cac2c4b094ac1ed38ac40b", "623ed9e19dc274ad6b3ae8dd"): "same_identity",
        ("06cac2c4b094ac1ed38ac40b", "7e66e9745e63138bdbdf2c76"): "same_identity",
        ("2cfcdb67a6274db8af9377f6", "2a40c16d17565173915c550d"): "insufficient_evidence",
        ("ffa5c9b29b95f230d34616d9", "4648a378b2f533657c23de7a"): "same_identity",
        ("1c1f2a962eca459282a98baa", "7a4072da49c6decfd6df3f01"): "same_identity",
        ("14537e43f763c717791c5b90", "00a49b2fac5c7887f0c4f628"): "insufficient_evidence",
        ("e8fd7b147a07358cd8e129e9", "d18b439c5be31864ad8f1e21"): "parent_component_phase",
    }
    for pair, identity_class in expected.items():
        assert by_pair[tuple(sorted(pair))]["identity_class"] == identity_class, pair
    # El merge de Fundamenta se mantiene exacto (canonical fijado); Plaza Egaña queda separado.
    fundamenta = by_pair[tuple(sorted(("bb5755a35f19ada504ca13a4", "de08d293dbbdbbb72d27e6ae")))]
    assert fundamenta["resolver_action"] == "merge_case" and fundamenta["canonical_project_id"] == "bb5755a35f19ada504ca13a4"
    plaza = by_pair[tuple(sorted(("89ddfb0616d12dccc7393b63", "cf65c362a0dd71489735dc57")))]
    assert plaza["resolver_action"] == "no_new_merge" and plaza["canonical_project_id"] is None


def test_decision_keeps_the_exact_id_scope_and_provenance_points_to_the_config_file():
    decisions = rpq.load_project_identity_decisions()
    ids = ("91f2112803222891bec22245", "2501823afe7521d105456260")
    result = rpq.classify_project_pair_with_adjudications(
        ids[0], "Carlos Valdovinos", ids[1], "proyecto de SuKasa en avenida Carlos Valdovinos", decisions
    )
    assert result[0] is True
    assert result[2] == rpq.PROJECT_IDENTITY_DECISION_SOURCE
    provenance = json.loads(
        rpq.decision_provenance_ref(
            "Carlos Valdovinos", "proyecto de SuKasa en avenida Carlos Valdovinos", result[2],
            project_ids=ids, identity_adjudications=decisions,
        )
    )
    assert provenance["artifact"] == "config/project_identity_decisions.json"
    # El hash se calcula sobre el archivo con saltos de linea normalizados: no depende de la configuracion de git.
    assert provenance["artifact_sha256"] == hashlib.sha256(DECISIONS_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert provenance["supporting_source_urls"], "una decision con fuentes de apoyo debe listarlas"

    other_ids = rpq.classify_project_pair_with_adjudications(
        "unreviewed-a", "Carlos Valdovinos", "unreviewed-b", "proyecto de SuKasa en avenida Carlos Valdovinos", decisions
    )
    assert other_ids[0] is None
    assert other_ids[2] == "reviewed_name_scope_guard"


def test_no_pair_is_left_unresolved_and_uncertainty_is_explicit():
    """Cierre de la cola: Recreo se identifica con respaldo oficial de direccion/entidad; Santa Petronila y Alto Las
    Condes permanecen sin fusion por identificadores insuficientes, no como diferencias probadas."""
    decisions = rpq.load_project_identity_decisions()
    assert not [d for d in decisions if d["identity_class"] == "unresolved"]
    by_pair = {tuple(sorted(d["project_ids"])): d for d in decisions}
    recreo = by_pair[tuple(sorted(("0a9d6730e059f72c2cdec2d8", "ad2b70567df6b8d44f952100")))]
    assert recreo["identity_class"] == "same_identity" and recreo["canonical_project_id"] == "0a9d6730e059f72c2cdec2d8"
    urls = {source["url"] for source in recreo["supporting_sources"]}
    assert "https://mercadosinmobiliarios.cl/wp-content/uploads/2024/10/E547184.pdf" in urls
    assert "https://documentos.minvu.cl/bitstreams/008434c5-0b80-41cc-8319-a294cda25405/download" in urls
    for ids in (("14537e43f763c717791c5b90", "00a49b2fac5c7887f0c4f628"), ("2cfcdb67a6274db8af9377f6", "2a40c16d17565173915c550d")):
        entry = by_pair[tuple(sorted(ids))]
        assert entry["identity_class"] == "insufficient_evidence"
        assert entry["resolver_action"] == "no_new_merge" and entry["canonical_project_id"] is None


def test_legacy_name_level_merges_contradicted_by_sources_are_reverted():
    """La coincidencia de nombre o de desarrollador no es identidad: 'Reserva La Dehesa'
    (54 casas, Cerro del Medio) != Reserva La Dehesa (ex Chaguay), y el edificio de
    Desarrollo Inmobiliario Bellavista (Estacion Central) != proyecto Bellavista (Recoleta)."""
    assert rpq.classify("Reserva La Dehesa", "Reserva La Dehesa (ex Chaguay)")[0] is False
    assert rpq.classify("proyecto Bellavista", "edificio de Desarrollo Inmobiliario Bellavista")[0] is False
    assert rpq.classify("Chaguay", "Reserva La Dehesa (ex Chaguay)")[0] is True


def test_lote_18_family_is_kept_separate_by_explicit_decisions():
    """Tras separar Lote 18-A de Lote 18, ambos pares nuevos quedan resueltos sin fusion."""
    assert rpq.classify("Lote 18", "Lote 18-A")[0] is False
    assert rpq.classify("Lote 18-A", "Lote 18-A1")[0] is False
    assert rpq.classify("Lote 18", "Lote 18-A1")[0] is True
