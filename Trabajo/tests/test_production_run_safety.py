"""Hallazgos de Codex/Luna sobre seguridad operacional de la corrida de
produccion (2026-09-16, antes de la primera corrida real a escala de 3835
documentos). No llaman a la API real."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import classify_v5_2_1 as target  # noqa: E402
import classify_v5_2_3 as v523  # noqa: E402
from pipeline_lock import StageSkipped  # noqa: E402


def _fake_docs(n=2):
    return [{"url": f"https://example.cl/doc{i}", "text": f"contenido {i}", "lineage": {}} for i in range(n)]


def _patch_common(monkeypatch, tmp_path, docs, output_path):
    # Archivos reales (no SimpleNamespace): _sha256_file() del manifiesto de
    # corrida necesita .read_bytes() real, no solo .read_text() simulado.
    fake_schema = tmp_path / "fake_schema.json"
    fake_schema.write_text("{}", encoding="utf-8")
    fake_prompt = tmp_path / "fake_prompt.md"
    fake_prompt.write_text("prompt", encoding="utf-8")
    monkeypatch.setattr(target.v51, "load_env", lambda _p: {"OPENROUTER_API_KEY": "fake-key"})
    monkeypatch.setattr(target.v51, "load_classifiable_documents", lambda urls_filter=None: docs)
    monkeypatch.setattr(target.v51, "already_classified_urls", lambda _p: set())
    monkeypatch.setattr(target, "SCHEMA_PATH", fake_schema)
    monkeypatch.setattr(target, "PROMPT_PATH", fake_prompt)
    monkeypatch.setattr(target, "postprocess_result", lambda doc, result: ("include", {"url": doc["url"], "decision_documento": "include"}))


def test_failed_document_is_recorded_in_errors_jsonl_not_silently_dropped(tmp_path, monkeypatch):
    output_path = tmp_path / "classifications.jsonl"
    docs = _fake_docs(2)
    _patch_common(monkeypatch, tmp_path, docs, output_path)

    def fake_classify(doc, api_key, prompt, schema):
        if doc["url"].endswith("doc1"):
            return {"error": "schema_validation_failed"}
        return {"parsed": {}, "usage": {}, "reasoning": None, "reasoning_details": None}

    monkeypatch.setattr(target.v51, "classify_document", fake_classify)
    # urls_file acotado para que is_test=True explicitamente -- --output-file
    # solo ya no activa el modo prueba (fix del punto 1, ronda siguiente).
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("\n".join(d["url"] for d in docs), encoding="utf-8")
    args = argparse.Namespace(limit=0, dry_run=False, urls_file=str(urls_file), output_file=str(output_path), workers=1)
    target._run(args)

    lines = [json.loads(l) for l in output_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, "el documento exitoso debe quedar escrito"

    errors_path = output_path.with_name(output_path.stem + ".errors.jsonl")
    assert errors_path.exists(), "debe existir un archivo de errores"
    error_lines = [json.loads(l) for l in errors_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(error_lines) == 1
    assert error_lines[0]["error"] == "schema_validation_failed"
    assert error_lines[0]["url"].endswith("doc1")


def test_dry_run_never_calls_the_api(tmp_path, monkeypatch):
    output_path = tmp_path / "classifications.jsonl"
    docs = _fake_docs(3)
    _patch_common(monkeypatch, tmp_path, docs, output_path)

    def explode_if_called(doc, api_key, prompt, schema):
        raise AssertionError("classify_document NO debe llamarse en --dry-run")

    monkeypatch.setattr(target.v51, "classify_document", explode_if_called)
    args = argparse.Namespace(limit=0, dry_run=True, urls_file="", output_file=str(output_path), workers=1)
    result = target._run(args)

    assert result == 0
    assert not output_path.exists(), "dry-run no debe escribir ningun archivo de salida"


def test_content_hash_is_present_and_correct_in_production_record():
    doc = {"url": "https://example.cl/x", "text": "El texto completo del articulo de prueba.", "lineage": {"query": "q"}}
    result = {"parsed": {"decision": "exclude", "case_mentions": [], "sentiment": "neutral", "source_type": "medio", "confidence": "alta"}, "usage": {}, "reasoning": None, "reasoning_details": None}
    _, record = v523.postprocess_result(doc, result)

    import hashlib
    expected = hashlib.sha256(doc["text"].encode("utf-8")).hexdigest()
    assert record["content_sha256"] == expected
    assert record["content_char_count"] == len(doc["text"])


def test_large_urls_file_does_not_bypass_the_human_review_gate(tmp_path, monkeypatch):
    """El hallazgo central del punto 5: --urls-file existe para pruebas
    chicas; con muchas URLs (todo el corpus disfrazado de prueba) debe
    seguir exigiendo el gate humano, no saltarselo silenciosamente."""
    many_urls = tmp_path / "many_urls.txt"
    many_urls.write_text("\n".join(f"https://example.cl/{i}" for i in range(target.MAX_TEST_URLS_WITHOUT_GATE + 1)), encoding="utf-8")

    monkeypatch.setattr(target, "REVIEW_ARTIFACT_PATH", tmp_path / "no_existe.json")
    monkeypatch.setattr(target, "upstream_stage_is_running", lambda _stage: False)

    args = argparse.Namespace(limit=0, dry_run=False, urls_file=str(many_urls), output_file="", workers=1)
    raised = False
    try:
        target._run(args)
    except StageSkipped as exc:
        raised = True
        assert exc.return_code == 4
    assert raised, "un --urls-file grande debe seguir exigiendo el gate humano (StageSkipped)"


def test_small_urls_file_still_bypasses_gate_for_legitimate_testing(tmp_path, monkeypatch):
    """Contraste con la prueba anterior: una muestra de prueba chica (bajo
    el umbral) sigue funcionando sin exigir el gate, como siempre."""
    small_urls = tmp_path / "few_urls.txt"
    small_urls.write_text("https://example.cl/uno\n", encoding="utf-8")
    output_path = tmp_path / "out.jsonl"
    docs = [{"url": "https://example.cl/uno", "text": "contenido", "lineage": {}}]
    _patch_common(monkeypatch, tmp_path, docs, output_path)
    monkeypatch.setattr(target.v51, "classify_document", lambda *a, **k: {"parsed": {}, "usage": {}, "reasoning": None, "reasoning_details": None})

    args = argparse.Namespace(limit=0, dry_run=False, urls_file=str(small_urls), output_file=str(output_path), workers=1)
    result = target._run(args)
    assert result == 0
    assert output_path.exists()


def test_output_file_alone_does_not_bypass_the_human_review_gate(tmp_path, monkeypatch):
    """Segundo hallazgo del punto 1 (ronda siguiente de Codex/Luna):
    --output-file por si solo NO acota el alcance de la corrida (podria
    seguir procesando los 3835 documentos pendientes enteros, solo que
    escribiendo a otro archivo) -- no debe activar el modo prueba."""
    output_path = tmp_path / "salida_alternativa.jsonl"
    monkeypatch.setattr(target, "REVIEW_ARTIFACT_PATH", tmp_path / "no_existe.json")
    monkeypatch.setattr(target, "upstream_stage_is_running", lambda _stage: False)

    args = argparse.Namespace(limit=0, dry_run=False, urls_file="", output_file=str(output_path), workers=1)
    raised = False
    try:
        target._run(args)
    except StageSkipped as exc:
        raised = True
        assert exc.return_code == 4
    assert raised, "--output-file solo (sin --urls-file acotado ni --dry-run) debe seguir exigiendo el gate humano"


def test_run_manifest_is_written_with_counts_and_cost(tmp_path, monkeypatch):
    """Punto 6: el conteo esperados/escritos/errores debe quedar en un
    manifiesto durable en disco, no solo en el log."""
    output_path = tmp_path / "classifications.jsonl"
    docs = _fake_docs(2)
    _patch_common(monkeypatch, tmp_path, docs, output_path)

    def fake_classify(doc, api_key, prompt, schema):
        if doc["url"].endswith("doc1"):
            return {"error": "schema_validation_failed"}
        return {"parsed": {}, "usage": {"cost": 0.0042}, "reasoning": None, "reasoning_details": None}

    monkeypatch.setattr(target.v51, "classify_document", fake_classify)
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("\n".join(d["url"] for d in docs), encoding="utf-8")
    args = argparse.Namespace(limit=0, dry_run=False, urls_file=str(urls_file), output_file=str(output_path), workers=1)
    target._run(args)

    # Fix 2026-09-16 (hallazgo de Codex/Luna, ronda siguiente): el
    # manifiesto ahora lleva el run_id en el nombre (un archivo por
    # intento, no se sobreescribe si la corrida se interrumpe y se
    # reanuda) -- se ubica por patron en vez de por nombre fijo.
    manifests = list(tmp_path.glob("classifications.run_manifest.*.json"))
    assert len(manifests) == 1, "debe existir exactamente un manifiesto para esta corrida"
    manifest_path = manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] in manifest_path.name, "el nombre del archivo debe incluir el run_id"
    assert manifest["written"] == 1
    assert manifest["errors"] == 1
    assert manifest["esperados"] == 2
    assert manifest["counts_consistent"] is True
    assert manifest["status"] == "completed"
    assert abs(manifest["total_cost_usd"] - 0.0042) < 1e-9
    assert manifest["prompt_sha256"]
    assert manifest["entry_script_sha256"], "el manifiesto debe pinnear tambien el script de entrada (no solo prompt/schema)"
    assert manifest["base_gate_sha256"], "el manifiesto debe pinnear tambien el gate base"
    assert manifest["schema_sha256"]
    assert "run_id" in manifest and "started_at" in manifest and "finished_at" in manifest

    errors_path = output_path.with_name(output_path.stem + ".errors.jsonl")
    error_lines = [json.loads(l) for l in errors_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert error_lines[0]["run_id"] == manifest["run_id"], "los errores deben llevar el run_id de la corrida que los genero"


def test_cost_of_a_schema_validation_failure_is_not_lost(tmp_path, monkeypatch):
    """Autoauditoria 2026-09-16: un fallo de schema_validation ocurre
    DESPUES de una llamada exitosa con costo real ya incurrido -- ese costo
    no debe desaparecer del manifiesto ni de errors.jsonl."""
    output_path = tmp_path / "classifications.jsonl"
    docs = _fake_docs(1)
    _patch_common(monkeypatch, tmp_path, docs, output_path)

    monkeypatch.setattr(target.v51, "classify_document", lambda *a, **k: {
        "error": "schema_validation_failed", "usage": {"cost": 0.0071},
    })
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("\n".join(d["url"] for d in docs), encoding="utf-8")
    args = argparse.Namespace(limit=0, dry_run=False, urls_file=str(urls_file), output_file=str(output_path), workers=1)
    target._run(args)

    errors_path = output_path.with_name(output_path.stem + ".errors.jsonl")
    error_lines = [json.loads(l) for l in errors_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert abs(error_lines[0]["cost_incurred_usd"] - 0.0071) < 1e-9
    assert error_lines[0].get("run_id"), "cada entrada de error debe llevar el run_id de la corrida"

    manifests = list(tmp_path.glob("classifications.run_manifest.*.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert abs(manifest["total_cost_usd"] - 0.0071) < 1e-9, "el costo del fallo debe sumarse al total del manifiesto"
    assert error_lines[0]["run_id"] == manifest["run_id"]
