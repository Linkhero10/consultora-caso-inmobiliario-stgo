#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Filtro de alcance con un modelo de decision (Jev, via OpenRouter): ¿esto es una disputa real, inmobiliaria/urbana?

La validacion ciega de extremo a extremo mostro que el error grave del producto es sobre todo de ALCANCE: disputa
inexistente (el proyecto solo se nombra en una lista o como ejemplo) o tema fuera del estudio. Eso es clasificacion con
opciones fijas, no extraccion: un modelo de decision (Jev) responde preguntas tipadas (noul / choice / score) con
probabilidades y no genera texto. NO sirve para extraer citas ni nombres; la extraccion sigue siendo del LLM.

Este modulo:
- construye, para un conflicto (o una mencion), un `state` acotado (nombre del proyecto, titulo y fragmentos del texto
  alrededor de cada mencion) y tres preguntas tipadas (`QUESTIONS`);
- llama al endpoint de chat de Requesty (`/v1/chat/completions`, modelo versionado `typesafe/jev-1.13.0`, formato de
  respuesta `questions`; ~US$0,04 por millon de tokens de entrada) con la clave `REQUESTY_API_KEY` de la extraccion;
- aplica una regla de decision con umbrales EXPLICITOS (`RULE`), que son hipotesis a calibrar, no verdad;
- evalua contra los veredictos de la validacion ciega (`--eval-blind`).

Guardrails (como `enrich.py`): sin `--confirm-paid-run` solo hay ensayo (cuenta unidades y estima costo; no llama a la
API); `--max-cost-usd` es obligatorio en una corrida pagada; cada respuesta se guarda (cache) para no pagar dos veces.

    python src/scope_jev.py --eval-blind                                  # ensayo: costo estimado
    python src/scope_jev.py --eval-blind --confirm-paid-run --max-cost-usd 0.50 --workers 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrichment_core import ENV_PATH, find_content_path, load_env  # noqa: E402
from paths import INTERMEDIATE_DIR, PROJECT_ROOT, REVIEW_SAMPLES_DIR  # noqa: E402

logger = logging.getLogger("scope_jev")

ENDPOINT = "https://router.requesty.ai/v1/chat/completions"
MODEL = "typesafe/jev-1.13.0"  # version fija, no un alias: el comportamiento no debe cambiar entre corridas
ENV_KEY = "REQUESTY_API_KEY"
PRICE_PER_INPUT_TOKEN_USD = 0.04 / 1_000_000
CHARS_PER_TOKEN = 3.5  # estimacion conservadora para espanol
MAX_STATE_CHARS = 60_000  # ~17k tokens: bien bajo el limite de 32k de estado + preguntas
SNIPPET_RADIUS = 900  # caracteres a cada lado de cada mencion del proyecto
MAX_SNIPPETS_PER_DOC = 4
MAX_DOCS_PER_UNIT = 3
SCOPE_DIR = INTERMEDIATE_DIR / "scope"
DECISIONS_PATH = PROJECT_ROOT / "config" / "conflict_scope_decisions.json"

TOPICS = {
    "inmobiliario_urbano": "Proyectos de vivienda o inmobiliarios, densidad o altura, permisos de edificacion, planes reguladores, patrimonio urbano, suelo urbano, DS19/vivienda social, tomas o campamentos como problema de suelo y vivienda.",
    "infraestructura_energia_ambiental": "Oleoductos, lineas de transmision, plantas de tratamiento, rellenos, centros logisticos o industriales y otros conflictos ambientales o de infraestructura sin componente de vivienda o suelo urbano.",
    "consumo_comercio_servicios": "Reclamos de consumo, contratos, patentes comerciales o de alcohol, quiebras, fraudes, locales comerciales.",
    "seguridad_orden_publico": "Delincuencia, narcotrafico, desalojos o demoliciones por seguridad, vandalismo, espacio publico por seguridad.",
    "otro": "Cualquier otro tema.",
}

