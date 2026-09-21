#!/usr/bin/env python3
"""Gate v5.2.2 (idéntico, sin cambios) + prompt v5.2.4: frontera para actos
simbólicos/conmemorativos/de nomenclatura.

Hallazgo 2026-09-15: una muestra ciega ALEATORIA de 50 documentos nunca
antes clasificados (fuera del set usado para afinar el gate) encontró un
patrón de falso positivo nuevo -- 2 artículos sobre el mismo caso (cambio de
nombre de la calle Namur, Santiago, conmemoración de los 50 años del golpe)
quedaban `include` con `tipo_objeto_norm=infraestructura_no_residencial`
pese a no ser una intervención física real, solo un acto de nomenclatura.
El fix es de prompt (classifier_system_v5_2_4.md agrega una frontera
explícita), no de gate determinista -- el gate v5.2.2 ya funciona bien,
el problema era que el modelo etiquetaba mal el objeto.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import classify_v5_2_1 as previous  # noqa: E402
import classify_v5_2_2 as gate  # noqa: E402
import classify_v5_1 as v51  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "Trabajo" / "config" / "classification_schema_v5_2_3.json"
PROMPT_PATH = PROJECT_ROOT / "Trabajo" / "prompts" / "classifier_system_v5_2_4.md"
CONTRACT_VERSION = "v5.2.3"


def postprocess_result(doc: dict[str, Any], result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    parsed = deepcopy(result["parsed"])
    for mention in parsed.get("case_mentions", []):
        v51._enrich_locations(mention)
    # Reutiliza el gate v5.2.2 tal cual (geografia compuesta, citas cortas,
    # fix de objeto de classify_v5_1.py) -- solo cambia el prompt de entrada.
    source_text = str(doc.get("text", ""))
    derived = gate.derive_document_decisions(parsed.get("case_mentions", []), source_text)
    record = {
        "url": doc.get("url"),
        "lineage": doc.get("lineage", {}),
        # Fix 2026-09-16 (hallazgo de la auditoría cruzada, punto 3): el registro no
        # traia ningun hash del texto realmente clasificado -- se podia
        # reconstruir cruzando otros manifests, pero no era autosuficiente.
        # Hash sobre el texto COMPLETO tal como lo devolvio
        # load_classifiable_documents() (antes del truncado a
        # MAX_TEXT_CHARS_FOR_PROMPT que aplica classify_document
        # internamente) -- si el documento se trunco para el prompt, este
        # hash es del texto de origen, no de lo que vio el modelo.
        "content_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "content_char_count": len(source_text),
        "corpus_scope": "temporal_v2",
        "contract_version": CONTRACT_VERSION,
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "model": previous.MODEL,
        "reasoning_effort": previous.REASONING_EFFORT,
        "reasoning": result.get("reasoning"),
        "reasoning_details": result.get("reasoning_details"),
        "usage": result.get("usage", {}),
        "decision_modelo": parsed.get("decision"),
        **parsed,
        **derived,
    }
    return str(record["decision_documento"]), record


def main() -> int:
    parser = argparse.ArgumentParser(description="Clasificación gate v5.2.2 + prompt v5.2.4 (frontera de actos simbólicos)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--urls-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--workers", type=int, default=50)
    args = parser.parse_args()
    # El ejecutor heredado (classify_v5_2_1._run) consulta su propio
    # classification_release_allowed(). Sin este cableado, la produccion
    # v5.2.3 quedaria protegida solo por tres booleanos y saltaria el
    # hash-pinning implementado en classify_v5_1.py.
    v51.PROMPT_PATH = PROMPT_PATH
    v51.SCHEMA_PATH = SCHEMA_PATH
    previous.classification_release_allowed = v51.classification_release_allowed
    previous.PROMPT_PATH = PROMPT_PATH
    previous.SCHEMA_PATH = SCHEMA_PATH
    previous.postprocess_result = postprocess_result
    previous.CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion_luna_v5_2_3" / "classifications.jsonl"
    # Fix 2026-09-16 (autoauditoria tras el hallazgo de --output-file de
    # la auditoría cruzada): este "es_produccion" es solo metadata informativa para
    # el lock/run_state.json -- el gate real vive en _run(). Pero seguia
    # usando la formula VIEJA (cualquier output_file/urls_file/dry_run =
    # prueba), que ya no coincide con la logica real de _run() (solo
    # urls_file acotado o dry_run cuentan). Sin este fix, una corrida real
    # con --output-file quedaria correctamente protegida por el gate pero
    # MAL etiquetada como prueba en run_state.json -- inconsistencia
    # exactamente del tipo que las rondas anteriores de auditoria buscaban.
    _urls_for_detail = {l.strip() for l in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if l.strip()} if args.urls_file else None
    _bounded_for_detail = bool(_urls_for_detail) and len(_urls_for_detail) <= previous.MAX_TEST_URLS_WITHOUT_GATE
    detail = {
        "output_path": str(Path(args.output_file) if args.output_file else previous.CLASSIFICATIONS_PATH),
        "es_produccion": not bool(_bounded_for_detail or args.dry_run),
        "schema_version": "v5.2.3",
        "prompt_version": "v5.2.4",
        "gate_version": "v5.2.2",
    }
    try:
        with previous.acquire_lock("classify_v5_2_3", detail=detail):
            return previous._run(args)
    except previous.LockBusyError as exc:
        previous.logger.info(str(exc))
        return 2
    except previous.StageSkipped as exc:
        previous.logger.warning(str(exc))
        return exc.return_code


if __name__ == "__main__":
    raise SystemExit(main())
