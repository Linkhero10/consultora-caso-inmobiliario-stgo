"""Higiene de la release publica.

El repositorio publico debe leerse como un producto terminado, no como el proceso que lo
produjo. Esta regla existia solo como texto en las instrucciones internas y se violo de forma
repetida (archivos con sufijos de version, nombres de revisores en textos publicos, rutas a
carpetas internas); ahora es una prueba que corre en cada push.

Que se exige a todo archivo versionado (salvo las excepciones listadas):
- nombres sin sufijos de version ni fechas de trabajo (`_v1`, `_v3_3`, `2026-09-29`);
- sin nombres de revisores humanos o de IA en el texto;
- sin rutas a carpetas internas (trabajo, auditoria en bruto, bitacora);
- en la prosa (README, documentos), sin numeros de version ni rondas de correccion: la version
  de la release vive en `pyproject.toml`, en el manifiesto y en la tabla `release_metadata`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Rutas exentas: datos de terceros/binarios, la salida generada del tablero y los archivos que
# por definicion nombran las carpetas internas para ignorarlas.
EXEMPT_PREFIXES = ("Fuentes/", "data/", "docs/index.html", "docs/manzanas_censales.geojson")
EXEMPT_FILES = {".gitignore", ".gitattributes", "tests/test_release_hygiene.py"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".txt", ".html", ".csv"}
PROSE_FILES = ("README.md", "START_HERE.md", "DATA_NOTICE.md")
PROSE_DIRS = ("docs/", "audit/")

VERSION_IN_NAME = re.compile(r"(?<![A-Za-z0-9])v\d+(?:[._]\d+)*(?![A-Za-z0-9])")
DATE_IN_NAME = re.compile(r"\d{4}[-_]\d{2}[-_]\d{2}")
# "Marie Claude" es el nombre de una persona citada en un articulo, no un revisor.
REVIEWER_NAMES = re.compile(r"(?<!Marie )\b(Sol|Luna|Codex|Claude|Anthropic|OpenAI|GPT-?\d[\w.]*)\b")
INTERNAL_PATHS = re.compile(r"(Trabajo|Auditoria|Productos|_FARO)[/\\]|BITACORA|FARO\.md")
ABSOLUTE_PATHS = re.compile(r"[A-Za-z]:[\/]+(?:Users|Felipe|FARO|Temp)|/home/\w+/|C:\\Users")
VERSION_IN_PROSE = re.compile(r"(?<![A-Za-z0-9])v\d+[._]\d+(?:[._]\d+)*(?![A-Za-z0-9])|\bFix \d[A-F]\b|\bronda \d+\b", re.IGNORECASE)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def _in_scope(path: str) -> bool:
    return path not in EXEMPT_FILES and not path.startswith(EXEMPT_PREFIXES)


def _read(path: str) -> str | None:
    if Path(path).suffix.lower() not in TEXT_SUFFIXES:
        return None
    try:
        return (PROJECT_ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return None


def _is_prose(path: str) -> bool:
    return path in PROSE_FILES or (path.startswith(PROSE_DIRS) and path.endswith(".md"))


def collect_violations() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"nombre": [], "revisores": [], "rutas_internas": [], "rutas_absolutas": [], "version_en_prosa": []}
    for path in _tracked_files():
        if not _in_scope(path):
            continue
        name = Path(path).name
        if VERSION_IN_NAME.search(name) or DATE_IN_NAME.search(name):
            result["nombre"].append(path)
        text = _read(path)
        if text is None:
            continue
        if REVIEWER_NAMES.search(text):
            result["revisores"].append(path)
        if INTERNAL_PATHS.search(text):
            result["rutas_internas"].append(path)
        if ABSOLUTE_PATHS.search(text):
            result["rutas_absolutas"].append(path)
        if _is_prose(path) and VERSION_IN_PROSE.search(text):
            result["version_en_prosa"].append(path)
    return result


@pytest.mark.parametrize("rule", ["nombre", "revisores", "rutas_internas", "rutas_absolutas", "version_en_prosa"])
def test_public_tree_has_no_release_hygiene_violations(rule):
    violations = collect_violations()[rule]
    assert not violations, (
        f"{len(violations)} archivos violan la regla '{rule}':\n  " + "\n  ".join(violations[:40])
    )


if __name__ == "__main__":  # medicion rapida fuera de pytest
    for rule, files in collect_violations().items():
        print(f"{rule}: {len(files)}")
        for f in files:
            print("   ", f)
