#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escalamiento v3.3 (2026-09-24): procesa el resto del universo real de 330
documentos (>1 case_mention, >=1 proyecto) tras piloto (8) + calibracion (75),
ya con GO de la revision ciega de Sol (ver
audit/calibracion_v3_3_revision_sol_cruce_2026-09-24.json).

Mismo modelo, mismo esfuerzo, mismo schema/prompt que el piloto y la
calibracion -- ningun parametro de calidad cambia. La UNICA diferencia real
es un limite de gasto explicito (--max-cost-usd), porque el usuario tiene
cupo de API limitado en este momento: el script deja de SUBMITIR trabajo
nuevo apenas el costo acumulado confirmado alcanza el limite, dejando
terminar el trabajo ya en vuelo. Lo que quede sin procesar se retoma despues
sin duplicar costo (already_enriched_urls() ya lo filtra)."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_lock import acquire_lock, LockBusyError, StageSkipped, read_jsonl_tolerant  # noqa: E402
from _enrich_pipeline import load_env, _find_content_path, validate_record_invariants  # noqa: E402
from _enrich_pipeline import verify_actor_quotes, verify_institution_quotes, verify_timeline_descriptions, verify_literal_quote_field  # noqa: E402
from _enrich_pipeline import compute_truncation_flags  # noqa: E402
from _enrich_pipeline_v3_3_pilot import (  # noqa: E402 -- mismo modelo/schema/prompt/logica que piloto y calibracion, sin cambios
    CLASSIFICATIONS_PATH, SCHEMA_PATH, RECORD_SCHEMA_PATH, PROMPT_PATH,
    MODEL, REASONING_EFFORT, MAX_TEXT_CHARS_FOR_PROMPT,
    sanitize_project_associations_v3_3, enrich_document,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("enrich_case_v3_3_scale")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_SAMPLE_PATH = PROJECT_ROOT / "audit" / "escalamiento_v3_3_248_restantes.json"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_3_escalamiento"
ENRICHMENT_PATH = OUTPUT_DIR / "enrichment.jsonl"
INVALID_PATH = OUTPUT_DIR / "invalid_records.jsonl"

# Este es el escalamiento real ya autorizado (GO de Sol) -- el limite sigue
# existiendo como guardrail de cordura, pero ahora cubre el universo completo
# restante (248), no un piloto/calibracion.
MAX_URLS = 260


def load_sample_urls(sample_path: Path) -> list[str]:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    urls = list(sample["holdout_principal"]["urls"]) + list(sample.get("stress_dirigido", {}).get("urls", []))
    if len(urls) > MAX_URLS:
        raise RuntimeError(f"La muestra tiene {len(urls)} URLs, por encima del limite de seguridad {MAX_URLS}.")
    if len(set(urls)) != len(urls):
        raise RuntimeError("La muestra tiene URLs duplicadas.")
    return urls


def load_cases(urls: list[str]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    url_set = set(urls)
    for rec in read_jsonl_tolerant(CLASSIFICATIONS_PATH):
        if rec.get("url") in url_set:
            by_url[rec["url"]] = rec

    cases = []
    for url in urls:
        rec = by_url.get(url)
        if rec is None:
            logger.warning("URL no encontrada en classifications.jsonl: %s", url)
            continue
        content_path = _find_content_path(url)
        if content_path is None:
            logger.warning("No se encontro contenido fulltext para %s -- se omite", url[:70])
            continue
        content = json.loads(content_path.read_text(encoding="utf-8"))
        rec["_text"] = content.get("text", "")
        rec["_title"] = content.get("title") or rec.get("title", "")
        rec["_lineage"] = rec.get("lineage") or content.get("lineage", {})
        cases.append(rec)
    return cases


def already_enriched_urls() -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(ENRICHMENT_PATH)}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _process_one(case: dict[str, Any], api_key: str, system_prompt: str, schema: dict, record_schema: dict, run_id: str) -> dict[str, Any]:
    n_case_mentions = len(case.get("case_mentions") or [])
    result = enrich_document(case, api_key, system_prompt, schema)
    if not result or "error" in result:
        return {"status": "error", "url": case.get("url"), "cost": (result or {}).get("total_incurred_cost_usd", 0.0) or 0.0,
                "error": (result or {}).get("error"), "raw_content_on_failure": (result or {}).get("raw_content_on_failure")}

    parsed = result["parsed"]
    cost = result.get("total_incurred_cost_usd", 0.0)
    source_text = case.get("_text", "")
    parsed["actores"] = verify_actor_quotes(parsed.get("actores", []), source_text)
    parsed["instituciones_mencionadas"] = verify_institution_quotes(parsed.get("instituciones_mencionadas", []), source_text)
    parsed["linea_tiempo"] = verify_timeline_descriptions(parsed.get("linea_tiempo", []), source_text)
    parsed = verify_literal_quote_field(parsed, "evidencia_objeto_disputa", source_text, "objeto_disputa")
    parsed = sanitize_project_associations_v3_3(parsed, n_case_mentions)
    invariant_errors = validate_record_invariants(parsed)

    record = {
        "url": case.get("url"),
        "n_case_mentions_etapa1": n_case_mentions,
        "decision_documento_etapa1": case.get("decision_documento"),
        "contract_version_etapa1": case.get("contract_version"),
        "lineage": case.get("_lineage", {}),
        "content_sha256": _sha256_text(source_text),
        "content_char_count": len(source_text),
        "input_truncated": len(source_text) > MAX_TEXT_CHARS_FOR_PROMPT,
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "enrichment_schema_version": "v3.3_escalamiento",
        "prompt_sha256": _sha256_file(PROMPT_PATH),
        "schema_sha256": _sha256_file(SCHEMA_PATH),
        "run_id": run_id,
        "usage": result.get("usage", {}),
        "retry_cost_usd": result.get("retry_cost_usd", 0.0),
        "total_incurred_cost_usd": cost,
        "paid_attempt_count": result.get("paid_attempt_count", 1),
        "request_attempt_count": result.get("request_attempt_count", 1),
        "reasoning": result.get("reasoning"),
        "reasoning_details": result.get("reasoning_details"),
        "raw_finish_reason": result.get("raw_finish_reason"),
        **compute_truncation_flags(parsed, schema),
        **parsed,
    }

    try:
        if invariant_errors:
            raise ValueError("; ".join(invariant_errors))
        jsonschema.validate(instance=record, schema=record_schema)
    except (jsonschema.ValidationError, ValueError) as val_exc:
        return {"status": "invalid", "url": case.get("url"), "cost": cost, "record": record, "validation_error": str(val_exc)[:500]}

    return {"status": "ok", "url": case.get("url"), "cost": cost, "record": record, "parsed": parsed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=50)
    parser.add_argument("--max-cost-usd", type=float, required=True, help="Deja de someter documentos nuevos apenas el costo confirmado acumulado alcance este limite. El trabajo ya en vuelo termina igual.")
    parser.add_argument("--sample", type=str, default=str(DEFAULT_SAMPLE_PATH))
    args = parser.parse_args()

    detail = {"escalamiento": True, "max_cost_usd": args.max_cost_usd, "workers": args.workers, "schema_version": "v3.3"}
    try:
        with acquire_lock("enrich_case_v3_3_scale", detail=detail):
            return _run(args.workers, args.max_cost_usd, Path(args.sample))
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        return exc.return_code


def _run(workers: int, max_cost_usd: float, sample_path: Path) -> int:
    env = load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("OPENROUTER_API_KEY vacia")
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record_schema = json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    urls = load_sample_urls(sample_path)
    cases = load_cases(urls)
    done_urls = already_enriched_urls()
    pending = [c for c in cases if c.get("url") not in done_urls]
    logger.info("Muestra: %d | ya enriquecidos: %d | pendientes: %d | workers: %d | limite de gasto: $%.4f", len(cases), len(done_urls), len(pending), workers, max_cost_usd)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    manifest_path = OUTPUT_DIR / f"run_manifest.{run_id}.json"

    total_cost = 0.0
    n_written = 0
    n_errors = 0
    n_stopped_by_budget = 0
    budget_exhausted = False
    write_lock = Lock()

    with ENRICHMENT_PATH.open("a", encoding="utf-8") as out_file, \
         INVALID_PATH.open("a", encoding="utf-8") as invalid_file:
        idx = 0
        while idx < len(pending) and not budget_exhausted:
            wave = pending[idx: idx + workers]
            idx += workers
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_process_one, case, api_key, system_prompt, schema, record_schema, run_id): case for case in wave}
                for future in as_completed(futures):
                    result = future.result()
                    with write_lock:
                        total_cost += result.get("cost", 0.0)
                        if result["status"] == "ok":
                            out_file.write(json.dumps(result["record"], ensure_ascii=False) + "\n")
                            out_file.flush()
                            n_written += 1
                            proyectos = [(p.get("nombre"), p.get("case_mention_index")) for p in result["parsed"].get("proyectos_mencionados", [])]
                            logger.info("[%d/%d escritos, costo acum=$%.4f] %s -> proyectos=%s", n_written, len(pending), total_cost, result["url"][:60], proyectos)
                        elif result["status"] == "invalid":
                            n_errors += 1
                            invalid_file.write(json.dumps({"url": result["url"], "validation_error": result["validation_error"], "record": result["record"], "run_id": run_id, "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                            invalid_file.flush()
                            logger.error("Registro invalido para %s: %s -- cuarentenado", result["url"][:70], result["validation_error"][:200])
                        else:
                            n_errors += 1
                            logger.warning("Fallo para %s: %s", result["url"][:70], result.get("error"))
                            if result.get("raw_content_on_failure"):
                                invalid_file.write(json.dumps({"url": result["url"], "validation_error": result.get("error"), "raw_content": result["raw_content_on_failure"], "run_id": run_id, "ts": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                                invalid_file.flush()
            if total_cost >= max_cost_usd:
                budget_exhausted = True
                n_stopped_by_budget = len(pending) - idx
                logger.warning("LIMITE DE GASTO ALCANZADO ($%.4f >= $%.4f) -- se detiene sin someter los %d documentos restantes de esta corrida. Se retoman en una proxima corrida sin duplicar costo.", total_cost, max_cost_usd, max(n_stopped_by_budget, 0))

    manifest = {
        "run_id": run_id, "written": n_written, "errors": n_errors, "total_cost_usd": total_cost,
        "budget_exhausted": budget_exhausted, "max_cost_usd": max_cost_usd,
        "n_pendientes_sin_someter_por_presupuesto": max(len(pending) - idx, 0) if budget_exhausted else 0,
        "schema_version": "v3.3_escalamiento", "workers": workers, "sample_path": str(sample_path),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Total enriquecidos: %d | errores: %d | costo total: $%.5f USD | presupuesto agotado: %s | pendientes sin someter: %d | manifest: %s",
                n_written, n_errors, total_cost, budget_exhausted, manifest["n_pendientes_sin_someter_por_presupuesto"], manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
