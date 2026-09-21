import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(r"D:\Felipe\Consultora\caso_inmobiliario_stgo")
SCRIPTS = ROOT / "Trabajo" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot = load("snapshot_discovery_under_test", "snapshot_discovery.py")
fulltext = load("fulltext_under_test", "fulltext_acquisition_v2.py")
classify = load("classify_under_test", "classify_luna.py")
dedupe = load("dedupe_under_test", "dedupe_fulltext.py")
pipeline_lock = load("pipeline_lock_under_test", "pipeline_lock.py")
repair = load("repair_under_test", "repair_fulltext_lineage.py")
enrich = load("enrich_under_test", "enrich_case.py")


class IntegrityFixTests(unittest.TestCase):
    def test_snapshot_classifies_legacy_records_instead_of_silently_mixing(self):
        record = {"query": "edificios", "comuna": "Las Condes", "termino": "altura"}
        self.assertEqual(snapshot.classify_discovery_record(record), "legacy_v1")

    def test_fulltext_preserves_all_discovery_origins_for_same_url(self):
        records = [
            {"resolved_url": "https://example.test/a", "record_hash": "h1", "query": "q1", "comuna": "A", "termino": "t", "periodo": "p", "nivel": "n", "contract_version": "discovery_v2"},
            {"resolved_url": "https://example.test/a", "record_hash": "h2", "query": "q2", "comuna": "B", "termino": "t", "periodo": "p", "nivel": "n", "contract_version": "discovery_v2"},
        ]
        path = Path(tempfile.gettempdir()) / "codex_root_fix_fixture.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        try:
            unique = fulltext.load_unique_discoveries(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(unique[0]["_origins"]), 2)

    def test_fulltext_does_not_mix_marked_legacy_row(self):
        records = [
            {"resolved_url": "https://example.test/legacy", "record_hash": "old", "contract_version": "legacy_v1"},
            {"resolved_url": "https://example.test/v2", "record_hash": "new", "contract_version": "discovery_v2"},
        ]
        path = Path(tempfile.gettempdir()) / "codex_contract_fixture.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        try:
            unique = fulltext.load_unique_discoveries(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([row["resolved_url"] for row in unique], ["https://example.test/v2"])

    def test_classification_payload_validation_rejects_missing_required_fields(self):
        schema = json.loads((ROOT / "Trabajo" / "config" / "classification_schema_v2.json").read_text(encoding="utf-8"))
        self.assertFalse(classify.validate_classification_payload({"decision": "include"}, schema))

    def test_evidence_verified_is_false_when_no_quote_exists(self):
        doc = {"url": "u", "text": "texto", "lineage": {}}
        result = {"parsed": {"decision": "exclude", "evidence_quote": ""}, "usage": {}}
        _decision, record = classify.postprocess_result(doc, result)
        self.assertFalse(record["evidence_verified"])

    def test_fingerprint_candidate_does_not_finalize_url(self):
        events = [
            {"event": "fingerprint_candidate", "url": "u1"},
            {"event": "canonical_elected", "url": "u2", "content_hash": "h"},
        ]
        self.assertEqual(dedupe.finalized_event_urls(events), {"u2"})

    def test_rebuild_manifest_uses_current_lineage_for_canonical_origin(self):
        base = Path(tempfile.gettempdir())
        content_path = base / "codex_dedupe_content.json"
        events_path = base / "codex_dedupe_events.jsonl"
        manifest_path = base / "codex_dedupe_manifest.jsonl"
        old_paths = dedupe.CONTENT_DIR, dedupe.EVENTS_PATH, dedupe.MANIFEST_PATH
        current_lineage = {"origins": [{"discovery_record_hash": "h1"}, {"discovery_record_hash": "h2"}]}
        stale_lineage = {"origins": [{"discovery_record_hash": "h1"}, {"discovery_record_hash": "h1"}]}
        content_path.write_text(json.dumps({"url": "https://example.test/a", "char_count": 500, "text": "texto", "lineage": current_lineage}) + "\n", encoding="utf-8")
        events_path.write_text(json.dumps({"event": "canonical_elected", "content_hash": "h", "url": "https://example.test/a", "char_count": 500, "lineage": stale_lineage, "ts": "t"}) + "\n", encoding="utf-8")
        try:
            dedupe.CONTENT_DIR = base
            dedupe.EVENTS_PATH = events_path
            dedupe.MANIFEST_PATH = manifest_path
            dedupe.rebuild_manifest()
            row = json.loads(manifest_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(
                [origin["discovery_record_hash"] for origin in row["origins"][0]["lineage"]["origins"]],
                ["h1", "h2"],
            )
        finally:
            dedupe.CONTENT_DIR, dedupe.EVENTS_PATH, dedupe.MANIFEST_PATH = old_paths
            for path in (content_path, events_path, manifest_path):
                path.unlink(missing_ok=True)

    def test_run_state_mutex_does_not_break_live_owner(self):
        mutex_path = Path(tempfile.gettempdir()) / f"codex_run_state_{__import__('os').getpid()}.mutex"
        old_path = pipeline_lock.RUN_STATE_MUTEX_PATH
        old_wait = pipeline_lock.RUN_STATE_MUTEX_MAX_WAIT_S
        try:
            pipeline_lock.RUN_STATE_MUTEX_PATH = mutex_path
            pipeline_lock.RUN_STATE_MUTEX_MAX_WAIT_S = 0.01
            mutex_path.write_text(json.dumps({"pid": __import__("os").getpid(), "token": "live"}), encoding="utf-8")
            with self.assertRaises(TimeoutError):
                with pipeline_lock._run_state_mutex():
                    pass
            self.assertTrue(mutex_path.exists())
        finally:
            mutex_path.unlink(missing_ok=True)
            pipeline_lock.RUN_STATE_MUTEX_PATH = old_path
            pipeline_lock.RUN_STATE_MUTEX_MAX_WAIT_S = old_wait

    def test_lineage_repair_reconstructs_all_snapshot_origins(self):
        path = Path(tempfile.gettempdir()) / "codex_lineage_fixture.jsonl"
        rows = [
            {"resolved_url": "https://example.test/a", "record_hash": "h1", "query": "q1", "query_hash": "qh1", "plan_version": "discovery_plan_v2", "comuna": "A", "termino": "t", "periodo": "p", "nivel": "n", "contract_version": "discovery_v2"},
            {"resolved_url": "https://example.test/a", "record_hash": "h1", "query": "q1", "query_hash": "qh1", "plan_version": "discovery_plan_v2", "comuna": "A", "termino": "t", "periodo": "p", "nivel": "n", "contract_version": "discovery_v2"},
            {"resolved_url": "https://example.test/a", "record_hash": "h2", "query": "q2", "query_hash": "qh2", "plan_version": "discovery_plan_v2", "comuna": "B", "termino": "t", "periodo": "p", "nivel": "n", "contract_version": "discovery_v2"},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        try:
            lineage = repair.build_lineage_map(path, {"run_id": "r1", "snapshot_sha256": "sha"})
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(lineage["https://example.test/a"]["origins"]), 2)
        self.assertEqual(lineage["https://example.test/a"]["snapshot_run_id"], "r1")
        self.assertEqual(lineage["https://example.test/a"]["query_hash"], "qh1")
        self.assertEqual(lineage["https://example.test/a"]["plan_version"], "discovery_plan_v2")
        self.assertEqual(
            [origin["query_hash"] for origin in lineage["https://example.test/a"]["origins"]],
            ["qh1", "qh2"],
        )

    def test_fulltext_lineage_propagates_query_identity(self):
        record = {
            "record_hash": "h1",
            "query": "q1",
            "query_hash": "qh1",
            "plan_version": "discovery_plan_v2",
            "comuna": "A",
            "termino": "t",
            "periodo": "p",
            "nivel": "n",
            "_origins": [
                {
                    "record_hash": "h1",
                    "query": "q1",
                    "query_hash": "qh1",
                    "plan_version": "discovery_plan_v2",
                    "comuna": "A",
                    "termino": "t",
                    "periodo": "p",
                    "nivel": "n",
                }
            ],
        }
        lineage = fulltext.build_lineage(record, {"snapshot_sha256": "sha", "run_id": "r1"})
        self.assertEqual(lineage["query_hash"], "qh1")
        self.assertEqual(lineage["plan_version"], "discovery_plan_v2")
        self.assertEqual(lineage["origins"][0]["query_hash"], "qh1")
        self.assertEqual(lineage["origins"][0]["plan_version"], "discovery_plan_v2")

    def test_corpus_scope_separates_legacy_only_from_mixed_provenance(self):
        self.assertEqual(
            classify.corpus_scope_for_lineage({"periodo": "", "nivel": "", "origins": [{"periodo": "", "nivel": ""}]}),
            "legacy_sin_ventana",
        )
        self.assertEqual(
            classify.corpus_scope_for_lineage({"periodo": "", "nivel": "", "origins": [{"periodo": "", "nivel": ""}, {"periodo": "2021_2023", "nivel": "comuna"}]}),
            "temporal_v2_mixed_legacy",
        )

    def test_enrichment_scope_gate_excludes_legacy_only(self):
        self.assertFalse(enrich.should_include_case_in_enrichment({"corpus_scope": "legacy_sin_ventana"}))
        self.assertTrue(enrich.should_include_case_in_enrichment({"corpus_scope": "temporal_v2_mixed_legacy"}))

    def test_jsonl_reader_tolerates_corrupt_materialized_input(self):
        path = Path(tempfile.gettempdir()) / "codex_corrupt_jsonl_fixture.jsonl"
        path.write_text('{"ok": true}\n{truncated\n', encoding="utf-8")
        try:
            self.assertEqual(pipeline_lock.read_jsonl_tolerant(path), [{"ok": True}])
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
