"""Fuente unica de verdad para leer la extraccion por LLM (enrichment).

La extraccion se ejecuta en una o mas corridas (`src/enrich.py --run-name ...`), cada una con su
carpeta `intermediate/enrichment/<run-name>/enrichment.jsonl`. Este modulo une todas las corridas
y aplica dos guardas que cualquier consumidor (ETL de enrichment, proyectos, conflictos) debe
compartir en vez de reimplementar:

- una URL no puede aparecer en dos corridas (las corridas son disjuntas por construccion; un
  duplicado es una senal de bug que hay que investigar, nunca "gana la primera" en silencio);
- `case_mention_index` es posicional sobre un `classifications.jsonl` concreto: si ese archivo
  cambia de contenido u orden, la traduccion indice -> `case_mention_id` deja de ser valida y la
  construccion aborta (`verify_classifications_sha256`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from paths import CLASSIFICATIONS_PATH, ENRICHMENT_DIR

CLASSIFICATIONS_SHA256_EXPECTED = "fc96bf57a34e13a10016087efe856a30ce83b37e6a7af87631af57469d597af7"

# Documentos con extraccion que quedan fuera del universo publicado: la corrida de control inicial
# incluyo uno que no forma parte del universo auditado de forma independiente. Su registro existe
# y paso las verificaciones automaticas, pero no se usa salvo peticion explicita.
EXCLUDED_URLS = frozenset({
    "https://www.chilevision.cl/noticias/reportajes/cronicas/suprema-falla-contra-proyecto-inmobiliario-de-dos-edificios-con-mas-de-mil-departamentos-en-estacion-central/",
})


def _first_timestamp(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return json.loads(line).get("enriched_at", "")
    return ""


def enrichment_files() -> list[Path]:
    """`enrichment.jsonl` de cada corrida, en orden CRONOLOGICO (fecha del primer registro).

    El orden importa para desempates aguas abajo (por ejemplo, que nombre de proyecto es canonico entre variantes de
    igual frecuencia); fijarlo por fecha lo vuelve independiente de como se llamen las carpetas."""
    if not ENRICHMENT_DIR.exists():
        return []
    files = [path for path in ENRICHMENT_DIR.glob("*/enrichment.jsonl") if path.is_file()]
    return sorted(files, key=lambda path: (_first_timestamp(path), path.parent.name))


def enriched_urls_in_all_runs() -> set[str]:
    """URLs con extraccion en cualquier corrida (para no volver a pagar un documento)."""
    urls: set[str] = set()
    for path in enrichment_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    urls.add(json.loads(line).get("url", ""))
                except json.JSONDecodeError:
                    continue
    return urls


def verify_classifications_sha256() -> None:
    """Aborta si `classifications.jsonl` cambio de contenido (ver docstring del modulo)."""
    if not CLASSIFICATIONS_PATH.exists():
        raise RuntimeError(f"No existe {CLASSIFICATIONS_PATH} -- no se puede traducir case_mention_index sin la fuente original.")
    actual_sha256 = hashlib.sha256(CLASSIFICATIONS_PATH.read_bytes()).hexdigest()
    if actual_sha256 != CLASSIFICATIONS_SHA256_EXPECTED:
        raise RuntimeError(
            f"{CLASSIFICATIONS_PATH} cambio de contenido (sha256 actual={actual_sha256}, "
            f"esperado={CLASSIFICATIONS_SHA256_EXPECTED}). El case_mention_index es posicional sobre "
            "ese archivo especifico: si cambio el orden o el contenido de case_mentions, la traduccion "
            "index->case_mention_id ya no es valida. Abortando en vez de seguir con una traduccion "
            "potencialmente incorrecta."
        )


def load_enrichment_records(include_excluded: bool = False, files: list[Path] | None = None) -> dict[str, dict[str, Any]]:
    """Une las corridas de extraccion y devuelve dict[url] -> registro."""
    records: dict[str, dict[str, Any]] = {}
    seen_in: dict[str, Path] = {}
    for path in files if files is not None else enrichment_files():
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            url = rec.get("url")
            if not url or (not include_excluded and url in EXCLUDED_URLS):
                continue
            if url in seen_in:
                raise RuntimeError(
                    f"URL duplicada entre corridas de extraccion: {url!r} aparece en {seen_in[url]} y en "
                    f"{path}. Las corridas deben ser disjuntas; investigar antes de continuar."
                )
            seen_in[url] = path
            records[url] = rec
    return records
