#!/usr/bin/env python3
"""Clasificador v5.2: frontera estricta para inmuebles existentes.

v5.2 conserva el contrato estructural de v5.1. Solo añade un gate
determinista: una ocupación/tenencia de inmueble existente sin intervención
urbana formal o materialmente relevante no entra en ninguna vista.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify_v5_1 as base  # noqa: E402
from pipeline_lock import LockBusyError, StageSkipped, acquire_lock, upstream_stage_is_running  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("classify_v5_2")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "src" / "_classify_pipeline" / "schema_stage_v5_2.json"
PROMPT_PATH = PROJECT_ROOT / "src" / "_classify_pipeline" / "prompt_stage_v5_2.md"
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5_2"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "classifications.jsonl"
REVIEW_ARTIFACT_PATH = PROJECT_ROOT / "Auditoria" / "muestras_control" / "review_sample_v5_2_amplio.json"
MODEL = base.MODEL
REASONING_EFFORT = base.REASONING_EFFORT


def _existing_property_without_urban_intervention(mention: dict) -> bool:
    """Detecta la frontera v5.2 sin inferir hechos nuevos.

    La combinación ocupación/propiedad + sin vía formal no basta para
    demostrar una intervención urbana relevante. Casos con patrimonio,
    regulación, permisos u otra vía verificable permanecen candidatos.
    """
    relation = str(mention.get("relacion_inmobiliaria_urbana", "")).strip().lower()
    conflict = str(mention.get("tipo_conflicto_norm", "")).strip().lower()
    legal = str(mention.get("via_legal_norm", "")).strip().lower()
    return (
        relation == "inmueble_existente_relevancia_urbana"
        and conflict == "ocupacion_propiedad"
        and legal in {"", "none", "sin_via_identificada", "incierta"}
    )


def apply_scope_gate(parsed: dict, source_text: str, scope: str) -> dict:
    result = base.apply_scope_gate(parsed, source_text, scope)
    # No conviertas una incertidumbre declarada por el modelo en exclusión:
    # la frontera es un veto adicional solo cuando el modelo propuso include.
    if parsed.get("decision") == "include" and _existing_property_without_urban_intervention(parsed):
        reasons = list(result.get("gate_reasons", []))
        reason = "inmueble_existente_sin_intervencion_urbana_formal"
        if reason not in reasons:
            reasons.append(reason)
        result["gate_reasons"] = reasons
        result["decision_final"] = "exclude"
        evaluation = dict(result.get("gate_evaluation", {}))
        evaluation["object"] = False
        result["gate_evaluation"] = evaluation
    return result


def _decision_for_scope(results: list[dict]) -> str:
    return base._decision_for_scope(results)


def derive_document_decisions(mentions: list[dict], source_text: str) -> dict:
    processed, residential, broad = [], [], []
    for mention in mentions:
        res = apply_scope_gate(mention, source_text, "residencial")
        wide = apply_scope_gate(mention, source_text, "inmobiliaria_urbana_amplia")
        item = deepcopy(mention)
        item["gate_residencial"] = res
        item["gate_inmobiliaria_urbana_amplia"] = wide
        processed.append(item)
        residential.append(res)
        broad.append(wide)
    return {
        "case_mentions": processed,
        "decision_residencial": _decision_for_scope(residential),
        "decision_inmobiliaria_urbana_amplia": _decision_for_scope(broad),
        "decision_documento": _decision_for_scope(broad),
    }


def postprocess_result(doc: dict, result: dict) -> tuple[str, dict]:
    parsed = deepcopy(result["parsed"])
    for mention in parsed.get("case_mentions", []):
        base._enrich_locations(mention)
    derived = derive_document_decisions(parsed.get("case_mentions", []), str(doc.get("text", "")))
    record = {
        "url": doc.get("url"),
        "lineage": doc.get("lineage", {}),
        "corpus_scope": "temporal_v2",
        "contract_version": "v5.2",
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "reasoning": result.get("reasoning"),
        "reasoning_details": result.get("reasoning_details"),
        "usage": result.get("usage", {}),
        "decision_modelo": parsed.get("decision"),
        **parsed,
        **derived,
    }
    return str(record["decision_documento"]), record


def classification_release_allowed(review_artifact: dict) -> bool:
    policy = review_artifact.get("review_policy", review_artifact)
    return (
        review_artifact.get("status") == "aprobado_revision_humana"
        and policy.get("human_review_completed") is True
        and policy.get("production_allowed") is True
    )


def _run(args: argparse.Namespace) -> int:
    is_test = bool(args.output_file or args.urls_file or args.dry_run)
    for stage in ("fulltext_acquisition_v2", "dedupe_fulltext"):
        if upstream_stage_is_running(stage) and not is_test:
            raise StageSkipped(3, f"{stage} activo; se bloquea produccion")
    if not is_test:
        try:
            artifact = json.loads(REVIEW_ARTIFACT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageSkipped(4, f"no se pudo leer gate v5.2: {exc}") from exc
        if not classification_release_allowed(artifact):
            raise StageSkipped(4, "gate humano v5.2 pendiente")
    env = base.load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    urls_filter = {line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if line.strip()} if args.urls_file else None
    docs = base.load_classifiable_documents(urls_filter=urls_filter)
    done = base.already_classified_urls(output_path)
    pending = [doc for doc in docs if doc.get("url") not in done]
    if args.dry_run:
        pending = pending[:1]
    elif args.limit:
        pending = pending[:args.limit]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(base.classify_document, doc, api_key, prompt, schema): doc for doc in pending}
        for future in as_completed(futures):
            doc = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Fallo no recuperable para %s: %s", doc.get("url", "")[:80], exc)
                result = None
            if result is not None:
                _, record = postprocess_result(doc, result)
                records.append(record)
    records.sort(key=lambda item: item.get("url", ""))
    if records:
        with output_path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    logger.info("v5.2 completado: %d registros escritos en %s", len(records), output_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificacion v5.2 con frontera estricta para inmuebles existentes")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    detail = {"output_path": str(output_path), "es_produccion": not bool(args.output_file or args.urls_file or args.dry_run), "schema_version": "v5.2"}
    try:
        with acquire_lock("classify_v5_2", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
