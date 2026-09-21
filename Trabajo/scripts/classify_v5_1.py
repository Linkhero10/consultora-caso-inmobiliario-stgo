#!/usr/bin/env python3
"""Clasificador v5.1: evidencia literal por arreglos y lookup geografico determinista."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
import unicodedata
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_v5 import already_classified_urls, load_classifiable_documents, load_env  # noqa: E402
from pipeline_lock import LockBusyError, StageSkipped, acquire_lock, upstream_stage_is_running  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("classify_v5_1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "Trabajo" / "config" / "classification_schema_v5_1.json"
PROMPT_PATH = PROJECT_ROOT / "Trabajo" / "prompts" / "classifier_system_v5_1.md"
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5_1"
CLASSIFICATIONS_PATH = OUTPUT_DIR / "classifications.jsonl"
REVIEW_ARTIFACT_PATH = PROJECT_ROOT / "Auditoria" / "muestras_control" / "review_sample_v5_1_amplio.json"
MODEL = "openai/gpt-5.6-luna"
REASONING_EFFORT = "xhigh"
MAX_TEXT_CHARS_FOR_PROMPT = 30000
MAX_RETRIES = 5
MIN_EVIDENCE_QUOTE_CHARS = 15

RESIDENTIAL_OBJECTS = {
    "edificio_residencial", "ds19", "condominio", "loteo_residencial",
    "uso_mixto_residencial", "instrumento_urbano_residencial",
}
BROAD_OBJECTS = RESIDENTIAL_OBJECTS | {
    "centro_comercial", "edificio_oficinas", "hotel", "proyecto_industrial",
    "equipamiento_urbano", "infraestructura_no_residencial",
    "inmobiliario_privado_no_residencial", "instrumento_urbano_general",
}
# Objetos del universo amplio que son legítimamente conflictos urbanos sin
# ser, por definición, "proyectos inmobiliarios" (es_proyecto_inmobiliario
# puede ser "no" sin que eso los excluya): instrumentos normativos puros
# (declaración de humedal urbano, modificación de plan regulador) y
# equipamiento/infraestructura pública sin promotor inmobiliario privado.
BROAD_NON_REAL_ESTATE_OBJECTS = {
    "instrumento_urbano_general", "equipamiento_urbano", "infraestructura_no_residencial",
}
SCOPES = {"residencial", "inmobiliaria_urbana_amplia"}

COMUNA_INE_CODES = {
    "Santiago": "13101", "Cerrillos": "13102", "Cerro Navia": "13103", "Conchalí": "13104",
    "El Bosque": "13105", "Estación Central": "13106", "Huechuraba": "13107", "Independencia": "13108",
    "La Cisterna": "13109", "La Florida": "13110", "La Granja": "13111", "La Pintana": "13112",
    "La Reina": "13113", "Las Condes": "13114", "Lo Barnechea": "13115", "Lo Espejo": "13116",
    "Lo Prado": "13117", "Macul": "13118", "Maipú": "13119", "Ñuñoa": "13120",
    "Pedro Aguirre Cerda": "13121", "Peñalolén": "13122", "Providencia": "13123", "Pudahuel": "13124",
    "Quilicura": "13125", "Quinta Normal": "13126", "Recoleta": "13127", "Renca": "13128",
    "San Joaquín": "13129", "San Miguel": "13130", "San Ramón": "13131", "Vitacura": "13132",
}


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.lower().split())


_COMUNA_BY_KEY = {_key(name): code for name, code in COMUNA_INE_CODES.items()}


def derive_ine_code(comuna: str) -> str:
    """Devuelve codigo INE solo para las 32 comunas del area de estudio."""
    return _COMUNA_BY_KEY.get(_key(comuna), "")


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def quote_flags(quotes: Any, source_text: str) -> tuple[list[bool], bool, bool]:
    values = quotes if isinstance(quotes, list) else []
    cleaned = [str(q).strip() for q in values]
    flags = [bool(q) and len(q) >= MIN_EVIDENCE_QUOTE_CHARS and normalize_text(q) in normalize_text(source_text) for q in cleaned]
    sufficient = bool(flags) and any(flags)
    contract_valid = sufficient and all(flags)
    return flags, sufficient, contract_valid


def _decision_for_scope(results: list[dict[str, Any]]) -> str:
    if not results:
        return "insufficient_content"
    decisions = {str(result.get("decision_final", "uncertain")) for result in results}
    if "include" in decisions:
        return "include"
    if "uncertain" in decisions:
        return "uncertain"
    if "exclude" in decisions:
        return "exclude"
    return "insufficient_content"


def apply_scope_gate(parsed: dict[str, Any], source_text: str, scope: str) -> dict[str, Any]:
    if scope not in SCOPES:
        raise ValueError(f"scope no soportado: {scope}")
    result = deepcopy(parsed)
    reasons: list[str] = []
    model_decision = str(parsed.get("decision", "uncertain"))
    action = str(parsed.get("accion_contenciosa", "")).strip().lower()
    action_type = str(parsed.get("tipo_accion_contenciosa", "")).strip().lower()
    object_type = str(parsed.get("tipo_objeto_norm", "")).strip().lower()
    real_estate = str(parsed.get("es_proyecto_inmobiliario", "")).strip().lower()
    residential = str(parsed.get("es_proyecto_vivienda_inmobiliario", "")).strip().lower()
    relation = str(parsed.get("relacion_inmobiliaria_urbana", "")).strip().lower()
    geography = str(parsed.get("precision_geografica", "")).strip().lower()
    depth = str(parsed.get("profundidad_documentacion_caso", "")).strip().lower()
    comuna = str(parsed.get("comuna", "")).strip()

    action_flags, action_ok, action_contract = quote_flags(parsed.get("evidencia_accion_quotes"), source_text)
    object_flags, object_ok_evidence, object_contract = quote_flags(parsed.get("evidencia_objeto_quotes"), source_text)
    geo_flags, geo_ok_evidence, geo_contract = quote_flags(parsed.get("evidencia_geografica_quotes"), source_text)
    result["decision_modelo"] = model_decision
    result["scope"] = scope
    result["evidence_action_quotes_verified"] = action_flags
    result["evidence_object_quotes_verified"] = object_flags
    result["evidence_geo_quotes_verified"] = geo_flags
    result["evidence_action_verified"] = action_ok
    result["evidence_object_verified"] = object_ok_evidence
    result["evidence_geo_verified"] = geo_ok_evidence

    if model_decision != "include":
        result["decision_final"] = model_decision
        result["gate_reasons"] = reasons
        return result

    if action != "confirmada" or action_type in {"", "ninguna", "incierta"}:
        reasons.append("sin_accion_contenciosa" if action in {"no", "ninguna"} else "accion_contenciosa_incierta")

    object_ok = object_type in (RESIDENTIAL_OBJECTS if scope == "residencial" else BROAD_OBJECTS)
    if scope == "residencial":
        object_ok = object_ok and residential == "si"
    else:
        # Un instrumento urbano, equipamiento o infraestructura no residencial
        # puede ser objeto legítimo del universo amplio sin ser, en sí mismo,
        # un "proyecto inmobiliario" (es_proyecto_inmobiliario=no es coherente
        # con una disputa puramente regulatoria/de infraestructura, ej. una
        # declaración de humedal urbano o una modificación de plan regulador).
        # Exigir real_estate=="si" en estos casos contradecía la propia
        # definición del universo amplio y excluía sistemáticamente ese patrón.
        object_ok = object_ok and (
            real_estate == "si" or object_type in BROAD_NON_REAL_ESTATE_OBJECTS
        )
    if scope == "inmobiliaria_urbana_amplia" and relation == "ocupacion_propiedad_sin_desarrollo":
        object_ok = False
        reasons.append("objeto_existente_sin_vinculo_urbano")
    if not object_ok and "objeto_existente_sin_vinculo_urbano" not in reasons:
        if scope == "residencial" and real_estate == "si" and residential == "no":
            reasons.append("objeto_fuera_de_alcance_residencial")
        elif object_type in {"", "none", "objeto_no_determinado"} or real_estate in {"", "incierto"}:
            reasons.append("objeto_no_determinado")
        else:
            reasons.append("objeto_no_admisible")

    if geography == "fuera_de_area":
        reasons.append("fuera_del_area_geografica")
    elif geography in {"", "ambigua", "provincia_general"}:
        reasons.append("geografia_incierta")
    elif comuna and _key(comuna) not in _COMUNA_BY_KEY and geography in {"proyecto_exacto", "sector_barrio", "comuna"}:
        reasons.append("fuera_del_area_geografica")

    if depth == "mencion_tangencial":
        reasons.append("mencion_tangencial")
    elif depth not in {"caso_principal", "caso_secundario_documentado"}:
        reasons.append("caso_insuficientemente_documentado")

    for label, sufficient, valid in (("accion", action_ok, action_contract), ("objeto", object_ok_evidence, object_contract), ("geografica", geo_ok_evidence, geo_contract)):
        if not sufficient:
            reasons.append(f"evidencia_{label}_no_verificada")
        elif not valid:
            reasons.append(f"evidencia_{label}_contrato_invalido")

    hard_exclude = {"sin_accion_contenciosa", "objeto_fuera_de_alcance_residencial", "objeto_no_admisible", "objeto_existente_sin_vinculo_urbano", "fuera_del_area_geografica", "mencion_tangencial"}
    result["decision_final"] = "exclude" if hard_exclude.intersection(reasons) else ("uncertain" if reasons else "include")
    result["gate_reasons"] = reasons
    result["gate_evaluation"] = {"action": action == "confirmada" and action_type not in {"", "ninguna", "incierta"}, "object": object_ok, "geography": geography not in {"fuera_de_area", "", "ambigua", "provincia_general"}, "depth": depth in {"caso_principal", "caso_secundario_documentado"}, "evidence_action": action_ok and action_contract, "evidence_object": object_ok_evidence and object_contract, "evidence_geo": geo_ok_evidence and geo_contract}
    return result


def derive_document_decisions(mentions: list[dict[str, Any]], source_text: str) -> dict[str, Any]:
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
    return {"case_mentions": processed, "decision_residencial": _decision_for_scope(residential), "decision_inmobiliaria_urbana_amplia": _decision_for_scope(broad), "decision_documento": _decision_for_scope(broad)}


def validate_classification_payload(parsed: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        jsonschema.validate(instance=parsed, schema=schema.get("schema", schema))
    except jsonschema.ValidationError as exc:
        logger.warning("Respuesta v5.1 invalida contra schema: %s", exc.message[:240])
        return False
    return True


def classify_document(doc: dict[str, Any], api_key: str, system_prompt: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve {'parsed':..., ...} en exito, o {'error': '<codigo>'} en
    fallo -- 2026-09-16: antes devolvia None sin razon, y el fallo se perdia
    en un log.warning() no persistido. errors.jsonl (escrito por _run())
    depende de este codigo para no quedar en blanco."""
    text = str(doc.get("text", ""))[:MAX_TEXT_CHARS_FOR_PROMPT]
    payload = {"model": MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"TITULO: {doc.get('title') or doc.get('discovery_title', '')}\nURL: {doc.get('url', '')}\n\nTEXTO DEL ARTICULO:\n{text}"}], "reasoning": {"effort": REASONING_EFFORT}, "response_format": {"type": "json_schema", "json_schema": schema}}
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=payload, timeout=60)
            if response.status_code == 429:
                if attempt == MAX_RETRIES:
                    return {"error": "rate_limited_max_retries"}
                time.sleep((2 ** attempt) + random.uniform(0, 1))
                continue
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            parsed = json.loads(message["content"])
            if not validate_classification_payload(parsed, schema):
                # Autoauditoria 2026-09-16: a diferencia de un rate-limit o
                # error de conexion (donde nunca hubo respuesta y nunca se
                # cobro nada), aqui SI hubo una llamada exitosa con costo
                # real (razonamiento incluido) -- solo el contenido no paso
                # la validacion del schema. Conservar usage para que ese
                # costo no desaparezca del manifiesto de la corrida.
                return {"error": "schema_validation_failed", "usage": data.get("usage", {})}
            return {"parsed": parsed, "usage": data.get("usage", {}), "reasoning": message.get("reasoning"), "reasoning_details": message.get("reasoning_details"), "raw_finish_reason": data["choices"][0].get("finish_reason")}
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_RETRIES:
                return {"error": f"connection_error_max_retries: {exc.__class__.__name__}"}
            time.sleep((2 ** attempt) + random.uniform(0, 1))
        except (KeyError, json.JSONDecodeError, TypeError) as exc:
            return {"error": f"response_parse_error: {exc.__class__.__name__}"}
    return {"error": "unknown_error_retry_loop_exhausted"}


