import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import geocode_locations as target  # noqa: E402


def _row(name, comuna, place_type="Centro Poblado", lat="0.0", lon="0.0", source="Toponimos_BCN"):
    return {
        "name": name,
        "norm_name": target._norm(name),
        "place_type": place_type,
        "comuna": comuna,
        "lat": lat,
        "lon": lon,
        "source": source,
    }


def _build_index(rows):
    index = {}
    for row in rows:
        index.setdefault(row["norm_name"], []).append(row)
    return index


def test_exact_unique_match_resolves():
    index = _build_index([_row("Lo Curro", "VITACURA", lat="-33.36", lon="-70.58")])
    result = target.resolve_location("Lo Curro", index=index)
    assert result is not None
    assert result.matched_name == "Lo Curro"
    assert result.comuna == "VITACURA"
    assert result.match_method == "literal"
    assert result.n_candidates_before_context == 1
    assert result.n_candidates_after_context == 1


def test_fragment_match_resolves_when_full_text_does_not():
    index = _build_index([_row("Lo Curro", "VITACURA", lat="-33.36", lon="-70.58")])
    result = target.resolve_location("proyecto Portezuelo en Lo Curro", index=index)
    assert result is not None
    assert result.matched_name == "Lo Curro"
    assert result.match_method == "fragment"


def test_zero_candidates_returns_none():
    index = _build_index([_row("Lo Curro", "VITACURA")])
    assert target.resolve_location("un lugar que no existe en el diccionario", index=index) is None


def test_ambiguous_name_across_comunas_without_context_returns_none():
    """Dos lugares reales con el mismo nombre en comunas distintas: sin
    contexto de comuna, no se puede elegir uno -- debe devolver None, nunca
    adivinar."""
    index = _build_index(
        [
            _row("El Golf", "LAS CONDES", lat="-33.41", lon="-70.57"),
            _row("El Golf", "PROVIDENCIA", lat="-33.42", lon="-70.60"),
        ]
    )
    assert target.resolve_location("El Golf", index=index) is None


def test_ambiguous_name_resolves_when_comuna_context_narrows_to_one():
    index = _build_index(
        [
            _row("El Golf", "LAS CONDES", lat="-33.41", lon="-70.57"),
            _row("El Golf", "PROVIDENCIA", lat="-33.42", lon="-70.60"),
        ]
    )
    result = target.resolve_location("El Golf", prefer_comuna="Las Condes", index=index)
    assert result is not None
    assert result.comuna == "LAS CONDES"
    assert result.n_candidates_before_context == 2
    assert result.n_candidates_after_context == 1


def test_context_narrows_to_more_than_one_still_returns_none():
    """Caso real encontrado en la revisión manual: el mismo nombre puede
    repetirse más de una vez incluso DENTRO de la comuna preferida (distintos
    place_type para el mismo nombre+comuna) -- eso sigue siendo ambiguo, no
    se elige ninguno."""
    index = _build_index(
        [
            _row("Las Condes", "LAS CONDES", place_type="Centro Poblado", lat="-33.41", lon="-70.58"),
            _row("Las Condes", "LAS CONDES", place_type="Comuna", lat="-33.40", lon="-70.51"),
            _row("Las Condes", "LO BARNECHEA", place_type="Centro Poblado", lat="-33.36", lon="-70.51"),
        ]
    )
    assert target.resolve_location("Las Condes", prefer_comuna="Las Condes", index=index) is None


def test_never_fuzzy_close_but_not_exact_name_does_not_match():
    index = _build_index([_row("Lo Curro", "VITACURA")])
    assert target.resolve_location("Lo Curr", index=index) is None
    assert target.resolve_location("Lo Kurro", index=index) is None


def test_skip_exact_names_excludes_known_administrative_names_from_matching():
    """Caso real encontrado en la revisión manual: un fragmento que es
    literalmente el nombre de una comuna conocida ("La Granja" dentro de una
    enumeración de comunas) no debe calzar contra un homónimo de barrio en
    OTRA comuna del gazetteer nacional -- eso se resuelve por la vía
    determinista de comuna, no por este geocoder."""
    index = _build_index([_row("La Granja", "LA CISTERNA", place_type="Localidad Rural")])
    text = "San Ramón, San Miguel, La Granja, La Florida y La Cisterna"
    assert target.resolve_location(text, index=index) is not None  # sin el filtro, calzaria
    assert target.resolve_location(text, index=index, skip_exact_names={"la granja"}) is None


def test_missing_coordinates_row_is_not_matched():
    index = _build_index([_row("Lo Curro", "VITACURA", lat="", lon="")])
    assert target.resolve_location("Lo Curro", index=index) is None


def test_de_variant_fallback_matches_with_and_without_preposition():
    index = _build_index([_row("Estero de El Arrayán", "LAS CONDES", place_type="Red Hidrografica", lat="-33.36", lon="-70.48")])
    result = target.resolve_location("Estero El Arrayán", index=index)
    assert result is not None
    assert result.match_method == "literal_de_variant"


def test_spatial_precision_bucket_from_place_type():
    index = _build_index([_row("Cerro Alvarado", "VITACURA", place_type="Elementos del Relieve", lat="-33.36", lon="-70.54")])
    result = target.resolve_location("cerro Alvarado", index=index)
    assert result is not None
    assert result.spatial_precision == "poi"

    index2 = _build_index([_row("Lo Hermida", "PENALOLEN", place_type="Localidad Rural", lat="-33.48", lon="-70.54")])
    result2 = target.resolve_location("Lo Hermida", index=index2)
    assert result2 is not None
    assert result2.spatial_precision == "neighborhood"
