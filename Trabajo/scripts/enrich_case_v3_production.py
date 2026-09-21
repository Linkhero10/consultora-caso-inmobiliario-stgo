#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runner de PRODUCCION para el enrichment v3.2 sobre el corpus include
completo (934 documentos), separado del runner de piloto
(enrich_case_v3.py, que queda congelado con su guardrail de 30/40 URLs y
nunca debe tocarse para esto).

Hallazgo real de la revisión (2026-09-16, tercera revision de v3.2): "no hay
todavia un runner de produccion para los 934 -- yo no quitaria simplemente
el limite [del script piloto] y reemplazaria la lista por todos los
documentos. Mantendria el script de piloto congelado y crearia una variante
de produccion que reutilice exactamente las mismas funciones/contratos,
pero seleccione el universo de manera explicita".

Este script IMPORTA (no copia) las funciones de verificacion, el cliente de
la API y los contratos desde enrich_case_v3.py -- misma logica de
extraccion, mismo prompt, mismo schema, mismo record schema. Lo unico que
cambia es el universo de documentos (todos los include con fulltext, no
PILOT_URLS) y el destino de escritura.

Selecciona el universo asi (preflight verificable con --dry-run):
    classifications v5.2.3, decision_documento == include
    -> corpus_scope == temporal_v2 (unico scope real visto)
    -> fulltext encontrado en Fuentes/fulltext_v2/content
    -> no enriquecido previamente (ya en enrichment.jsonl de produccion)
    -> 934 esperados (verificado 2026-09-16: 934/934 tienen fulltext)

GUARDRAIL DURO: no ejecuta ninguna llamada real a la API sin el flag
--confirm-production-run, ademas de --dry-run=False. Esto es intencional:
el usuario pidio explicitamente que ninguna corrida pagada se lance sin su
autorizacion explicita para ESA corrida -- este flag existe para que
lanzar el run completo requiera una accion deliberada y visible, no un
accidente de linea de comandos."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_lock import acquire_lock, LockBusyError, StageSkipped, read_jsonl_tolerant  # noqa: E402

# Reutiliza funciones/contratos del runner de piloto -- NUNCA duplicar esta
# logica, cualquier fix futuro a la verificacion/extraccion debe hacerse una
# sola vez en enrich_case_v3.py y este script lo hereda automaticamente.
import enrich_case_v3 as pilot  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("enrich_case_v3_production")

PROJECT_ROOT = pilot.PROJECT_ROOT
CLASSIFICATIONS_PATH = pilot.CLASSIFICATIONS_PATH
CONTENT_DIR = pilot.CONTENT_DIR
SCHEMA_PATH = pilot.SCHEMA_PATH
RECORD_SCHEMA_PATH = pilot.RECORD_SCHEMA_PATH
PROMPT_PATH = pilot.PROMPT_PATH
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_2_934"
ENRICHMENT_PATH = OUTPUT_DIR / "enrichment.jsonl"
INVALID_PATH = OUTPUT_DIR / "invalid_records.jsonl"
ERRORS_PATH = OUTPUT_DIR / "errors.jsonl"
EXPECTED_INCLUDE = 934  # verificado 2026-09-16 contra classifications.jsonl
# Hallazgo real de la auditoría (auditoria de lanzamiento, paso 7 de su lista):
# "ejecutar un --dry-run sobre los 934 y congelar el hash del universo".
# UNIVERSE_FREEZE_PATH es ese artefacto -- si la clasificacion Etapa 1
# cambia entre el dry-run y la corrida real (documento agregado/quitado),
# el hash diverge y el guardrail de abajo se niega a correr.
UNIVERSE_FREEZE_PATH = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_2_934" / "universo_congelado_934.json"


EXPECTED_CORPUS_SCOPE = "temporal_v2"  # unico scope real visto en los 934 include (verificado 2026-09-16)