QUESTIONS: dict[str, dict[str, Any]] = {
    "disputa_concreta": {
        "type": "noul",
        "instructions": "En los fragmentos, ¿se describe una disputa, reclamo, litigio, denuncia, oposicion o fallo concretos que afectan al proyecto o inmueble indicado en `proyecto`?",
        "criteria": {
            "true": "El texto cuenta una controversia concreta sobre ESE proyecto o inmueble: quien reclama, que se disputa, o una decision de una autoridad o tribunal sobre el.",
            "false": "El proyecto solo se nombra: en una lista, como ejemplo o comparacion, como direccion o calle, o como contexto de otro asunto.",
        },
    },
    "tema": {
        "type": "choice",
        "instructions": "¿Cual es el tema de la disputa que afecta al proyecto indicado?",
        "criteria": TOPICS,
    },
    "foco": {
        "type": "choice",
        "instructions": "¿Que lugar ocupa el proyecto indicado en los textos?",
        "criteria": {
            "principal": "Es el asunto central del texto.",
            "secundario": "Es uno de varios asuntos tratados con cierto detalle.",
            "mencion_de_paso": "Aparece nombrado sin desarrollo (lista, ejemplo, direccion).",
        },
    },
}

# Regla de decision: HIPOTESIS a calibrar con datos etiquetados (ver `--eval-blind`), no una verdad.
RULE = {"min_disputa": 0.5, "tema": "inmobiliario_urbano", "foco_excluido": "mencion_de_paso"}


def decide(answers: dict[str, Any], rule: dict[str, Any] = RULE) -> dict[str, Any]:
    """Aplica la regla de alcance a las respuestas del modelo. Devuelve {'pasa': bool, 'motivos': [...]}."""
    motivos = []
    disputa = answers.get("disputa_concreta", {}).get("noul")
    tema = answers.get("tema", {}).get("choice")
    foco = answers.get("foco", {}).get("choice")
    if disputa is None or disputa < rule["min_disputa"]:
        motivos.append("sin_disputa_concreta")
    if tema != rule["tema"]:
        motivos.append(f"tema:{tema}")
    if foco == rule["foco_excluido"]:
        motivos.append("mencion_de_paso")
    return {"pasa": not motivos, "motivos": motivos}


def snippets(text: str, name: str) -> list[str]:
    """Fragmentos del texto alrededor de las apariciones del nombre; si no aparece, el inicio del texto."""
    found = []
    last_end = -1
    for match in re.finditer(re.escape(name), text, flags=re.IGNORECASE):
        if match.start() < last_end:
            continue
        start, end = max(0, match.start() - SNIPPET_RADIUS), min(len(text), match.end() + SNIPPET_RADIUS)
        found.append(text[start:end].replace("\n", " "))
        last_end = end
        if len(found) >= MAX_SNIPPETS_PER_DOC:
            break
    return found or [text[: 2 * SNIPPET_RADIUS].replace("\n", " ")]