def _enrich_locations(mention: dict[str, Any]) -> None:
    for location in mention.get("lugares_mencionados", []):
        name = str(location.get("nombre", ""))
        code = derive_ine_code(name) if location.get("tipo") == "comuna" else ""
        location["codigo_comuna_ine"] = code
        location["en_area_estudio"] = "si" if code else ("incierto" if location.get("tipo") in {"comuna", "ciudad", "region"} else "incierto")
    mention["codigo_comuna_ine"] = derive_ine_code(str(mention.get("comuna", "")))


def postprocess_result(doc: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parsed = deepcopy(result["parsed"])
    for mention in parsed.get("case_mentions", []):
        _enrich_locations(mention)
    derived = derive_document_decisions(parsed.get("case_mentions", []), str(doc.get("text", "")))
    record = {"url": doc.get("url"), "lineage": doc.get("lineage", {}), "corpus_scope": "temporal_v2", "contract_version": "v5.1", "classified_at": datetime.now(timezone.utc).isoformat(), "model": MODEL, "reasoning_effort": REASONING_EFFORT, "reasoning": result.get("reasoning"), "reasoning_details": result.get("reasoning_details"), "usage": result.get("usage", {}), "decision_modelo": parsed.get("decision"), **parsed, **derived}
    return str(record["decision_documento"]), record


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def classification_release_reasons(review_artifact: dict[str, Any]) -> list[str]:
    """Hash-pinning del gate (2026-09-16, hallazgo de auditoria cruzada
    la auditoría cruzada): antes classification_release_allowed() solo verificaba 3
    booleanos, sin confirmar que el artefacto aprobado corresponda al
    prompt/schema/script/muestra ACTUALES -- un artefacto viejo podia
    autorizar silenciosamente un contrato nuevo sin revisar. Devuelve una
    lista vacia si la liberacion es valida, o la lista de motivos de
    bloqueo si no."""
    reasons: list[str] = []
    policy = review_artifact.get("review_policy", review_artifact)
    if review_artifact.get("status") != "aprobado_revision_humana":
        reasons.append("status != aprobado_revision_humana")
    if policy.get("human_review_completed") is not True:
        reasons.append("review_policy.human_review_completed != true")
    if policy.get("production_allowed") is not True:
        reasons.append("review_policy.production_allowed != true")
    if reasons:
        return reasons

    fingerprint = review_artifact.get("contract_fingerprint")
    if not isinstance(fingerprint, dict):
        return ["artefacto sin contract_fingerprint -- no se puede verificar que autorice el contrato vigente"]

    checks = [
        ("prompt", PROMPT_PATH, fingerprint.get("prompt_path"), fingerprint.get("prompt_sha256")),
        ("schema", SCHEMA_PATH, fingerprint.get("schema_path"), fingerprint.get("schema_sha256")),
        ("script de entrada", Path(sys.argv[0]) if sys.argv else Path(__file__), fingerprint.get("entry_script_path"), fingerprint.get("entry_script_sha256")),
        ("gate base (classify_v5_1.py)", Path(__file__), fingerprint.get("base_gate_path"), fingerprint.get("base_gate_sha256")),
    ]
    # extra_gate_files: lista libre de {label, path, sha256} para pinnear
    # cualquier archivo adicional del camino de ejecucion (ej. los wrappers
    # classify_v5_2_1.py/classify_v5_2_2.py que hacen el monkeypatching real
    # -- classify_v5_1.py deliberadamente no conoce sus nombres para no
    # invertir la capa de dependencia; quien construye el artefacto declara
    # que archivos importan para SU cadena de ejecucion concreta).
    extra_files = fingerprint.get("extra_gate_files")
    for entry in (extra_files if isinstance(extra_files, list) else []):
        if not isinstance(entry, dict):
            reasons.append("contract_fingerprint.extra_gate_files tiene una entrada invalida (no es un objeto)")
            continue
        label = str(entry.get("label") or entry.get("path") or "archivo adicional")
        declared_path = entry.get("path")
        declared_hash = entry.get("sha256")
        if not declared_path or not declared_hash:
            reasons.append(f"contract_fingerprint incompleto para {label} (falta path o hash declarado)")
            continue
        checks.append((label, PROJECT_ROOT / declared_path, declared_path, declared_hash))

    for label, current_path, declared_path, declared_hash in checks:
        if not declared_path or not declared_hash:
            reasons.append(f"contract_fingerprint incompleto para {label} (falta path o hash declarado)")
            continue
        current_rel = _relpath(current_path)
        if current_rel != str(declared_path).replace("\\", "/"):
            reasons.append(f"{label}: ruta vigente ({current_rel}) no coincide con la declarada en el artefacto ({declared_path})")
            continue
        current_hash = _sha256_file(current_path)
        if current_hash is None:
            reasons.append(f"{label}: no se pudo leer el archivo vigente en {current_rel}")
        elif current_hash != declared_hash:
            reasons.append(f"{label}: hash vigente ({current_hash[:12]}...) no coincide con el declarado en el artefacto ({str(declared_hash)[:12]}...) -- el contrato cambio desde que se aprobo")

    review_sample_path = fingerprint.get("human_review_sample_path")
    declared_sample_hash = fingerprint.get("human_review_sample_sha256")
    if review_sample_path and declared_sample_hash:
        sample_full_path = PROJECT_ROOT / review_sample_path
        current_sample_hash = _sha256_file(sample_full_path)
        if current_sample_hash is None:
            reasons.append(f"muestra de revision humana: no se pudo leer {review_sample_path}")
        elif current_sample_hash != declared_sample_hash:
            reasons.append("muestra de revision humana: el archivo cambio desde que se aprobo el artefacto (hash no coincide)")
    else:
        reasons.append("contract_fingerprint incompleto: falta human_review_sample_path/sha256")

    return reasons


def classification_release_allowed(review_artifact: dict[str, Any]) -> bool:
    return not classification_release_reasons(review_artifact)


def _run(args: argparse.Namespace) -> int:
    is_test = bool(args.output_file or args.urls_file or args.dry_run)
    for stage in ("fulltext_acquisition_v2", "dedupe_fulltext"):
        if upstream_stage_is_running(stage) and not is_test:
            raise StageSkipped(3, f"{stage} activo; se bloquea produccion")
    if not is_test:
        try:
            artifact = json.loads(REVIEW_ARTIFACT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StageSkipped(4, f"no se pudo leer gate v5.1: {exc}") from exc
        blocking_reasons = classification_release_reasons(artifact)
        if blocking_reasons:
            raise StageSkipped(4, "gate humano v5.1 pendiente: " + "; ".join(blocking_reasons))
    env = load_env(ENV_PATH)
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    urls_filter = {line.strip() for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if line.strip()} if args.urls_file else None
    docs = load_classifiable_documents(urls_filter=urls_filter)
    done = already_classified_urls(output_path)
    pending = [doc for doc in docs if doc.get("url") not in done]
    if args.dry_run:
        pending = pending[:1]
    elif args.limit:
        pending = pending[:args.limit]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(classify_document, doc, api_key, prompt, schema): doc for doc in pending}
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
    logger.info("v5.1 completado: %d registros escritos en %s", len(records), output_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificacion v5.1 por menciones, citas literales y doble alcance")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    output_path = Path(args.output_file) if args.output_file else CLASSIFICATIONS_PATH
    detail = {"output_path": str(output_path), "es_produccion": not bool(args.output_file or args.urls_file or args.dry_run), "schema_version": "v5.1"}
    try:
        with acquire_lock("classify_v5_1", detail=detail):
            return _run(args)
    except LockBusyError as exc:
        logger.info(str(exc))
        return 2
    except StageSkipped as exc:
        logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
