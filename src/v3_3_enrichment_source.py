"""Fuente unica de verdad para leer el enrichment v3.3 (2026-09-26).

Migracion completa v3.2->v3.3: los 934/934 documentos productivos ya tienen
enriquecimiento v3.3 (case_mention_index por proyecto mencionado), repartidos
en 3 archivos JSONL generados en momentos distintos (piloto/calibracion/
escalamiento). Antes de este modulo, la logica de "leer los 3 archivos,
excluir el documento fuera de universo, verificar el sha256 de
classifications.jsonl" vivia duplicada dentro de
build_conflicts.py::load_v3_3_verified_links(). Se extrae aqui para que
build_enrichment_tables.py, build_projects.py y build_conflicts.py compartan
la MISMA implementacion -- nunca tres lecturas independientes del mismo dato.

Ningun consumidor de este modulo debe re-implementar el parseo/exclusion/
guard de sha256; deben importar de aqui.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion" / "classifications.jsonl"
CLASSIFICATIONS_SHA256_EXPECTED = "fc96bf57a34e13a10016087efe856a30ce83b37e6a7af87631af57469d597af7"

V3_3_ENRICHMENT_FILES = [
    PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_3_piloto" / "enrichment.jsonl",
    PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_3_calibracion" / "enrichment.jsonl",
    PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_3_escalamiento" / "enrichment.jsonl",
]

# Unico documento del piloto v3.3 que quedo fuera de la definicion estricta
# del universo original de 330 (ambiguedad genuina: >1 case_mention + >=1
# proyecto) y que por eso nunca paso por ninguna de las 2 rondas de revision
# ciega de Sol. Su dato v3.3 existe (y paso las mismas verificaciones
# automaticas de citas/schema que cualquier otro registro) pero no tiene la
# capa adicional de auditoria externa que los otros 933 documentos si
# tienen -- se excluye por defecto de load_v3_3_records() para que quien lo
# necesite lo pida explicitamente y sepa por que.
V3_3_URL_FUERA_DE_UNIVERSO = "https://www.chilevision.cl/noticias/reportajes/cronicas/suprema-falla-contra-proyecto-inmobiliario-de-dos-edificios-con-mas-de-mil-departamentos-en-estacion-central/"


def verify_classifications_sha256() -> None:
    """Aborta si `classifications.jsonl` cambio de contenido.

    El `case_mention_index` de v3.3 es posicional sobre ESE archivo
    especifico (mismo orden que `case_mention.mention_index`). Si el
    archivo cambio de orden o contenido, la traduccion index->case_mention_id
    ya no es valida -- mejor abortar que seguir con una traduccion
    potencialmente incorrecta en silencio.
    """
    if not CLASSIFICATIONS_PATH.exists():
        raise RuntimeError(f"No existe {CLASSIFICATIONS_PATH} -- no se puede traducir case_mention_index sin la fuente original.")
    actual_sha256 = hashlib.sha256(CLASSIFICATIONS_PATH.read_bytes()).hexdigest()
    if actual_sha256 != CLASSIFICATIONS_SHA256_EXPECTED:
        raise RuntimeError(
            f"{CLASSIFICATIONS_PATH} cambio de contenido (sha256 actual={actual_sha256}, "
            f"esperado={CLASSIFICATIONS_SHA256_EXPECTED}). El case_mention_index de v3.3 es "
            "posicional sobre ESE archivo especifico -- si cambio el orden o el contenido de "
            "case_mentions, la traduccion index->case_mention_id ya no es valida. Abortando en "
            "vez de seguir con una traduccion potencialmente incorrecta."
        )


def load_v3_3_records(include_fuera_de_universo: bool = False) -> dict[str, dict[str, Any]]:
    """Lee los 3 archivos de enrichment v3.3 y devuelve dict[url] -> record.

    Valida que ninguna URL se repita entre los 3 archivos -- deben ser
    disjuntos por construccion (cada documento se enriquecio una sola vez,
    en una sola tanda). Un duplicado real es una senal de bug que hay que
    investigar, nunca "el primero gana" en silencio (a diferencia del
    patron viejo en build_enrichment_tables.py que si tolera duplicados
    entre corridas de RE-clasificacion del mismo v3.2).

    No verifica el sha256 de classifications.jsonl por si solo -- eso es
    responsabilidad de verify_classifications_sha256(), llamada aparte por
    quien vaya a traducir case_mention_index a case_mention_id (leer los
    records por si solos, ej. para conteos, no requiere el guard).
    """
    records: dict[str, dict[str, Any]] = {}
    seen_in: dict[str, Path] = {}
    for path in V3_3_ENRICHMENT_FILES:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            url = rec.get("url")
            if not url:
                continue
            if not include_fuera_de_universo and url == V3_3_URL_FUERA_DE_UNIVERSO:
                continue
            if url in seen_in:
                raise RuntimeError(
                    f"URL duplicada entre archivos de enrichment v3.3: {url!r} aparece en "
                    f"{seen_in[url]} Y en {path} -- los 3 archivos deben ser disjuntos por "
                    "construccion. Investigar antes de continuar, no elegir uno arbitrariamente."
                )
            seen_in[url] = path
            records[url] = rec
    return records