def build_state(project: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    """`documents`: [{'title', 'text', 'role'}]. Los focales primero; acotado a MAX_STATE_CHARS."""
    ordered = sorted(documents, key=lambda d: 0 if d.get("role") in ("focal", "co_focal") else 1)[:MAX_DOCS_PER_UNIT]
    state = {"proyecto": project, "documentos": [
        {"titulo": d.get("title", ""), "fragmentos": snippets(d.get("text", ""), project)} for d in ordered
    ]}
    while len(json.dumps(state, ensure_ascii=False)) > MAX_STATE_CHARS and state["documentos"][-1]["fragmentos"]:
        state["documentos"][-1]["fragmentos"].pop()
    return state


def estimate_cost_usd(state: dict[str, Any]) -> float:
    chars = len(json.dumps(state, ensure_ascii=False)) + len(json.dumps(QUESTIONS, ensure_ascii=False))
    return chars / CHARS_PER_TOKEN * PRICE_PER_INPUT_TOKEN_USD


def call_jev(state: dict[str, Any], api_key: str, sleep=time.sleep, max_retries: int = 4) -> dict[str, Any]:
    """Una llamada con reintentos ante 429/5xx/red. Devuelve {'answers', 'cost'} o {'error', 'cost'}.

    Requesty expone Jev como chat: el estado va como JSON en el mensaje del usuario, las preguntas en
    `response_format` (type `questions`) y las respuestas vuelven como JSON dentro del mensaje del asistente."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": json.dumps(state, ensure_ascii=False)}],
        "response_format": {"type": "questions", "questions": QUESTIONS},
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(ENDPOINT, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                                 json=payload, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == max_retries:
                    return {"error": f"http_{resp.status_code}", "cost": 0.0}
                sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            answers = json.loads(data["choices"][0]["message"]["content"])
            if not isinstance(answers, dict) or "disputa_concreta" not in answers:
                return {"error": "respuesta_sin_las_preguntas", "cost": float((data.get("usage") or {}).get("cost") or 0.0)}
            return {"answers": answers, "cost": float((data.get("usage") or {}).get("cost") or 0.0), "model": data.get("model")}
        except requests.exceptions.RequestException as exc:
            if attempt == max_retries:
                return {"error": f"conexion: {exc}"[:200], "cost": 0.0}
            sleep(2 ** attempt)
        except (KeyError, IndexError, ValueError) as exc:
            return {"error": f"respuesta_inesperada: {exc}"[:200], "cost": 0.0}
    return {"error": "reintentos_agotados", "cost": 0.0}


def _load_blind_units(sample_dir: Path | None = None) -> list[dict[str, Any]]:
    """Unidades de la validacion ciega: un conflicto = un proyecto (el primero) y sus documentos con texto completo."""
    sample_dir = sample_dir or REVIEW_SAMPLES_DIR / "blind_validation"
    verdicts = {v["conflict_id"]: v for v in json.loads((sample_dir / "verdicts.json").read_text(encoding="utf-8"))["verdicts"]}
    units = []
    for name in ("sample_main", "sample_stress"):
        if not (sample_dir / f"{name}.json").exists():
            continue
        for conflict in json.loads((sample_dir / f"{name}.json").read_text(encoding="utf-8")):
            docs = []
            for doc in conflict["documents"]:
                if doc.get("content_file"):
                    record = json.loads((PROJECT_ROOT / doc["content_file"]).read_text(encoding="utf-8"))
                    docs.append({"title": doc.get("title") or record.get("title", ""), "text": record.get("text", ""), "role": doc["role"]})
            units.append({
                "unit_id": conflict["conflict_id"], "project": conflict["label"], "documents": docs,
                "veredicto": verdicts[conflict["conflict_id"]]["veredicto"],
            })
    return units


def evaluate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compara la decision del modelo con el veredicto ciego (solo unidades verificables)."""
    cells = {"pasa_y_correcto_o_menor": 0, "pasa_y_grave": 0, "rechaza_y_grave": 0, "rechaza_y_correcto_o_menor": 0}
    for r in results:
        if r["veredicto"] == "no_verificable" or "decision" not in r:
            continue
        good = r["veredicto"] in ("correcto", "error_menor")
        key = ("pasa" if r["decision"]["pasa"] else "rechaza") + ("_y_correcto_o_menor" if good else "_y_grave")
        cells[key] += 1
    passed, rejected = cells["pasa_y_correcto_o_menor"] + cells["pasa_y_grave"], cells["rechaza_y_grave"] + cells["rechaza_y_correcto_o_menor"]
    good_total = cells["pasa_y_correcto_o_menor"] + cells["rechaza_y_correcto_o_menor"]
    grave_total = cells["pasa_y_grave"] + cells["rechaza_y_grave"]
    return {
        **cells,
        "precision_de_lo_que_pasa": round(cells["pasa_y_correcto_o_menor"] / passed, 3) if passed else None,
        "error_grave_que_se_filtra": round(cells["rechaza_y_grave"] / grave_total, 3) if grave_total else None,
        "buenos_que_se_pierden": round(cells["rechaza_y_correcto_o_menor"] / good_total, 3) if good_total else None,
    }


def unit_signature(label: str, documents: list[tuple[str, str]]) -> str:
    """Huella de la unidad evaluada, calculable desde el warehouse SIN el corpus: etiqueta + (documento, rol) ordenados.
    Si cambia (otra agrupacion de casos, otro documento, otro rol), la decision guardada deja de aplicar."""
    return hashlib.sha256(json.dumps([label, sorted(documents)], ensure_ascii=False).encode("utf-8")).hexdigest()


def conflict_units(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Una unidad por conflicto: su etiqueta y sus documentos (con texto si hay corpus local). Es la unidad que se valido."""
    units = []
    for conflict_id, label in conn.execute("SELECT conflict_id, label FROM conflict ORDER BY conflict_id").fetchall():
        rows = conn.execute(
            "SELECT dc.document_id, dc.role, d.url, d.title FROM document_conflict dc JOIN document d USING(document_id) "
            "WHERE dc.conflict_id = ? ORDER BY dc.document_id", (conflict_id,)
        ).fetchall()
        docs = []
        for document_id, role, url, title in rows:
            path = find_content_path(url)
            text = json.loads(path.read_text(encoding="utf-8")).get("text", "") if path else ""
            docs.append({"document_id": document_id, "role": role, "title": title or "", "text": text})
        units.append({"unit_id": conflict_id, "project": label, "documents": docs,
                      "signature": unit_signature(label, [(d["document_id"], d["role"]) for d in docs])})
    return units


def classify_conflicts(units: list[dict[str, Any]], previous: dict[str, dict], api_key: str, workers: int, max_cost_usd: float) -> tuple[dict[str, dict], float, list]:
    """Llama a Jev para las unidades sin decision vigente (misma firma). Devuelve (decisiones, costo, errores)."""
    decisions = {k: v for k, v in previous.items()}
    pending = [u for u in units if u["documents"] and previous.get(u["unit_id"], {}).get("signature") != u["signature"]
               and any(d["text"] for d in u["documents"])]
    lock, spent, errors = Lock(), {"cost": 0.0}, []

    def work(unit):
        with lock:
            if spent["cost"] >= max_cost_usd:
                return None
        response = call_jev(build_state(unit["project"], unit["documents"]), api_key)
        with lock:
            spent["cost"] += response.get("cost", 0.0)
        if "error" in response:
            errors.append((unit["unit_id"], response["error"]))
            return None
        a = response["answers"]
        return unit["unit_id"], {
            "signature": unit["signature"], "disputa": a["disputa_concreta"]["noul"],
            "tema": a["tema"]["choice"], "tema_confianza": a["tema"].get("confidence"),
            "foco": a["foco"]["choice"], "foco_confianza": a["foco"].get("confidence"),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(work, pending):
            if result:
                decisions[result[0]] = result[1]
    return decisions, spent["cost"], errors


def answers_from_decision(entry: dict[str, Any]) -> dict[str, Any]:
    """Reconstruye el formato de respuestas que espera `decide` desde una decision guardada."""
    return {"disputa_concreta": {"noul": entry["disputa"]}, "tema": {"choice": entry["tema"]}, "foco": {"choice": entry["foco"]}}


def main_classify_conflicts(args) -> int:
    conn = sqlite3.connect(f"file:{(PROJECT_ROOT / 'data' / 'warehouse.sqlite').as_posix()}?mode=ro", uri=True)
    units = conflict_units(conn)
    conn.close()
    previous = {}
    if DECISIONS_PATH.exists():
        previous = {e["conflict_id"]: e for e in json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))["decisions"]}
    pending = [u for u in units if u["documents"] and previous.get(u["unit_id"], {}).get("signature") != u["signature"]
               and any(d["text"] for d in u["documents"])]
    estimate = sum(estimate_cost_usd(build_state(u["project"], u["documents"])) for u in pending)
    logger.info("Conflictos: %d | con decision vigente: %d | pendientes: %d | costo estimado: US$%.4f",
                len(units), len(previous), len(pending), estimate)
    if not args.confirm_paid_run:
        logger.info("ENSAYO: no se llamo a ninguna API. Para ejecutar: --confirm-paid-run --max-cost-usd <tope>.")
        return 0
    if args.max_cost_usd is None:
        logger.error("--max-cost-usd es obligatorio en una corrida pagada")
        return 1
    api_key = load_env(ENV_PATH).get(ENV_KEY, "")
    if not api_key:
        logger.error("%s vacia", ENV_KEY)
        return 1
    live_ids = {u["unit_id"] for u in units}
    previous = {k: v for k, v in previous.items() if k in live_ids}  # descarta decisiones de conflictos que ya no existen
    decisions, cost, errors = classify_conflicts(units, {k: {**v, "signature": v["signature"]} for k, v in previous.items()}, api_key, args.workers, args.max_cost_usd)
    for unit_id, error in errors:
        logger.warning("Fallo %s: %s", unit_id[-8:], error)
    payload = {
        "schema_version": "conflict_scope_decisions",
        "description": "Respuestas del modelo de decision (disputa concreta, tema, foco) por conflicto. La regla que las convierte en 'aprobado'/'rechazado' vive en el codigo (RULE) y se aplica al construir, asi que cambiarla no exige volver a llamar a la API. Cada entrada lleva la firma de su unidad: si cambia la agrupacion o los documentos, deja de aplicar.",
        "model": MODEL,
        "decisions": [{"conflict_id": k, **v} for k, v in sorted(decisions.items())],
    }
    DECISIONS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    logger.info("Decisiones: %d | costo de esta corrida: US$%.5f | errores: %d", len(decisions), cost, len(errors))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--eval-blind", action="store_true", help="evalua contra los veredictos de una validacion ciega")
    parser.add_argument("--classify-conflicts", action="store_true", help="decide el alcance de todos los conflictos del warehouse y escribe config/conflict_scope_decisions.json")
    parser.add_argument("--sample-dir", type=Path, default=None, help="carpeta de la muestra (por defecto, blind_validation)")
    parser.add_argument("--confirm-paid-run", action="store_true", help="autoriza llamadas reales (pagadas) a la API")
    parser.add_argument("--max-cost-usd", type=float, default=None)
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args(argv)
    if not (args.eval_blind or args.classify_conflicts):
        parser.error("indica --eval-blind o --classify-conflicts")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    if args.classify_conflicts:
        return main_classify_conflicts(args)

    sample_dir = args.sample_dir or REVIEW_SAMPLES_DIR / "blind_validation"
    units = _load_blind_units(sample_dir)
    states = {u["unit_id"]: build_state(u["project"], u["documents"]) for u in units if u["documents"]}
    estimate = sum(estimate_cost_usd(s) for s in states.values())
    logger.info("Unidades: %d (con texto: %d) | costo estimado: US$%.4f", len(units), len(states), estimate)
    if not args.confirm_paid_run:
        logger.info("ENSAYO: no se llamo a ninguna API. Para ejecutar: --confirm-paid-run --max-cost-usd <tope>.")
        return 0
    if args.max_cost_usd is None:
        logger.error("--max-cost-usd es obligatorio en una corrida pagada")
        return 1
    api_key = load_env(ENV_PATH).get(ENV_KEY, "")
    if not api_key:
        logger.error("%s vacia", ENV_KEY)
        return 1

    SCOPE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = SCOPE_DIR / f"{sample_dir.name}_cache.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                cache[row["unit_id"]] = row
    pending = [u for u in units if u["unit_id"] in states and u["unit_id"] not in cache]
    lock, spent, errors = Lock(), {"cost": 0.0}, []

    def work(unit):
        # el tope se revisa antes de someter cada unidad: lo ya en vuelo termina igual
        with lock:
            if spent["cost"] >= args.max_cost_usd:
                return None
        response = call_jev(states[unit["unit_id"]], api_key)
        with lock:
            spent["cost"] += response.get("cost", 0.0)
        if "error" in response:
            errors.append((unit["unit_id"], response["error"]))
            return None
        return {"unit_id": unit["unit_id"], "answers": response["answers"], "cost": response["cost"], "model": response.get("model")}

    with cache_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(work, pending):
            if row is not None:
                cache[row["unit_id"]] = row
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
    for unit_id, error in errors:
        logger.warning("Fallo %s: %s", unit_id[-8:], error)
    results = [
        {"unit_id": u["unit_id"], "veredicto": u["veredicto"], "decision": decide(cache[u["unit_id"]]["answers"])}
        for u in units if u["unit_id"] in cache
    ]
    report = {"modelo": MODEL, "regla": RULE, "costo_usd_de_esta_corrida": round(spent["cost"], 6), "n": len(results),
              "errores": len(errors), **evaluate(results)}
    (SCOPE_DIR / f"{sample_dir.name}_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
