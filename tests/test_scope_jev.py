"""Filtro de alcance con Jev: estado acotado, regla de decision, reintentos y ensayo sin gasto. Sin llamadas reales."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import scope_jev as sj  # noqa: E402


def _answers(disputa=0.9, tema="inmobiliario_urbano", foco="principal"):
    return {"disputa_concreta": {"type": "noul", "noul": disputa}, "tema": {"type": "choice", "choice": tema},
            "foco": {"type": "choice", "choice": foco}}


def test_decision_rule_requires_dispute_topic_and_focus():
    assert sj.decide(_answers())["pasa"] is True
    assert sj.decide(_answers(disputa=0.2))["motivos"] == ["sin_disputa_concreta"]
    assert sj.decide(_answers(tema="consumo_comercio_servicios"))["motivos"] == ["tema:consumo_comercio_servicios"]
    assert sj.decide(_answers(foco="mencion_de_paso"))["motivos"] == ["mencion_de_paso"]
    assert sj.decide({})["pasa"] is False


def test_questions_follow_the_endpoint_schema():
    q = sj.QUESTIONS
    assert q["disputa_concreta"]["type"] == "noul" and set(q["disputa_concreta"]["criteria"]) == {"true", "false"}
    assert q["tema"]["type"] == "choice" and "inmobiliario_urbano" in q["tema"]["criteria"]
    assert q["foco"]["type"] == "choice" and "mencion_de_paso" in q["foco"]["criteria"]


def test_state_is_bounded_and_puts_focal_documents_first():
    big = "relleno " * 20000 + " Torre Alfa " + "relleno " * 20000
    docs = [{"title": "otro", "text": big, "role": "mentioned_unreviewed"}, {"title": "foco", "text": "La Torre Alfa fue impugnada.", "role": "focal"}]
    state = sj.build_state("Torre Alfa", docs)
    assert state["documentos"][0]["titulo"] == "foco"
    assert len(__import__("json").dumps(state, ensure_ascii=False)) <= sj.MAX_STATE_CHARS
    assert sj.snippets("sin el nombre", "Zeta")[0].startswith("sin el nombre")


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sj.requests.exceptions.HTTPError(str(self.status_code))

    def json(self):
        return self._body


def test_call_retries_rate_limit_and_reads_cost(monkeypatch):
    seq = iter([_Resp(429), _Resp(200, {"answers": _answers(), "usage": {"cost": 0.00002}, "model": "typesafe/jev-1.13-x"})])
    monkeypatch.setattr(sj.requests, "post", lambda *a, **k: next(seq))
    out = sj.call_jev({"proyecto": "x"}, "key", sleep=lambda s: None)
    assert out["cost"] == pytest.approx(0.00002) and "answers" in out


def test_call_reports_unexpected_shape_and_persistent_failure(monkeypatch):
    monkeypatch.setattr(sj.requests, "post", lambda *a, **k: _Resp(200, {"sin": "answers"}))
    assert sj.call_jev({}, "key", sleep=lambda s: None)["error"].startswith("respuesta_inesperada")
    monkeypatch.setattr(sj.requests, "post", lambda *a, **k: _Resp(503))
    assert sj.call_jev({}, "key", sleep=lambda s: None, max_retries=1)["error"] == "http_503"


def test_evaluation_counts_the_four_cells():
    rows = [
        {"veredicto": "correcto", "decision": {"pasa": True}},
        {"veredicto": "error_grave", "decision": {"pasa": True}},
        {"veredicto": "error_grave", "decision": {"pasa": False}},
        {"veredicto": "error_menor", "decision": {"pasa": False}},
        {"veredicto": "no_verificable", "decision": {"pasa": True}},
    ]
    out = sj.evaluate(rows)
    assert (out["pasa_y_correcto_o_menor"], out["pasa_y_grave"], out["rechaza_y_grave"], out["rechaza_y_correcto_o_menor"]) == (1, 1, 1, 1)
    assert out["precision_de_lo_que_pasa"] == 0.5 and out["error_grave_que_se_filtra"] == 0.5


def test_dry_run_never_calls_the_api(monkeypatch):
    monkeypatch.setattr(sj, "_load_blind_units", lambda: [{"unit_id": "u", "project": "P", "documents": [{"title": "t", "text": "P texto", "role": "focal"}], "veredicto": "correcto"}])
    monkeypatch.setattr(sj.requests, "post", lambda *a, **k: pytest.fail("un ensayo no debe llamar a la API"))
    assert sj.main(["--eval-blind"]) == 0
    assert sj.main(["--eval-blind", "--confirm-paid-run"]) == 1  # sin tope de gasto no corre