def load_production_cases() -> list[dict]:
    """Universo completo: TODOS los documentos decision_documento==include
    Y corpus_scope==temporal_v2 de la clasificacion Etapa 1 vigente, con
    fulltext disponible -- a diferencia de load_pilot_cases() (solo
    PILOT_URLS).

    Fix v3.2 (hallazgo real de la revisión, cuarta revision): antes solo filtraba
    por decision_documento==include; hoy los 934 include coinciden 1:1 con
    corpus_scope==temporal_v2 (verificado), pero eso era una coincidencia
    de conteo, no una condicion explicita en el codigo -- si algun dia
    aparece un include de otro scope, EXPECTED_INCLUDE=934 lo hubiera
    detectado (stop-the-line), pero el universo mismo no estaba definido
    por contrato. Ahora el filtro de corpus_scope es explicito y se reporta
    include_all_scopes / include_temporal_v2 / excluded_other_scopes en el
    preflight."""
    by_url_all_scopes: dict[str, dict] = {}
    by_url_temporal_v2: dict[str, dict] = {}
    for rec in read_jsonl_tolerant(CLASSIFICATIONS_PATH):
        if rec.get("decision_documento") != "include":
            continue
        by_url_all_scopes[rec["url"]] = rec
        if rec.get("corpus_scope") == EXPECTED_CORPUS_SCOPE:
            by_url_temporal_v2[rec["url"]] = rec

    n_excluded_other_scopes = len(by_url_all_scopes) - len(by_url_temporal_v2)

    cases = []
    missing_fulltext = []
    for url, rec in by_url_temporal_v2.items():
        content_path = pilot._find_content_path(url)
        if content_path is None:
            missing_fulltext.append(url)
            continue
        content = json.loads(content_path.read_text(encoding="utf-8"))
        rec = dict(rec)
        rec["_text"] = content.get("text", "")
        rec["_title"] = content.get("title") or rec.get("title", "")
        rec["_lineage"] = rec.get("lineage") or content.get("lineage", {})
        cases.append(rec)

    if missing_fulltext:
        logger.warning("%d documento(s) include SIN fulltext encontrado -- se excluyen del universo, revisar antes de correr: %s", len(missing_fulltext), missing_fulltext[:10])
    if n_excluded_other_scopes:
        logger.warning("%d documento(s) include con corpus_scope distinto de %r -- excluidos del universo de produccion", n_excluded_other_scopes, EXPECTED_CORPUS_SCOPE)

    universe_sha256 = hashlib.sha256("\n".join(sorted(by_url_temporal_v2.keys())).encode("utf-8")).hexdigest()

    return cases, len(by_url_all_scopes), len(by_url_temporal_v2), n_excluded_other_scopes, missing_fulltext, universe_sha256


def already_enriched_urls() -> set[str]:
    return {rec.get("url", "") for rec in read_jsonl_tolerant(ENRICHMENT_PATH)}


