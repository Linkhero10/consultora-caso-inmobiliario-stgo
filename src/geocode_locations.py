#!/usr/bin/env python3
"""Geocodificación de lugares mencionados contra el gazetteer BCN.

Adaptado de un geocoder ya validado por el usuario en otro proyecto propio
(cascada de resolución de topónimos sin fuzzy matching, usada para conflictos
hídricos del norte de Chile). Aquí se porta solo el núcleo relevante para
este dominio (conflictos inmobiliarios/urbanos en la Provincia de Santiago):
normalización, match exacto, fragmentación conservadora, y desambiguación
por comuna preferida -- sin las reglas específicas de minería del proyecto
original (sinónimos embalse/tranque, alias de región de Atacama).

Principio, igual que el original: **nunca fabricar una coordenada**. Si el
texto no calza literalmente con ningún topónimo del diccionario, o si tras
aplicar el contexto de comuna sigue habiendo más de un candidato posible,
la función devuelve `None`. No se hace fuzzy matching en ningún punto.

Regla de unicidad (revisión externa): un match exacto por sí solo no
garantiza identidad -- "El Golf" o "Santa Isabel" pueden repetirse en varias
comunas. Se exige exact match + comuna preferida (si se conoce) +
exactamente 1 candidato remanente; 0 o >1 candidatos devuelven `None`.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GAZETTEER_PATH = PROJECT_ROOT / "Fuentes" / "fuentes_externas" / "raw" / "F-19" / "geo_dictionary_bcn.csv"

# "," / " en " / " y " -- mismos separadores conservadores del geocoder
# original: el LLM suele describir el lugar como frase compuesta
# ("Edificio Cumbres de Colón, Las Condes") en vez de un topónimo único.
_FRAGMENT_SPLIT = re.compile(r",| en | y ")

# Prefijos administrativos genéricos que a veces anteceden al topónimo real
# ("Sector de Vitacura", "Zona de Ñuñoa"). Solo se prueban como candidato
# adicional después de que el texto completo y sus fragmentos ya fallaron.
_GENERIC_PREFIX = re.compile(r"^(sector|zona|barrio)\s+de\s+", re.IGNORECASE)

# El diccionario BCN registra el mismo lugar con y sin la preposición "de"
# entre sustantivo genérico y nombre propio. Se usa solo como índice
# secundario de fallback, nunca reemplaza el match literal.
_ARTICLE_CONNECTOR = re.compile(r"\b(?:de la|de los|de las|del|de)\b")

# place_type del gazetteer -> bucket de precisión espacial. El gazetteer BCN
# no tiene direcciones con numeración (nivel "address"); ese bucket queda
# reservado para un futuro geocodificador de direcciones exactas.
_PRECISION_BY_PLACE_TYPE = {
    "admin_comuna": "commune",
    "comuna": "commune",
    "admin_provincia": "commune",
    "admin_region": "commune",
    "regi\xa2n administrativa": "commune",
    "centro poblado": "neighborhood",
    "ciudad": "neighborhood",
    "pueblo": "neighborhood",
    "aldea": "neighborhood",
    "localidad rural": "neighborhood",
    "localidad o area": "neighborhood",
    "localidad": "neighborhood",
    "caserio": "neighborhood",
    "villorrio": "neighborhood",
    "villa": "neighborhood",
}


def _norm(value: str | None) -> str:
    text = str(value or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    text = text.replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def _collapse_articles(norm_text: str) -> str:
    collapsed = _ARTICLE_CONNECTOR.sub(" ", norm_text)
    return re.sub(r"\s+", " ", collapsed).strip()


def _strip_generic_prefix(text: str) -> str | None:
    match = _GENERIC_PREFIX.match(text)
    return text[match.end():].strip() if match else None


def _fragments(text: str) -> list[str]:
    parts = [p.strip() for p in _FRAGMENT_SPLIT.split(text) if p.strip()]
    return list(dict.fromkeys(parts))


def _candidate_strings(text: str) -> list[str]:
    full = text.strip()
    fragments = [f for f in _fragments(text) if _norm(f) != _norm(full)]
    ordered = [full, *fragments]
    seen = {_norm(c) for c in ordered}
    result: list[str] = []
    for candidate in ordered:
        result.append(candidate)
        derived = _strip_generic_prefix(candidate)
        if derived and _norm(derived) not in seen:
            seen.add(_norm(derived))
            result.append(derived)
    return result


@dataclass(frozen=True)
class GeocodeResult:
    raw_text: str
    normalized_text: str
    matched_name: str
    comuna: str | None
    lat: float
    lon: float
    match_method: str  # literal | fragment | de_variant | generic_prefix
    n_candidates_before_context: int
    n_candidates_after_context: int
    spatial_precision: str  # address | poi | neighborhood | commune | unknown
    source: str


_INDEX_CACHE: dict[str, list[dict[str, str]]] | None = None
_INDEX_CACHE_PATH: Path | None = None
_DE_COLLAPSED_CACHE: tuple[int, dict[str, list[dict[str, str]]]] | None = None


def load_index(path: Path = GAZETTEER_PATH) -> dict[str, list[dict[str, str]]]:
    """norm_name -> lista de filas del gazetteer con esa clave normalizada."""
    global _INDEX_CACHE, _INDEX_CACHE_PATH
    if _INDEX_CACHE is not None and _INDEX_CACHE_PATH == path:
        return _INDEX_CACHE
    index: dict[str, list[dict[str, str]]] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                key = _norm(row.get("norm_name") or row.get("name"))
                if key:
                    index.setdefault(key, []).append(row)
    _INDEX_CACHE, _INDEX_CACHE_PATH = index, path
    return index


def _de_collapsed_index(index: dict[str, list[dict[str, str]]]) -> dict[str, list[dict[str, str]]]:
    """Índice secundario (conector "de/del/..." colapsado), cacheado por
    identidad del índice de entrada para no reconstruirlo en cada llamada a
    `resolve_location` -- reconstruirlo por llamada es O(tamaño del
    diccionario) y se invoca miles de veces al procesar un corpus."""
    global _DE_COLLAPSED_CACHE
    if _DE_COLLAPSED_CACHE is not None and _DE_COLLAPSED_CACHE[0] == id(index):
        return _DE_COLLAPSED_CACHE[1]
    built: dict[str, list[dict[str, str]]] = {}
    for key, rows in index.items():
        collapsed = _collapse_articles(key)
        if collapsed:
            built.setdefault(collapsed, []).extend(rows)
    _DE_COLLAPSED_CACHE = (id(index), built)
    return built


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spatial_precision(place_type: str | None) -> str:
    return _PRECISION_BY_PLACE_TYPE.get(_norm(place_type), "poi")


def _lookup_unique(
    key: str, index: dict[str, list[dict[str, str]]], prefer_comuna: str | None
) -> tuple[dict[str, str] | None, int, int]:
    """Devuelve (fila_unica_o_None, n_candidatos_antes_de_contexto, n_candidatos_despues).

    Nunca elige entre varios candidatos por heurística de "el más probable" --
    solo exact match + filtro de comuna preferida, y exige exactamente 1
    candidato remanente. 0 o >1 -> fila None (no se fabrica una coordenada).
    """
    candidates = index.get(key, [])
    n_before = len(candidates)
    if n_before == 0:
        return None, 0, 0

    preferred = _norm(prefer_comuna)
    if preferred:
        # Contexto duro: si se conoce la comuna esperada, el candidato DEBE
        # pertenecer a ella. 0 candidatos en la comuna preferida es "no
        # resuelto", nunca un fallback silencioso al universo nacional --
        # aunque ese universo nacional tenga, por coincidencia, un único
        # candidato en otra comuna.
        filtered = [row for row in candidates if _norm(row.get("comuna")) == preferred]
    else:
        filtered = candidates

    n_after = len(filtered)
    if n_after != 1:
        return None, n_before, n_after
    return filtered[0], n_before, n_after


def resolve_location(
    raw_text: str | None,
    *,
    prefer_comuna: str | None = None,
    index: dict[str, list[dict[str, str]]] | None = None,
    skip_exact_names: set[str] | None = None,
) -> GeocodeResult | None:
    """Resuelve un texto de lugar contra el gazetteer BCN.

    Devuelve `None` si el texto está vacío, si no calza con ningún topónimo,
    o si tras aplicar el contexto de comuna sigue habiendo ambigüedad
    (0 o >1 candidatos). Nunca hace fuzzy matching.

    `skip_exact_names` (normalizados, ej. vía `_norm`) excluye candidatos que
    sean exactamente uno de esos nombres -- útil para no dejar que un
    fragmento que es literalmente el nombre de una comuna ya conocida
    (ej. "La Granja" dentro de una enumeración de comunas) calce contra un
    homónimo de barrio en otra comuna del gazetteer nacional; ese caso debe
    resolverse por la vía determinista de comuna, no por el gazetteer.
    """
    text = str(raw_text or "").strip()
    if not text:
        return None
    idx = index if index is not None else load_index()
    skip = skip_exact_names or set()

    for position, candidate in enumerate(_candidate_strings(text)):
        norm_candidate = _norm(candidate)
        if norm_candidate in skip:
            continue
        row, n_before, n_after = _lookup_unique(norm_candidate, idx, prefer_comuna)
        method = "literal" if position == 0 else "fragment"
        if row is None:
            collapsed_key = _collapse_articles(norm_candidate)
            row, n_before, n_after = _lookup_unique(collapsed_key, _de_collapsed_index(idx), prefer_comuna)
            method = f"{method}_de_variant"
        if row is None:
            continue
        lat, lon = _float_or_none(row.get("lat")), _float_or_none(row.get("lon"))
        if lat is None or lon is None:
            continue
        return GeocodeResult(
            raw_text=text,
            normalized_text=norm_candidate,
            matched_name=row.get("name") or "",
            comuna=row.get("comuna") or None,
            lat=lat,
            lon=lon,
            match_method=method,
            n_candidates_before_context=n_before,
            n_candidates_after_context=n_after,
            spatial_precision=_spatial_precision(row.get("place_type")),
            source=row.get("source") or "Toponimos_BCN",
        )
    return None
