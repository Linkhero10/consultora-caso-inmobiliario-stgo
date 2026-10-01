"""Pruebas del nucleo de extraccion por LLM (`enrichment_core.py`) y del ejecutor (`enrich.py`).

Ninguna llama a una API: el cliente HTTP se reemplaza por respuestas sinteticas.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import enrichment_core as core  # noqa: E402
import enrichment_source as source  # noqa: E402
import enrich  # noqa: E402


def _record():
    return {
        "url": "https://example.cl/multi",
        "nombre_proyecto": "Proyecto A",
        "proyectos_mencionados": [
            {"nombre": "Proyecto A", "case_mention_index": 0},
            {"nombre": "Proyecto B", "case_mention_index": None},
        ],
        "evidencia_objeto_disputa": "permiso de edificación de Proyecto A",
        "evidencia_objeto_disputa_verificada": True,
        "actores": [{
            "nombre": "Vecinos", "cita": "Vecinos demandaron a Proyecto A", "cita_verificada": True,
            "proyecto_asociado": "Proyecto A",
        }],
        "instituciones_mencionadas": [{
            "nombre": "Municipio", "cita": "Municipio revisó el permiso de Proyecto B", "cita_verificada": True,
            "proyecto_asociado": "Proyecto B",
        }],
        "linea_tiempo": [{
            "fecha": "2024", "descripcion": "Se impugnó el permiso de Proyecto A",
            "evidencia_hito": "En 2024 se impugnó el permiso de Proyecto A", "evidencia_hito_verificada": True,
            "fecha_year_grounded": True, "proyecto_asociado": "Proyecto A",
        }],
        "revision": {"nivel": "ninguno", "campos_afectados": [], "motivo": ""},
    }


# --- contexto entregado al modelo ------------------------------------------------------------

def test_context_block_lists_case_mentions_with_index_objeto_comuna_decision():
    case = {"case_mentions": [
        {"tipo_objeto_raw": "construccion de dos torres de 38 pisos",
         "evidencia_objeto_quotes": ["la construccion de dos torres de 38 pisos con mas de mil departamentos"],
         "comuna": "Estacion Central", "decision": "include"},
        {"tipo_objeto_raw": "", "evidencia_objeto_quotes": [], "comuna": "Estacion Central", "decision": "exclude"},
    ]}
    block = core.case_mentions_context_block(case)
    assert "[0]" in block and "[1]" in block
    assert "construccion de dos torres de 38 pisos" in block
    assert "comuna=Estacion Central" in block
    assert "decision=include" in block and "decision=exclude" in block


def test_context_block_handles_no_case_mentions():
    assert "ninguna" in core.case_mentions_context_block({"case_mentions": []}).lower()


# --- saneamiento del indice de case_mention --------------------------------------------------

def _parsed(index):
    return {"proyectos_mencionados": [{"nombre": "Torre A", "case_mention_index": index}],
            "actores": [], "instituciones_mencionadas": [], "linea_tiempo": []}


def test_sanitize_keeps_valid_index_and_marks_it_verified():
    item = core.sanitize_project_associations(_parsed(0), n_case_mentions=2)["proyectos_mencionados"][0]
    assert item["case_mention_index"] == 0 and item["case_mention_index_verificada"] is True


@pytest.mark.parametrize("bad_index", [5, -1, True])
def test_sanitize_clears_out_of_range_index_but_preserves_the_model_value(bad_index):
    item = core.sanitize_project_associations(_parsed(bad_index), n_case_mentions=2)["proyectos_mencionados"][0]
    assert item["case_mention_index"] is None
    assert item["case_mention_index_original_modelo"] == bad_index
    assert item["case_mention_index_verificada"] is False


def test_sanitize_null_index_stays_null_and_unverified():
    item = core.sanitize_project_associations(_parsed(None), n_case_mentions=3)["proyectos_mencionados"][0]
    assert item["case_mention_index"] is None
    assert "case_mention_index_original_modelo" not in item
    assert item["case_mention_index_verificada"] is False


# --- proyecto_asociado: se corrige, no se descarta el registro -------------------------------

def test_project_associations_are_sanitized_not_discarded():
    clean = core.sanitize_project_associations(_record(), n_case_mentions=1)
    assert clean["actores"][0]["proyecto_asociado_verificada"] is True

    bad = _record()
    bad["actores"][0]["proyecto_asociado"] = "Proyecto inexistente"
    sanitized = core.sanitize_project_associations(bad, n_case_mentions=1)
    actor = sanitized["actores"][0]
    assert actor["proyecto_asociado"] == ""
    assert actor["proyecto_asociado_original_modelo"] == "Proyecto inexistente"
    assert actor["proyecto_asociado_verificada"] is False
    assert sanitized["nombre_proyecto"] == bad["nombre_proyecto"]  # el resto del registro sigue intacto
    assert core.validate_record_invariants(sanitized) == []


def test_project_associations_normalize_whitespace_on_match():
    record = _record()
    record["actores"][0]["proyecto_asociado"] = "Proyecto A  "
    actor = core.sanitize_project_associations(record, n_case_mentions=1)["actores"][0]
    assert actor["proyecto_asociado"] == "Proyecto A"
    assert actor["proyecto_asociado_verificada"] is True


def test_semantic_invariants_reject_inconsistent_verified_fields():
    assert core.validate_record_invariants(_record()) == []

    bad_revision = _record()
    bad_revision["revision"] = {"nivel": "ninguno", "campos_afectados": ["actores"], "motivo": "duda"}
    assert any("revision.nivel=ninguno" in e for e in core.validate_record_invariants(bad_revision))

    bad_quote = _record()
    bad_quote["actores"][0]["cita"] = ""
    assert any("cita_verificada=true" in e for e in core.validate_record_invariants(bad_quote))

    bad_hito = _record()
    bad_hito["linea_tiempo"][0]["evidencia_hito"] = ""
    assert any("evidencia_hito_verificada=true" in e for e in core.validate_record_invariants(bad_hito))


# --- verificacion literal de citas ------------------------------------------------------------

def test_literal_quote_is_verified_and_a_fabricated_one_is_emptied_but_preserved():
    text = "Los vecinos demandaron   al Municipio en 2024."
    ok = core.verify_literal_quote_field({"cita": "vecinos demandaron al municipio"}, "cita", text, "t")
    assert ok["cita_verificada"] is True and ok["cita"] == "vecinos demandaron al municipio"
    bad = core.verify_literal_quote_field({"cita": "cita inventada"}, "cita", text, "t")
    assert bad["cita_verificada"] is False and bad["cita"] == "" and bad["cita_original_modelo"] == "cita inventada"


def test_timeline_year_must_appear_as_a_whole_word_in_the_text():
    hitos = [{"fecha": "2024", "evidencia_hito": ""}, {"fecha": "26 de julio", "evidencia_hito": ""}]
    out = core.verify_timeline_descriptions(hitos, "Ocurrio en 2024 y nada mas.")
    assert out[0]["fecha_year_grounded"] is True
    assert out[1]["fecha_year_grounded"] is False


def test_truncation_flag_only_when_array_reaches_max_items():
    schema = {"properties": {"actores": {"maxItems": 2}, "instituciones_mencionadas": {"maxItems": 3}, "linea_tiempo": {"maxItems": 5}}}
    flags = core.compute_truncation_flags({"actores": [1, 2], "instituciones_mencionadas": [1], "linea_tiempo": []}, schema)
    assert flags == {"actores_posiblemente_truncados": True, "instituciones_posiblemente_truncadas": False,
                     "hitos_posiblemente_truncados": False}


# --- cliente HTTP: contabilidad de costo y reintentos ------------------------------------------

class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise core.requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        return self._body


def _ok_body(content, cost=0.01):
    return {"usage": {"cost": cost}, "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


SCHEMA = {"schema": {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}}
CASE = {"url": "https://example.cl/x", "_text": "texto", "_title": "t", "decision_documento": "include", "case_mentions": []}


def _run_with(monkeypatch, responses):
    calls = iter(responses)
    monkeypatch.setattr(core.requests, "post", lambda *a, **k: next(calls))
    return core.enrich_document(CASE, "key", "prompt", SCHEMA, sleep=lambda s: None)


def test_enrich_document_returns_parsed_payload_and_cost(monkeypatch):
    result = _run_with(monkeypatch, [_Resp(200, _ok_body('{"a": 1}'))])
    assert result["parsed"] == {"a": 1}
    assert result["total_incurred_cost_usd"] == pytest.approx(0.01)
    assert result["paid_attempt_count"] == 1 and result["request_attempt_count"] == 1


def test_enrich_document_retries_malformed_json_and_accumulates_the_paid_cost(monkeypatch):
    result = _run_with(monkeypatch, [_Resp(200, _ok_body("no es json", cost=0.02)), _Resp(200, _ok_body('{"a": 2}', cost=0.03))])
    assert result["parsed"] == {"a": 2}
    assert result["total_incurred_cost_usd"] == pytest.approx(0.05)
    assert result["retry_cost_usd"] == pytest.approx(0.02)
    assert result["paid_attempt_count"] == 2


def test_enrich_document_does_not_retry_a_schema_violation_and_keeps_the_paid_response(monkeypatch):
    result = _run_with(monkeypatch, [_Resp(200, _ok_body('{"a": "no entero"}', cost=0.04))])
    assert result["error"].startswith("schema_validation_failed")
    assert result["total_incurred_cost_usd"] == pytest.approx(0.04)
    assert result["raw_content_on_failure"] == '{"a": "no entero"}'


def test_enrich_document_retries_429_without_charging(monkeypatch):
    result = _run_with(monkeypatch, [_Resp(429), _Resp(200, _ok_body('{"a": 3}'))])
    assert result["parsed"] == {"a": 3}
    assert result["paid_attempt_count"] == 1 and result["request_attempt_count"] == 2


def test_enrich_document_estimates_cost_when_the_provider_omits_it(monkeypatch):
    body = {"usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
            "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]}
    result = _run_with(monkeypatch, [_Resp(200, body)])
    assert result["total_incurred_cost_usd"] == pytest.approx(0.60)


# --- registro final y guardrails del ejecutor ---------------------------------------------------

def test_process_document_quarantines_a_record_that_breaks_its_contract():
    case = dict(CASE, _text="Vecinos demandaron a Proyecto A.")
    parsed = _record()
    parsed.pop("url")  # la respuesta del modelo no trae la URL: la agrega el postproceso
    result = {"parsed": parsed, "total_incurred_cost_usd": 0.01}
    record_schema = {"type": "object", "required": ["campo_que_no_existe"]}
    hashes = {"prompt": "p", "schema": "s", "record_schema": "r"}
    outcome = core.process_document(case, result, record_schema, {"properties": {}}, "run", "xhigh", "1.0", "now", hashes)
    assert outcome["status"] == "invalid"
    assert outcome["record"]["url"] == CASE["url"]  # la respuesta pagada se conserva integra


def test_universe_is_restricted_to_relevant_documents_in_scope(tmp_path, monkeypatch):
    classifications = tmp_path / "classifications.jsonl"
    rows = [
        {"url": "https://a", "decision_documento": "include", "corpus_scope": enrich.EXPECTED_CORPUS_SCOPE},
        {"url": "https://b", "decision_documento": "exclude", "corpus_scope": enrich.EXPECTED_CORPUS_SCOPE},
        {"url": "https://c", "decision_documento": "include", "corpus_scope": "otro_alcance"},
    ]
    classifications.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setattr(enrich, "CLASSIFICATIONS_PATH", classifications)
    monkeypatch.setattr(enrich, "find_content_path", lambda url: None)
    assert enrich.load_cases(None) == []  # sin texto completo no hay caso; los excluidos ni siquiera se consultan


def test_urls_file_rejects_duplicates_and_bad_shapes(tmp_path):
    path = tmp_path / "urls.json"
    path.write_text(json.dumps({"urls": ["https://a", "https://a"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicados"):
        enrich.load_urls_file(path)
    path.write_text(json.dumps({"urls": "no es lista"}), encoding="utf-8")
    with pytest.raises(ValueError, match="lista"):
        enrich.load_urls_file(path)
    path.write_text(json.dumps(["https://a", "https://b"]), encoding="utf-8")
    assert enrich.load_urls_file(path) == ["https://a", "https://b"]


def test_dry_run_never_calls_the_api(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "load_cases", lambda urls: [{"url": "https://a"}])
    monkeypatch.setattr(enrich, "enriched_urls_in_all_runs", lambda: set())
    monkeypatch.setattr(enrich, "ENRICHMENT_DIR", tmp_path)
    monkeypatch.setattr(core.requests, "post", lambda *a, **k: pytest.fail("un ensayo no debe llamar a la API"))
    args = enrich.argparse.Namespace(urls_file=None, run_name="t", confirm_paid_run=False, max_cost_usd=None,
                                     provider="openrouter", workers=1, effort="xhigh")
    assert enrich.run(args) == 0
    assert not (tmp_path / "t").exists()


def test_paid_run_requires_an_explicit_spending_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "load_cases", lambda urls: [])
    monkeypatch.setattr(enrich, "enriched_urls_in_all_runs", lambda: set())
    monkeypatch.setattr(enrich, "ENRICHMENT_DIR", tmp_path)
    args = enrich.argparse.Namespace(urls_file=None, run_name="t", confirm_paid_run=True, max_cost_usd=None,
                                     provider="openrouter", workers=1, effort="xhigh")
    assert enrich.run(args) == 1


# --- fuente unica de lectura -------------------------------------------------------------------

def test_records_from_two_runs_must_be_disjoint(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text(json.dumps({"url": "https://x"}) + "\n", encoding="utf-8")
    b.write_text(json.dumps({"url": "https://x"}) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="duplicada"):
        source.load_enrichment_records(files=[a, b])
    b.write_text(json.dumps({"url": "https://y"}) + "\n", encoding="utf-8")
    assert set(source.load_enrichment_records(files=[a, b])) == {"https://x", "https://y"}


def test_excluded_urls_are_left_out_unless_requested(tmp_path):
    url = next(iter(source.EXCLUDED_URLS))
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps({"url": url}) + "\n" + json.dumps({"url": "https://y"}) + "\n", encoding="utf-8")
    assert set(source.load_enrichment_records(files=[path])) == {"https://y"}
    assert set(source.load_enrichment_records(include_excluded=True, files=[path])) == {url, "https://y"}


def test_persisted_record_contract_requires_its_own_hashes():
    schema = json.loads((PROJECT_ROOT / "config" / "enrichment_record_schema.json").read_text(encoding="utf-8"))
    assert {"prompt_sha256", "schema_sha256"} <= set(schema["required"])