def check_universe_freeze(universe_sha256: str) -> tuple[bool, str]:
    """Hallazgo real de la auditoría: compara el hash del universo ACTUAL (recien
    calculado) contra el que se congelo en universo_congelado_934.json.
    Si no coincide, la clasificacion Etapa 1 cambio desde que se fijo ese
    artefacto -- devuelve (False, motivo) para que _run() haga stop-the-line.

    Fix real (hallazgo real de la auditoría, segunda auditoria, 2026-09-17): esta
    funcion SOLO comparaba universe_sha256, nunca los hashes de
    prompt/schema/record_schema que el mismo artefacto ya guardaba -- un
    prompt editado despues de congelar el universo (exactamente lo que
    paso en este proyecto: alguien edito enrichment_system_v3_2.md tras el
    congelamiento) pasaba sin que nada lo detectara. Ahora se comparan los
    4 hashes, no solo 1."""
    if not UNIVERSE_FREEZE_PATH.exists():
        return False, f"no existe {UNIVERSE_FREEZE_PATH} -- correr el congelamiento del universo antes de una corrida real"
    frozen = json.loads(UNIVERSE_FREEZE_PATH.read_text(encoding="utf-8"))
    frozen_hash = frozen.get("universe_sha256", "")
    if frozen_hash != universe_sha256:
        return False, f"universe_sha256 actual ({universe_sha256[:16]}...) no coincide con el congelado ({frozen_hash[:16]}...) -- la clasificacion Etapa 1 cambio desde {frozen.get('frozen_at', '?')}"

    current_prompt_sha256 = pilot._sha256_file(PROMPT_PATH)
    current_schema_sha256 = pilot._sha256_file(SCHEMA_PATH)
    current_record_schema_sha256 = pilot._sha256_file(RECORD_SCHEMA_PATH)
    checks = (
        ("prompt_sha256", frozen.get("prompt_sha256", ""), current_prompt_sha256),
        ("schema_sha256", frozen.get("schema_sha256", ""), current_schema_sha256),
        ("record_schema_sha256", frozen.get("record_schema_sha256", ""), current_record_schema_sha256),
    )
    for name, frozen_val, current_val in checks:
        if frozen_val != current_val:
            return False, f"{name} actual ({current_val[:16]}...) no coincide con el congelado ({frozen_val[:16]}...) -- el contrato (prompt/schema/record_schema) cambio desde {frozen.get('frozen_at', '?')} sin volver a congelar el universo. Correr de nuevo el congelamiento (y validar el cambio con un piloto) antes de producir."
    return True, ""


def previously_quarantined_urls() -> set[str]:
    if not INVALID_PATH.exists():
        return set()
    return {rec.get("url", "") for rec in read_jsonl_tolerant(INVALID_PATH)}


