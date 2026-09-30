#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ejecutor de la extraccion estructurada por LLM (ver `enrichment_core.py`).

Procesa los documentos clasificados como relevantes que aun no tienen extraccion en NINGUNA corrida
previa (`intermediate/enrichment/*/enrichment.jsonl`), asi que relanzarlo nunca vuelve a pagar un
documento ya procesado. La salida de cada corrida vive en `intermediate/enrichment/<run-name>/`.

Guardrails (una corrida pagada es una decision explicita, nunca un accidente de linea de comandos):
- sin `--confirm-paid-run` solo se hace un ensayo: cuenta el universo y los pendientes, sin llamar a la API;
- `--max-cost-usd` es obligatorio en una corrida pagada: deja de someter documentos nuevos apenas el
  costo confirmado acumulado lo alcanza (el trabajo ya en vuelo termina igual y se contabiliza);
- toda respuesta ya pagada se conserva: un registro que no cumple su contrato se cuarentena en
  `invalid_records.jsonl` en vez de perderse.

Uso:
    python src/enrich.py --run-name main                       # ensayo: cuenta pendientes
    python src/enrich.py --run-name main --urls-file urls.json --confirm-paid-run --max-cost-usd 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrichment_core import (  # noqa: E402
    ENV_KEY_BY_PROVIDER, ENV_PATH, PROMPT_PATH, RECORD_SCHEMA_PATH, SCHEMA_PATH, REASONING_EFFORT,
    enrich_document, find_content_path, load_env, process_document, sha256_file,
)
from enrichment_source import enriched_urls_in_all_runs  # noqa: E402
from paths import CLASSIFICATIONS_PATH, ENRICHMENT_DIR  # noqa: E402
from pipeline_lock import LockBusyError, StageSkipped, acquire_lock, read_jsonl_tolerant  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("enrich")

EXPECTED_CORPUS_SCOPE = "temporal_v2"


