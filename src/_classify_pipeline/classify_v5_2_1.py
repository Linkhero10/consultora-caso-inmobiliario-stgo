#!/usr/bin/env python3
"""Gate v5.2.1: separa suficiencia de evidencia y limpieza de citas.

v5.2.1 es deliberadamente solo un cambio de postprocesamiento. Conserva el
prompt, schema, respuestas crudas y frontera de inmueble existente de v5.2.
Una cita inválida adicional queda visible como advertencia de calidad, pero no
borra una evidencia válida de la misma categoría. La liberación de producción
continúa dependiendo del gate de revisión humana.
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
import classify_v5_1 as v51  # noqa: E402
import classify_v5_2 as v52  # noqa: E402
from pipeline_lock import LockBusyError, StageSkipped, acquire_lock, upstream_stage_is_running  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("classify_v5_2_1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "src" / "_classify_pipeline" / "schema_stage_v5_2.json"
PROMPT_PATH = PROJECT_ROOT / "src" / "_classify_pipeline" / "prompt_stage_v5_2.md"
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5_2_1"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "classifications.jsonl"
REVIEW_ARTIFACT_PATH = PROJECT_ROOT / "Auditoria" / "muestras_control" / "review_sample_v5_2_1_amplio.json"
MODEL = v52.MODEL
REASONING_EFFORT = v52.REASONING_EFFORT

_CONTRACT_REASON_BY_LABEL = {
    "accion": "evidencia_accion_contrato_invalido",
    "objeto": "evidencia_objeto_contrato_invalido",
    "geografica": "evidencia_geografica_contrato_invalido",
}


def _quote_quality(parsed: dict, source_text: str) -> dict:
    categories = {
        "accion": "evidencia_accion_quotes",
        "objeto": "evidencia_objeto_quotes",
        "geografica": "evidencia_geografica_quotes",
    }
    quality: dict[str, dict] = {}
    for label, key in categories.items():
        flags, sufficient, clean = v51.quote_flags(parsed.get(key), source_text)
        quality[label] = {
            "flags": flags,
            "sufficient": sufficient,
            "fully_clean": clean,
            "invalid_count": sum(not flag for flag in flags),
        }
    category_values = [quality[label] for label in categories]
    quality["all_sufficient"] = all(item["sufficient"] for item in category_values)
    quality["all_fully_clean"] = all(item["fully_clean"] for item in category_values)
    return quality


def _broad_unknown_object_is_admissible(parsed: dict, quality: dict) -> bool:
    """Permite un objeto sin subtipo solo con evidencia amplia explícita."""
    relation = str(parsed.get("relacion_inmobiliaria_urbana", "")).strip().lower()
    return (
        str(parsed.get("tipo_objeto_norm", "")).strip().lower() == "objeto_no_determinado"
        and str(parsed.get("es_proyecto_inmobiliario", "")).strip().lower() == "si"
        and relation in {"desarrollo_proyecto", "transformacion_regulacion_uso", "inmueble_existente_relevancia_urbana"}
        and quality["objeto"]["sufficient"]
        and quality["accion"]["sufficient"]
        and quality["geografica"]["sufficient"]
        and bool(str(parsed.get("tipo_objeto_raw", "")).strip())
    )


def apply_scope_gate(parsed: dict, source_text: str, scope: str) -> dict:
    """Reevalúa v5.2 sin llamadas API y conserva v5.2 como historial."""
    if scope not in v51.SCOPES:
        raise ValueError(f"scope no soportado: {scope}")

    result = v52.apply_scope_gate(parsed, source_text, scope)
    quality = _quote_quality(parsed, source_text)
    result["evidence_action_quotes_verified"] = quality["accion"]["flags"]
    result["evidence_object_quotes_verified"] = quality["objeto"]["flags"]
    result["evidence_geo_quotes_verified"] = quality["geografica"]["flags"]
    result["evidence_action_verified"] = quality["accion"]["sufficient"]
    result["evidence_object_verified"] = quality["objeto"]["sufficient"]
    result["evidence_geo_verified"] = quality["geografica"]["sufficient"]
    result["case_evidence_sufficient"] = {
        "action": quality["accion"]["sufficient"],
        "object": quality["objeto"]["sufficient"],
        "geography": quality["geografica"]["sufficient"],
        "all": quality["all_sufficient"],
    }
    result["quote_set_fully_clean"] = {
        "action": quality["accion"]["fully_clean"],
        "object": quality["objeto"]["fully_clean"],
        "geography": quality["geografica"]["fully_clean"],
        "all": quality["all_fully_clean"],
    }
    result["invalid_quote_counts"] = {
        label: quality[label]["invalid_count"] for label in ("accion", "objeto", "geografica")
    }
    result["quality_flags"] = [
        f"{label}_quote_set_not_fully_clean"
        for label in ("accion", "objeto", "geografica")
        if quality[label]["sufficient"] and not quality[label]["fully_clean"]
    ]

    # Las decisiones no include del modelo no se reinterpretan.
    if str(parsed.get("decision", "uncertain")) != "include":
        return result

    reasons = [
        reason
        for reason in result.get("gate_reasons", [])
        if reason not in _CONTRACT_REASON_BY_LABEL.values()
    ]

    # La frontera estricta v5.2 sigue siendo un veto duro.
    if "inmueble_existente_sin_intervencion_urbana_formal" in reasons:
        result["gate_reasons"] = reasons
        return result

    object_exception = scope == "inmobiliaria_urbana_amplia" and _broad_unknown_object_is_admissible(parsed, quality)
    if object_exception:
        reasons = [reason for reason in reasons if reason != "objeto_no_determinado"]

    hard_exclude = {
        "sin_accion_contenciosa",
        "objeto_fuera_de_alcance_residencial",
        "objeto_no_admisible",
        "objeto_existente_sin_vinculo_urbano",
        "fuera_del_area_geografica",
        "mencion_tangencial",
    }
    result["decision_final"] = "exclude" if hard_exclude.intersection(reasons) else ("uncertain" if reasons else "include")
    result["gate_reasons"] = reasons
    evaluation = dict(result.get("gate_evaluation", {}))
    evaluation["evidence_action_sufficient"] = quality["accion"]["sufficient"]
    evaluation["evidence_object_sufficient"] = quality["objeto"]["sufficient"]
    evaluation["evidence_geo_sufficient"] = quality["geografica"]["sufficient"]
    if object_exception:
        evaluation["object"] = True
        result["object_gate_exception"] = "broad_explicit_project_without_subtype"
    result["gate_evaluation"] = evaluation
    return result


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
        "decision_residencial": v51._decision_for_scope(residential),
        "decision_inmobiliaria_urbana_amplia": v51._decision_for_scope(broad),
        "decision_documento": v51._decision_for_scope(broad),
    }


def postprocess_result(doc: dict, result: dict) -> tuple[str, dict]:
    parsed = deepcopy(result["parsed"])
    for mention in parsed.get("case_mentions", []):
        v51._enrich_locations(mention)
    derived = derive_document_decisions(parsed.get("case_mentions", []), str(doc.get("text", "")))
    record = {
        "url": doc.get("url"),
        "lineage": doc.get("lineage", {}),
        "corpus_scope": "temporal_v2",
        "contract_version": "v5.2.1",
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


MAX_TEST_URLS_WITHOUT_GATE = 100


def _run(args: argparse.Namespace) -> int:
    # Fix 2026-09-16 (hallazgo de la auditoría cruzada, punto 5, y una segunda ronda
    # que encontro que el fix no bastaba): --urls-file existe para pruebas
    # chicas (10-70 docs) y salta el gate humano/hash-pinning por diseno.
    # Un --urls-file con TODO el corpus pendiente seria, en la practica,
    # una corrida de produccion disfrazada de prueba -- si trae mas de
    # MAX_TEST_URLS_WITHOUT_GATE URLs, se trata como produccion real.
    # SEGUNDO HALLAZGO (la auditoría cruzada, ronda siguiente): --output-file SOLO
    # (sin --urls-file) tambien bypaseaba el gate por completo, aunque
    # procesara los 3835 documentos pendientes enteros -- --output-file
    # nunca acota el ALCANCE de la corrida (solo el DESTINO de la
    # escritura), asi que por si solo nunca debe activar el modo prueba.
    # Solo --urls-file (acotado) o --dry-run cuentan como prueba real.
    urls_filter = {line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if line.strip()} if args.urls_file else None
    bounded_urls_file = bool(urls_filter) and len(urls_filter) <= MAX_TEST_URLS_WITHOUT_GATE
    is_test = bool(bounded_urls_file or args.dry_run)
    for stage in ("fulltext_acquisition_v2", "dedupe_fulltext"):
        if upstream_stage_is_running(stage) and not is_test:
            raise StageSkipped(3, f"{stage} activo; se bloquea produccion")
    if not is_test:
        try:
            artifact = json.loads(REVIEW_ARTIFACT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageSkipped(4, f"no se pudo leer gate v5.2.1: {exc}") from exc
        if not classification_release_allowed(artifact):
            raise StageSkipped(4, "gate humano v5.2.1 pendiente")
    env = v51.load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    docs = v51.load_classifiable_documents(urls_filter=urls_filter)
    done = v51.already_classified_urls(output_path)
    pending = [doc for doc in docs if doc.get("url") not in done]
    if args.limit:
        pending = pending[:args.limit]
    if args.dry_run:
        # Fix 2026-09-16 (hallazgo de la auditoría cruzada, punto 4): antes --dry-run
        # solo recortaba a 1 documento pero SEGUIA llamando a la API real
        # (gastaba dinero pese al nombre). Ahora --dry-run nunca llama a
        # classify_document -- solo reporta cuantos documentos se
        # clasificarian y una muestra de sus URLs, sin tocar la API ni el
        # archivo de salida.
        sample = [doc.get("url", "") for doc in pending[:5]]
        logger.info("DRY RUN (sin llamadas a la API): %d documentos pendientes. Muestra: %s", len(pending), sample)
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    errors_path = output_path.with_name(output_path.stem + ".errors.jsonl")
    # Fix 2026-09-16 (hallazgo de la auditoría cruzada, punto 6): el conteo
    # esperados/escritos/errores solo quedaba en el log, no en un
    # manifiesto durable -- un manifiesto en disco con run_id, hashes de
    # contrato, conteos y costo permite auditar una corrida despues sin
    # tener que ir a buscar el log de esa sesion especifica.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    # Fix 2026-09-16 (hallazgo de la auditoría cruzada, ronda siguiente): el manifiesto
    # usaba siempre el mismo nombre -- si una corrida se interrumpe y se
    # reanuda, el segundo intento sobrescribia la evidencia del primero.
    # Ahora el nombre incluye el run_id, un manifiesto propio por intento.
    manifest_path = output_path.with_name(f"{output_path.stem}.run_manifest.{run_id}.json")
    # Fix 2026-09-16 (hallazgo de la auditoría cruzada, ronda siguiente, deuda menor
    # no bloqueante): el manifiesto pinneaba prompt/schema pero no el
    # script de entrada ni el gate base -- el artefacto de liberacion si
    # los pinnea, agregarlos aqui tambien cierra la misma cobertura.
    _entry_script_path = Path(sys.argv[0]) if sys.argv else Path(__file__)
    run_manifest = {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "output_path": str(output_path),
        "errors_path": str(errors_path),
        "is_test": is_test,
        "prompt_path": str(PROMPT_PATH),
        "prompt_sha256": v51._sha256_file(PROMPT_PATH),
        "schema_path": str(SCHEMA_PATH),
        "schema_sha256": v51._sha256_file(SCHEMA_PATH),
        "entry_script_path": str(_entry_script_path),
        "entry_script_sha256": v51._sha256_file(_entry_script_path),
        "base_gate_path": str(Path(v51.__file__)),
        "base_gate_sha256": v51._sha256_file(Path(v51.__file__)),
        "workers": args.workers,
        "pending_esperados": len(pending),
        "status": "running",
    }
    manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Fix 2026-09-16 (hallazgo de auditoria de punta a punta antes de la
    # primera corrida de produccion real a escala, 3835 documentos): antes
    # todos los registros se acumulaban en memoria y se escribian recien al
    # terminar el ThreadPoolExecutor completo -- un crash, corte de red o
    # kill a mitad de la corrida perdia TODOS los resultados ya pagados,
    # sin ninguna persistencia parcial. Ahora cada registro se escribe (con
    # flush+fsync) apenas su future termina, en el hilo principal que ya
    # consume as_completed() secuencialmente -- sin necesidad de lock
    # adicional, no hay dos escritores concurrentes. Se pierde el orden
    # por URL (antes se ordenaba al final); already_classified_urls() no
    # depende del orden, asi que no afecta la deduplicacion entre corridas.
    # Fix 2026-09-16 (hallazgo de la auditoría cruzada, punto 2): antes un fallo de
    # classify_document (429 agotado, error de conexion, JSON invalido)
    # solo generaba un log.warning() no persistido -- el documento
    # quedaba sin ningun rastro de que se intento y fallo. Ahora cada
    # fallo se escribe a <output>.errors.jsonl con motivo, y se verifica
    # al final que escritos + errores == esperados.
    written = 0
    error_count = 0
    total_cost = 0.0
    with output_path.open("a", encoding="utf-8") as handle, errors_path.open("a", encoding="utf-8") as errors_handle:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(v51.classify_document, doc, api_key, prompt, schema): doc for doc in pending}
            for future in as_completed(futures):
                doc = futures[future]
                url = doc.get("url", "")
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"unhandled_exception: {exc.__class__.__name__}: {exc}"}
                if result is not None and "parsed" in result:
                    # Fix 2026-09-16 (hallazgo de la auditoría cruzada, punto 4): antes
                    # una excepcion dentro de postprocess_result (ej. un
                    # KeyError si el shape de la respuesta del modelo
                    # cambia inesperadamente) se propagaba sin capturar,
                    # abortando toda la corrida SIN dejar ningun rastro en
                    # errors.jsonl para ese documento -- y ademas descartaba
                    # en silencio cualquier resultado ya en vuelo en el
                    # ThreadPoolExecutor al salir del `with`. Ahora se trata
                    # igual que un fallo de classify_document: se registra
                    # en errors.jsonl y la corrida sigue con el resto.
                    try:
                        _, record = postprocess_result(doc, result)
                    except Exception as exc:  # noqa: BLE001
                        # En esta rama result ya tiene "parsed" -- la llamada
                        # a la API fue exitosa y ese costo es real, solo
                        # fallo el postprocesamiento local (sin API). No
                        # perderlo del manifiesto por el mismo motivo que
                        # schema_validation_failed arriba.
                        failed_cost = float((result.get("usage") or {}).get("cost", 0) or 0)
                        total_cost += failed_cost
                        reason = f"postprocess_result_exception: {exc.__class__.__name__}: {exc}"
                        logger.warning("Fallo de postprocesamiento para %s: %s", url[:80], reason)
                        errors_handle.write(json.dumps({
                            "url": url, "error": reason, "lineage": doc.get("lineage", {}),
                            "cost_incurred_usd": failed_cost, "run_id": run_id,
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False) + "\n")
                        errors_handle.flush()
                        os.fsync(errors_handle.fileno())
                        error_count += 1
                        continue
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    written += 1
                    total_cost += float((result.get("usage") or {}).get("cost", 0) or 0)
                else:
                    reason = (result or {}).get("error", "unknown_error_result_none")
                    # Autoauditoria 2026-09-16: un fallo de schema_validation
                    # ocurre DESPUES de una llamada exitosa con costo real ya
                    # incurrido (razonamiento incluido) -- a diferencia de un
                    # rate-limit/error de conexion, donde nunca hubo
                    # respuesta ni costo. Sin esto, ese gasto real
                    # desaparecia del total_cost_usd del manifiesto.
                    failed_cost = float((result or {}).get("usage", {}).get("cost", 0) or 0)
                    total_cost += failed_cost
                    logger.warning("Fallo no recuperable para %s: %s", url[:80], reason)
                    errors_handle.write(json.dumps({
                        "url": url, "error": reason, "lineage": doc.get("lineage", {}),
                        "cost_incurred_usd": failed_cost, "run_id": run_id,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False) + "\n")
                    errors_handle.flush()
                    os.fsync(errors_handle.fileno())
                    error_count += 1
    esperados = len(pending)
    counts_consistent = (written + error_count == esperados)
    if not counts_consistent:
        logger.error(
            "INCONSISTENCIA DE CONTEO: esperados=%d != escritos(%d)+errores(%d)=%d -- revisar %s y %s",
            esperados, written, error_count, written + error_count, output_path, errors_path,
        )
    logger.info(
        "v5.2.1 completado: %d escritos, %d errores, %d esperados -- %s (errores en %s)",
        written, error_count, esperados, output_path, errors_path,
    )
    run_manifest.update({
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "written": written,
        "errors": error_count,
        "esperados": esperados,
        "counts_consistent": counts_consistent,
        "total_cost_usd": round(total_cost, 6),
        "status": "completed" if counts_consistent else "completed_with_count_mismatch",
    })
    manifest_path.write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificacion v5.2.1 con gate de evidencia separado")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    detail = {"output_path": str(output_path), "es_produccion": not bool(args.output_file or args.urls_file or args.dry_run), "schema_version": "v5.2.1"}
    try:
        with acquire_lock("classify_v5_2_1", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
