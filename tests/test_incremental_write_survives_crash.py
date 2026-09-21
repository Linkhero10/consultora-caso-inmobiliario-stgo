"""Persistencia incremental de resultados (2026-09-16, hallazgo de auditoria
de punta a punta antes de la primera corrida de produccion real a escala,
3835 documentos): antes, todos los registros se acumulaban en memoria y se
escribian recien al terminar el ThreadPoolExecutor completo -- un crash,
corte de red o kill a mitad de la corrida perdia TODOS los resultados ya
pagados. Esta prueba simula un fallo a mitad de la corrida (postprocess_result
lanza una excepcion en el segundo documento) y confirma dos cosas: (a) el
primer resultado, ya clasificado y pagado, sobrevive en disco, y (b) el
fallo del segundo se registra en errors.jsonl en vez de abortar la corrida
sin dejar rastro (fix del punto 4 de una ronda posterior de Codex/Luna)."""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src" / "_classify_pipeline"
sys.path.insert(0, str(SCRIPT_DIR))

import classify_v5_2_1 as target  # noqa: E402


def _fake_docs():
    return [
        {"url": "https://example.cl/uno", "text": "contenido uno", "lineage": {}},
        {"url": "https://example.cl/dos", "text": "contenido dos", "lineage": {}},
    ]


def test_first_record_persists_and_second_failure_is_logged_not_swallowed(tmp_path, monkeypatch):
    output_path = tmp_path / "classifications.jsonl"

    fake_schema = tmp_path / "fake_schema.json"
    fake_schema.write_text("{}", encoding="utf-8")
    fake_prompt = tmp_path / "fake_prompt.md"
    fake_prompt.write_text("prompt", encoding="utf-8")
    monkeypatch.setattr(target.v51, "load_env", lambda _path: {"OPENROUTER_API_KEY": "fake-key"})
    monkeypatch.setattr(target.v51, "load_classifiable_documents", lambda urls_filter=None: _fake_docs())
    monkeypatch.setattr(target.v51, "already_classified_urls", lambda _path: set())
    monkeypatch.setattr(target, "SCHEMA_PATH", fake_schema)
    monkeypatch.setattr(target, "PROMPT_PATH", fake_prompt)

    def fake_classify_document(doc, api_key, prompt, schema):
        return {"parsed": {"url": doc["url"]}, "usage": {}, "reasoning": None, "reasoning_details": None}

    monkeypatch.setattr(target.v51, "classify_document", fake_classify_document)

    call_count = {"n": 0}

    def crashing_postprocess_result(doc, result):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("fallo simulado a mitad de la corrida")
        return "include", {"url": doc["url"], "decision_documento": "include"}

    monkeypatch.setattr(target, "postprocess_result", crashing_postprocess_result)

    # urls_file acotado (bajo MAX_TEST_URLS_WITHOUT_GATE) para que is_test=True
    # de forma explicita -- --output-file solo ya no activa el modo prueba
    # (fix 2026-09-16, hallazgo de Codex/Luna: --output-file no acota alcance).
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("\n".join(d["url"] for d in _fake_docs()), encoding="utf-8")
    args = argparse.Namespace(limit=0, dry_run=False, urls_file=str(urls_file), output_file=str(output_path), workers=1)

    result_code = target._run(args)

    assert result_code == 0, "un fallo de postprocesamiento en un documento ya NO debe abortar toda la corrida"
    assert output_path.exists()
    lines = [json.loads(l) for l in output_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1, "el resultado exitoso debe quedar escrito"

    errors_path = output_path.with_name(output_path.stem + ".errors.jsonl")
    assert errors_path.exists(), "el fallo de postprocesamiento debe quedar registrado en errors.jsonl, no perderse en silencio"
    error_lines = [json.loads(l) for l in errors_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(error_lines) == 1
    assert "postprocess_result_exception" in error_lines[0]["error"]