def load_urls_file(path: Path) -> list[str]:
    """Lista de URLs (JSON: lista simple, o {"urls": [...]})."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    urls = payload.get("urls") if isinstance(payload, dict) else payload
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        raise ValueError("el archivo de URLs debe ser una lista de strings o {'urls': [...]}")
    if len(set(urls)) != len(urls):
        raise ValueError("el archivo de URLs contiene duplicados")
    return urls


def load_cases(urls: list[str] | None) -> list[dict[str, Any]]:
    """Documentos relevantes (decision_documento=include) del alcance vigente con texto completo disponible.
    Si se da `urls`, se restringe a esas."""
    wanted = set(urls) if urls is not None else None
    cases = []
    for rec in read_jsonl_tolerant(CLASSIFICATIONS_PATH):
        if rec.get("decision_documento") != "include" or rec.get("corpus_scope") != EXPECTED_CORPUS_SCOPE:
            continue
        if wanted is not None and rec.get("url") not in wanted:
            continue
        content_path = find_content_path(rec["url"])
        if content_path is None:
            logger.warning("Sin texto completo para %s -- se omite", rec["url"][:70])
            continue
        content = json.loads(content_path.read_text(encoding="utf-8"))
        rec = dict(rec)
        rec["_text"] = content.get("text", "")
        rec["_title"] = content.get("title") or rec.get("title", "")
        rec["_lineage"] = rec.get("lineage") or content.get("lineage", {})
        cases.append(rec)
    return cases


def _process_one(case, api_key, system_prompt, schema, record_schema, run_id, provider, effort, file_hashes) -> dict[str, Any]:
    result = enrich_document(case, api_key, system_prompt, schema, effort=effort, provider=provider)
    if not result or "error" in result:
        return {"status": "error", "url": case.get("url"), "cost": (result or {}).get("total_incurred_cost_usd", 0.0) or 0.0,
                "error": (result or {}).get("error"), "raw_content_on_failure": (result or {}).get("raw_content_on_failure")}
    outcome = process_document(
        case, result, record_schema, schema, run_id, effort, "1.0",
        datetime.now(timezone.utc).isoformat(), file_hashes,
    )
    outcome["url"] = case.get("url")
    return outcome


def run(args: argparse.Namespace) -> int:
    urls = load_urls_file(Path(args.urls_file)) if args.urls_file else None
    cases = load_cases(urls)
    output_dir = ENRICHMENT_DIR / args.run_name
    done = enriched_urls_in_all_runs()
    pending = [c for c in cases if c.get("url") not in done]
    logger.info("Universo: %d | ya extraidos en alguna corrida: %d | pendientes: %d", len(cases), len(cases) - len(pending), len(pending))

    if not args.confirm_paid_run:
        logger.info("ENSAYO: no se llamo a ninguna API. Para ejecutar, agregar --confirm-paid-run y --max-cost-usd.")
        return 0
    if args.max_cost_usd is None:
        logger.error("--max-cost-usd es obligatorio en una corrida pagada")
        return 1

    env_key = ENV_KEY_BY_PROVIDER[args.provider]
    api_key = load_env(ENV_PATH).get(env_key, "")
    if not api_key:
        logger.error("%s vacia", env_key)
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record_schema = json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    file_hashes = {"prompt": sha256_file(PROMPT_PATH), "schema": sha256_file(SCHEMA_PATH), "record_schema": sha256_file(RECORD_SCHEMA_PATH)}

    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    total_cost = 0.0
    n_written = n_errors = 0
    budget_exhausted = False
    submitted = 0
    write_lock = Lock()
    with (output_dir / "enrichment.jsonl").open("a", encoding="utf-8") as out_file, \
         (output_dir / "invalid_records.jsonl").open("a", encoding="utf-8") as invalid_file:
        while submitted < len(pending) and not budget_exhausted:
            wave = pending[submitted: submitted + args.workers]
            submitted += len(wave)
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [executor.submit(_process_one, c, api_key, system_prompt, schema, record_schema, run_id, args.provider, args.effort, file_hashes) for c in wave]
                for future in as_completed(futures):
                    result = future.result()
                    with write_lock:
                        total_cost += result.get("cost", 0.0)
                        if result["status"] == "ok":
                            out_file.write(json.dumps(result["record"], ensure_ascii=False) + "\n")
                            out_file.flush()
                            n_written += 1
                            logger.info("[%d/%d escritos, costo acum=$%.4f] %s", n_written, len(pending), total_cost, result["url"][:70])
                            continue
                        n_errors += 1
                        entry: dict[str, Any] = {"url": result["url"], "run_id": run_id, "ts": datetime.now(timezone.utc).isoformat()}
                        if result["status"] == "invalid":
                            entry.update(validation_error=result["validation_error"], record=result["record"])
                        elif result.get("raw_content_on_failure"):
                            entry.update(validation_error=result.get("error"), raw_content=result["raw_content_on_failure"])
                        else:
                            logger.warning("Fallo para %s: %s", result["url"][:70], result.get("error"))
                            continue
                        invalid_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        invalid_file.flush()
                        logger.error("Respuesta cuarentenada para %s: %s", result["url"][:70], str(entry["validation_error"])[:200])
            if total_cost >= args.max_cost_usd:
                budget_exhausted = True
                logger.warning("LIMITE DE GASTO ALCANZADO ($%.4f >= $%.4f): se detiene sin someter %d documentos; se retoman en otra corrida sin duplicar costo.",
                               total_cost, args.max_cost_usd, len(pending) - submitted)

    manifest = {
        "run_id": run_id, "run_name": args.run_name, "provider": args.provider, "workers": args.workers,
        "written": n_written, "errors": n_errors, "total_cost_usd": total_cost,
        "budget_exhausted": budget_exhausted, "max_cost_usd": args.max_cost_usd,
        "pending_not_submitted": max(len(pending) - submitted, 0),
        "prompt_sha256": file_hashes["prompt"], "schema_sha256": file_hashes["schema"],
        "record_schema_sha256": file_hashes["record_schema"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / f"run_manifest.{run_id}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Escritos: %d | errores: %d | costo total: $%.5f | manifiesto: %s", n_written, n_errors, total_cost, manifest_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True, help="carpeta de salida bajo intermediate/enrichment/")
    parser.add_argument("--urls-file", help="restringe la corrida a estas URLs (JSON)")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--provider", choices=sorted(ENV_KEY_BY_PROVIDER), default="openrouter")
    parser.add_argument("--effort", choices=["none", "minimal", "low", "medium", "high", "xhigh"], default=REASONING_EFFORT)
    parser.add_argument("--max-cost-usd", type=float, default=None)
    parser.add_argument("--confirm-paid-run", action="store_true", help="autoriza llamadas reales (pagadas) a la API")
    args = parser.parse_args(argv)
    try:
        with acquire_lock("enrich", detail={"run_name": args.run_name, "paid": args.confirm_paid_run}):
            return run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        return exc.return_code


if __name__ == "__main__":
    sys.exit(main())