def estimate_cost_per_doc() -> float:
    """Estima costo/doc a partir del piloto v3.2 real (30 docs, mismo
    modelo/schema/prompt/effort) -- no es una cifra inventada."""
    pilot_recs = list(read_jsonl_tolerant(pilot.ENRICHMENT_PATH))
    costs = [r.get("total_incurred_cost_usd", r.get("usage", {}).get("cost", 0.0)) or 0.0 for r in pilot_recs]
    if not costs:
        return 0.0
    return sum(costs) / len(costs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preflight: imprime conteos y costo estimado, NO llama a la API.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--effort", type=str, default=pilot.REASONING_EFFORT, choices=["none", "minimal", "low", "medium", "high", "xhigh"])
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--confirm-production-run", action="store_true", help="Requerido junto con la ausencia de --dry-run para ejecutar llamadas reales a la API sobre el corpus completo. Sin este flag, el script se niega a correr en modo real.")
    args = parser.parse_args()

    detail = {"effort": args.effort, "es_produccion": True, "limit": args.limit, "workers": args.workers}
    try:
        with acquire_lock("enrich_case_v3_production", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        return exc.return_code


def _preflight(cases, n_all_scopes, n_temporal_v2, n_excluded_other_scopes, missing_fulltext, done_urls, quarantined_urls, pending_total, pending_selected, universe_sha256, universe_freeze_ok, universe_freeze_motivo, args) -> dict:
    prompt_sha256 = pilot._sha256_file(PROMPT_PATH)
    schema_sha256 = pilot._sha256_file(SCHEMA_PATH)
    record_schema_sha256 = pilot._sha256_file(RECORD_SCHEMA_PATH)
    cost_per_doc = estimate_cost_per_doc()
    # Fix v3.2 (hallazgo real de la revisión, cuarta revision): los reintentos de
    # cuarentena y el costo estimado deben calcularse sobre pending_selected
    # (lo que REALMENTE se va a procesar si hay --limit), no sobre
    # pending_total -- antes el preflight mostraba el costo de los 934 aunque
    # se fuera a correr solo --limit 20.
    reintentos_cuarentena = [c.get("url", "") for c in pending_selected if c.get("url") in quarantined_urls]

    report = {
        "expected_include": EXPECTED_INCLUDE,
        "classifications_include_all_scopes": n_all_scopes,
        "temporal_v2_include": n_temporal_v2,
        "excluded_other_scopes": n_excluded_other_scopes,
        "fulltext_found": len(cases),
        "missing_fulltext": len(missing_fulltext),
        "already_enriched": len(done_urls),
        "pending_total": len(pending_total),
        "limit": args.limit or None,
        "pending_selected": len(pending_selected),
        "reintentos_de_cuarentena_en_pending_selected": len(reintentos_cuarentena),
        "universe_sha256": universe_sha256,
        "universe_freeze_ok": universe_freeze_ok,
        "universe_freeze_motivo": universe_freeze_motivo,
        "schema_version": "v3.2",
        "prompt_sha256": prompt_sha256,
        "schema_sha256": schema_sha256,
        "record_schema_sha256": record_schema_sha256,
        "cost_per_doc_usd_estimado_desde_piloto": round(cost_per_doc, 5),
        "estimated_cost_usd_pending_total": round(cost_per_doc * len(pending_total), 2),
        "estimated_cost_usd_selected": round(cost_per_doc * len(pending_selected), 2),
        "workers": args.workers,
        "effort": args.effort,
    }
    return report


def _run(args) -> int:
    cases, n_all_scopes, n_temporal_v2, n_excluded_other_scopes, missing_fulltext, universe_sha256 = load_production_cases()
    done_urls = already_enriched_urls()
    pending_total = [c for c in cases if c.get("url") not in done_urls]
    pending_selected = pending_total[: args.limit] if args.limit else pending_total
    quarantined_urls = previously_quarantined_urls()
    universe_freeze_ok, universe_freeze_motivo = check_universe_freeze(universe_sha256)

    report = _preflight(cases, n_all_scopes, n_temporal_v2, n_excluded_other_scopes, missing_fulltext, done_urls, quarantined_urls, pending_total, pending_selected, universe_sha256, universe_freeze_ok, universe_freeze_motivo, args)
    logger.info("PREFLIGHT: %s", json.dumps(report, indent=2, ensure_ascii=False))

    # Stop-the-line: si el universo esperado no coincide, no seguir -- ni
    # siquiera en modo real con --confirm-production-run.
    if n_temporal_v2 != EXPECTED_INCLUDE:
        logger.error("STOP-THE-LINE: classifications.jsonl tiene %d documentos include con corpus_scope=%r, se esperaban %d -- la clasificacion Etapa 1 cambio desde que se fijo este numero. Revisar antes de continuar.", n_temporal_v2, EXPECTED_CORPUS_SCOPE, EXPECTED_INCLUDE)
        return 1
    if missing_fulltext:
        logger.error("STOP-THE-LINE: %d documento(s) include sin fulltext -- revisar antes de continuar.", len(missing_fulltext))
        return 1
    # Hallazgo real de la auditoría (paso 7 de su lista): el hash del universo
    # congelado (universo_congelado_934.json) debe coincidir con el
    # recalculado ahora mismo -- si no, la clasificacion Etapa 1 cambio
    # desde que se congelo, y NO se sigue ni siquiera en modo real.
    if not universe_freeze_ok and not args.dry_run:
        logger.error("STOP-THE-LINE: %s", universe_freeze_motivo)
        return 1

    reintentos_cuarentena = [c.get("url", "") for c in pending_selected if c.get("url") in quarantined_urls]
    if reintentos_cuarentena:
        logger.warning("%d URL(s) seleccionadas fueron cuarentenadas antes (fallaron record schema) y se van a REINTENTAR, con costo nuevo: %s", len(reintentos_cuarentena), reintentos_cuarentena[:10])

    if args.dry_run:
        logger.info("DRY RUN: sin llamadas a la API. pending_total=%d, pending_selected=%d (limit=%s).", len(pending_total), len(pending_selected), args.limit or "sin limite")
        return 0

    # Fix v3.2 (mejora no bloqueante de la revisión): la comprobacion de
    # OPENROUTER_API_KEY se movia ANTES de saber si era --dry-run -- un
    # dry-run no hace ninguna llamada, no deberia exigir credenciales.
    # Movido a despues del return temprano de dry-run.
    env = pilot.load_env(pilot.ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        logger.error("OPENROUTER_API_KEY vacia")
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record_schema = json.loads(RECORD_SCHEMA_PATH.read_text(encoding="utf-8"))
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    if not args.confirm_production_run:
        logger.error("Se pidio una corrida REAL (sin --dry-run) pero falta --confirm-production-run -- esto es un guardrail deliberado, no un bug. Agregar el flag explicitamente para confirmar la corrida pagada sobre %d documentos (costo estimado $%.2f).", len(pending_selected), report["estimated_cost_usd_selected"])
        return 1

    pending = pending_selected

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    manifest_path = OUTPUT_DIR / f"run_manifest.{run_id}.json"

    total_cost = 0.0
    revision_niveles = {"ninguno": 0, "campo": 0, "caso": 0, "bloqueante": 0}
    n_triage_consistency_flags = 0
    n_hitos_totales = 0
    n_written = 0
    n_errors = 0
    n_record_schema_failures = 0

    with ENRICHMENT_PATH.open("a", encoding="utf-8") as out_file, ERRORS_PATH.open("a", encoding="utf-8") as err_file, INVALID_PATH.open("a", encoding="utf-8") as invalid_file, ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(pilot.enrich_document, case, api_key, system_prompt, schema, args.effort): case for case in pending}
        for future in as_completed(futures):
            case = futures[future]
            # Hallazgo real de la auditoría (2026-09-17): future.result() y todo el
            # postprocesamiento (verificacion de citas, invariantes,
            # jsonschema) vivian FUERA de cualquier try/except -- una
            # excepcion inesperada en un solo documento (de 934) tumbaba el
            # `with ThreadPoolExecutor` completo, y el manifest final NUNCA
            # se escribia (los registros YA escritos en enrichment.jsonl
            # quedan a salvo por el flush incremental, pero se pierde el
            # resumen y la corrida termina de forma sucia). Ahora cada
            # documento esta aislado: una falla inesperada en UNO no tumba
            # los otros 933.
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                n_errors += 1
                logger.error("Excepcion INESPERADA obteniendo el resultado para %s: %s -- registrado como error, la corrida continua", case.get("url", "")[:70], exc)
                err_file.write(json.dumps({
                    "url": case.get("url"),
                    "error": f"unexpected_exception_in_future_result: {exc}"[:500],
                    "cost_incurred_usd": 0.0,
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + "\n")
                err_file.flush()
                continue
            if not result or "error" in result:
                n_errors += 1
                failed_cost = (result or {}).get("total_incurred_cost_usd", 0.0) or 0.0
                total_cost += failed_cost
                err_file.write(json.dumps({
                    "url": case.get("url"),
                    "error": (result or {}).get("error", "enrich_document_returned_none"),
                    "cost_incurred_usd": failed_cost,
                    "paid_attempt_count": (result or {}).get("paid_attempt_count", 0),
                    "request_attempt_count": (result or {}).get("request_attempt_count", 0),
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + "\n")
                err_file.flush()
                logger.warning("Fallo para %s (costo incurrido=$%.5f en %d intentos pagados) -- registrado en errors.jsonl", case.get("url", "")[:70], failed_cost, (result or {}).get("paid_attempt_count", 0))
                continue

            usage = result.get("usage", {})
            cost = result.get("total_incurred_cost_usd", usage.get("cost", 0.0) or 0.0)

            # Hallazgo real de la auditoría (2026-09-17): todo este bloque de
            # postprocesamiento (verificacion de citas, invariantes,
            # construccion del registro, jsonschema) vivia fuera de
            # cualquier try/except -- un KeyError/TypeError inesperado en UN
            # documento (de 934) tumbaba el `with ThreadPoolExecutor`
            # completo sin escribir el manifest final. Aislado por
            # documento: una falla inesperada aqui se registra como error y
            # la corrida sigue con los demas 933.
            try:
                total_cost += cost
                parsed = result["parsed"]
                source_text = case.get("_text", "")
                parsed["actores"] = pilot.verify_actor_quotes(parsed.get("actores", []), source_text)
                parsed["instituciones_mencionadas"] = pilot.verify_institution_quotes(parsed.get("instituciones_mencionadas", []), source_text)
                parsed["linea_tiempo"] = pilot.verify_timeline_descriptions(parsed.get("linea_tiempo", []), source_text)
                parsed = pilot.verify_literal_quote_field(parsed, "evidencia_objeto_disputa", source_text, "objeto_disputa")
                parsed = pilot.sanitize_project_associations(parsed)
                invariant_errors = pilot.validate_record_invariants(parsed)
                nivel = parsed.get("revision", {}).get("nivel", "ninguno")
            except Exception as exc:  # noqa: BLE001
                n_errors += 1
                logger.error("Excepcion INESPERADA postprocesando %s: %s -- registrado como error (costo ya incurrido=$%.5f preservado), la corrida continua", case.get("url", "")[:70], exc, cost)
                err_file.write(json.dumps({
                    "url": case.get("url"),
                    "error": f"unexpected_exception_in_postprocessing: {exc}"[:500],
                    "cost_incurred_usd": cost,
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + "\n")
                err_file.flush()
                continue

            try:
                record = {
                    "url": case.get("url"),
                    "decision_documento_etapa1": case.get("decision_documento"),
                    "contract_version_etapa1": case.get("contract_version"),
                    "lineage": case.get("_lineage", {}),
                    "content_sha256": pilot._sha256_text(source_text),
                    "content_char_count": len(source_text),
                    "input_truncated": len(source_text) > pilot.MAX_TEXT_CHARS_FOR_PROMPT,
                    "enriched_at": datetime.now(timezone.utc).isoformat(),
                    "model": pilot.MODEL,
                    "reasoning_effort": args.effort,
                    "enrichment_schema_version": "v3.2",
                    "prompt_sha256": report["prompt_sha256"],
                    "schema_sha256": report["schema_sha256"],
                    "record_schema_sha256": report["record_schema_sha256"],
                    "script_sha256": pilot._sha256_file(Path(__file__).resolve()),
                    # Mejora de trazabilidad de la revisión (no bloqueante, quinta revision):
                    # script_sha256 (arriba) es el hash de ESTE runner, pero la
                    # logica critica de extraccion (enrich_document, verificadores
                    # de citas y timeline, constantes de truncamiento) viene
                    # IMPORTADA de enrich_case_v3.py -- si ese archivo cambia en el
                    # futuro, hace falta poder reconstruir exactamente que codigo
                    # corrio cada lote. runner_script_sha256 es explicitamente el
                    # mismo valor que script_sha256 (redundante a proposito, para
                    # que quede claro cual es cual); core_enrichment_script_sha256
                    # es el hash del modulo importado. Ambos opcionales en el
                    # record schema porque los registros del piloto (que no
                    # importa nada, es autocontenido) no los tienen.
                    "runner_script_sha256": pilot._sha256_file(Path(__file__).resolve()),
                    "core_enrichment_script_sha256": pilot._sha256_file(Path(pilot.__file__).resolve()),
                    "run_id": run_id,
                    "usage": usage,
                    "retry_cost_usd": result.get("retry_cost_usd", 0.0),
                    "total_incurred_cost_usd": cost,
                    "paid_attempt_count": result.get("paid_attempt_count", 1),
                    "request_attempt_count": result.get("request_attempt_count", 1),
                    "reasoning": result.get("reasoning"),
                    "reasoning_details": result.get("reasoning_details"),
                    "raw_finish_reason": result.get("raw_finish_reason"),
                    **pilot.compute_truncation_flags(parsed, schema),
                    **parsed,
                }

                try:
                    if invariant_errors:
                        raise ValueError("; ".join(invariant_errors))
                    jsonschema.validate(instance=record, schema=record_schema)
                except (jsonschema.ValidationError, ValueError) as val_exc:
                    n_record_schema_failures += 1
                    n_errors += 1
                    error_message = getattr(val_exc, "message", str(val_exc))
                    logger.error("Registro persistido NO valido contra los contratos v3.2 para %s: %s -- cuarentenado, NO entra a enrichment.jsonl", case.get("url", "")[:70], error_message[:200])
                    invalid_file.write(json.dumps({
                        "url": case.get("url"),
                        "validation_error": error_message[:500],
                        "record": record,
                        "run_id": run_id,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False) + "\n")
                    invalid_file.flush()
                    continue

                n_hitos_totales += len(parsed.get("linea_tiempo", []))
                revision_niveles[nivel] = revision_niveles.get(nivel, 0) + 1
                if parsed.get("triage_consistency_check"):
                    n_triage_consistency_flags += 1

                out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_file.flush()
                n_written += 1

                logger.info(
                    "[%d/%d] %s -> proyecto=%r hitos=%d actores=%d (central=%d) revision=%s truncado=%s | costo=$%.5f",
                    n_written, len(pending), case.get("url", "")[:60],
                    parsed.get("nombre_proyecto", "")[:40], len(parsed.get("linea_tiempo", [])),
                    len(parsed.get("actores", [])),
                    sum(1 for a in parsed.get("actores", []) if a.get("nivel_involucramiento") == "central"),
                    nivel, record["input_truncated"], cost,
                )
            except Exception as exc:  # noqa: BLE001
                n_errors += 1
                logger.error("Excepcion INESPERADA construyendo/escribiendo el registro para %s: %s -- registrado como error (costo ya incurrido=$%.5f preservado), la corrida continua", case.get("url", "")[:70], exc, cost)
                err_file.write(json.dumps({
                    "url": case.get("url"),
                    "error": f"unexpected_exception_building_record: {exc}"[:500],
                    "cost_incurred_usd": cost,
                    "run_id": run_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + "\n")
                err_file.flush()
                continue

    esperados = len(pending)
    counts_consistent = (n_written + n_errors == esperados)
    if not counts_consistent:
        logger.error("Inconsistencia de conteos: escritos=%d + errores=%d != esperados=%d", n_written, n_errors, esperados)

    manifest = {
        "run_id": run_id,
        "preflight": report,
        "started_pending": esperados,
        "written": n_written,
        "errors": n_errors,
        "counts_consistent": counts_consistent,
        "total_cost_usd": total_cost,
        "hitos_linea_tiempo": n_hitos_totales,
        "revision_niveles": revision_niveles,
        "triage_consistency_flags": n_triage_consistency_flags,
        "record_schema_validation_failures": n_record_schema_failures,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    # Fix (hallazgo real de la auditoría, deuda de durabilidad, no una falla
    # observada): antes se escribia manifest_path.write_text() directo -- un
    # crash o un corte de energia a mitad del write() podia dejar el
    # manifest truncado/corrupto. Ahora se escribe a un archivo temporal en
    # el mismo directorio, se hace fsync, y se renombra atomicamente
    # (os.replace es atomico en el mismo filesystem) -- el manifest final
    # queda siempre completo o no existe, nunca a medias.
    manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        tmp_file.write(manifest_json)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_path, manifest_path)
    logger.info("Total enriquecidos: %d | errores: %d | hitos linea_tiempo: %d | revision_niveles: %s | triage_consistency_flags: %d | fallas de schema del registro persistido: %d | costo total: $%.5f USD | manifest: %s", n_written, n_errors, n_hitos_totales, revision_niveles, n_triage_consistency_flags, n_record_schema_failures, total_cost, manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
