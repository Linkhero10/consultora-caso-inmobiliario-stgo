import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import project_case_mention as pcm
import project_geography as geo


def _cm_lookup(case_mentions: list[dict]) -> dict[str, dict]:
    return {cm["case_mention_id"]: cm for cm in case_mentions}


def test_comuna_of_another_mention_is_never_propagated_to_the_project():
    """Item 2 del diseno: la misma cita bajo otra case_mention (con comuna
    distinta) no debe propagar esa comuna al proyecto -- solo cuenta la
    comuna de la case_mention que realmente respalda el nombre."""
    case_mentions = [
        {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Vitacura", "codigo_comuna_ine": "13132"},
        {"case_mention_id": "cm2", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Lo Barnechea", "codigo_comuna_ine": "13115"},
    ]
    links = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Terrazas del Valle"}],
        case_mentions=case_mentions,
        # Solo cm1 (Vitacura) respalda el nombre; cm2 (Lo Barnechea) es otra mencion sin relacion textual.
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Terrazas del Valle", "verified": 1}],
    )
    attributions = geo.attribute_projects_to_comunas(links, _cm_lookup(case_mentions))
    assert len(attributions) == 1
    assert attributions[0]["geography_status"] == "direct_attribution"
    assert attributions[0]["codigo_comuna_ine"] == "13132"  # Vitacura, no Lo Barnechea


def test_ambiguous_direct_never_becomes_direct_attribution_same_or_different_comuna():
    """Item 11 del diseno: varias case_mention incluidas que calzan con el
    mismo nombre quedan ambiguas para el enlace, sin importar si comparten
    comuna o tienen comunas distintas -- ninguna de las dos variantes debe
    promoverse a direct_attribution."""
    # Variante A: mismo codigo de comuna en ambas case_mention.
    case_mentions_same = [
        {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Nunoa", "codigo_comuna_ine": "13120"},
        {"case_mention_id": "cm2", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Nunoa", "codigo_comuna_ine": "13120"},
    ]
    links_same = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Eco Egana"}],
        case_mentions=case_mentions_same,
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d1", "case_mention_id": "cm2", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
        ],
    )
    attr_same = geo.attribute_projects_to_comunas(links_same, _cm_lookup(case_mentions_same))
    assert all(a["geography_status"] == "ambiguous_candidate" for a in attr_same)
    assert all(a["codigo_comuna_ine"] is None for a in attr_same)

    # Variante B: comunas distintas en cada case_mention.
    case_mentions_diff = [
        {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Nunoa", "codigo_comuna_ine": "13120"},
        {"case_mention_id": "cm2", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Providencia", "codigo_comuna_ine": "13123"},
    ]
    links_diff = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Eco Egana"}],
        case_mentions=case_mentions_diff,
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d1", "case_mention_id": "cm2", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
        ],
    )
    attr_diff = geo.attribute_projects_to_comunas(links_diff, _cm_lookup(case_mentions_diff))
    assert all(a["geography_status"] == "ambiguous_candidate" for a in attr_diff)
    assert all(a["codigo_comuna_ine"] is None for a in attr_diff)


def test_empty_or_out_of_territory_code_keeps_link_but_assigns_no_comuna():
    """Item 12 del diseno: codigo vacio, o valido mas fuera del universo de
    `territory`, conserva el enlace textual (verified_direct) pero no infiere
    ninguna comuna."""
    case_mentions = [
        {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include", "comuna": "", "codigo_comuna_ine": ""},
        {"case_mention_id": "cm2", "document_id": "d2", "decision_final_amplio": "include", "comuna": "Fuera de RM", "codigo_comuna_ine": "99999"},
    ]
    links = pcm.build_project_case_mention_links(
        project_mentions=[
            {"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"},
            {"document_id": "d2", "project_id": "p2", "raw_nombre_proyecto": "Torre Beta"},
        ],
        case_mentions=case_mentions,
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d2", "case_mention_id": "cm2", "quote_role": "objeto", "quote_text": "Torre Beta", "verified": 1},
        ],
    )
    valid_codes = {"13101", "13132"}  # 99999 no pertenece al universo territorial
    attributions = geo.attribute_projects_to_comunas(links, _cm_lookup(case_mentions), valid_codes)
    by_project = {a["project_id"]: a for a in attributions}
    assert by_project["p1"]["link_status"] == "verified_direct"
    assert by_project["p1"]["geography_status"] == "direct_link_no_comuna"
    assert by_project["p1"]["codigo_comuna_ine"] is None
    assert by_project["p2"]["link_status"] == "verified_direct"
    assert by_project["p2"]["geography_status"] == "direct_link_no_comuna"
    assert by_project["p2"]["codigo_comuna_ine"] is None


def test_project_backed_in_several_documents_counts_once_per_comuna():
    """Item 13 del diseno: un proyecto respaldado en varias noticias de la
    MISMA comuna cuenta una sola vez ahi; solo aparece en mas de una comuna
    si tiene un enlace elegible independiente en cada una."""
    case_mentions = [
        {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include", "comuna": "Nunoa", "codigo_comuna_ine": "13120"},
        {"case_mention_id": "cm2", "document_id": "d2", "decision_final_amplio": "include", "comuna": "Nunoa", "codigo_comuna_ine": "13120"},
        {"case_mention_id": "cm3", "document_id": "d3", "decision_final_amplio": "include", "comuna": "Providencia", "codigo_comuna_ine": "13123"},
    ]
    links = pcm.build_project_case_mention_links(
        project_mentions=[
            {"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Eco Egana"},
            {"document_id": "d2", "project_id": "p1", "raw_nombre_proyecto": "Eco Egana"},
            {"document_id": "d3", "project_id": "p1", "raw_nombre_proyecto": "Eco Egana"},
        ],
        case_mentions=case_mentions,
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d2", "case_mention_id": "cm2", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
            {"evidence_id": "ev3", "document_id": "d3", "case_mention_id": "cm3", "quote_role": "objeto", "quote_text": "Eco Egana", "verified": 1},
        ],
    )
    attributions = geo.attribute_projects_to_comunas(links, _cm_lookup(case_mentions))
    per_comuna = geo.count_projects_per_comuna(attributions)
    assert per_comuna["13120"] == {"p1"}       # 2 noticias en Nunoa -> cuenta 1 vez
    assert per_comuna["13123"] == {"p1"}       # comuna distinta, enlace independiente -> cuenta tambien ahi
    assert len(per_comuna) == 2


def test_resolve_case_mention_comuna_never_falls_back():
    assert geo.resolve_case_mention_comuna(None) is None
    assert geo.resolve_case_mention_comuna({"codigo_comuna_ine": "", "comuna": ""}) is None
    assert geo.resolve_case_mention_comuna({"codigo_comuna_ine": "13101", "comuna": "Santiago"}) == {
        "codigo_comuna_ine": "13101", "comuna": "Santiago",
    }
    assert geo.resolve_case_mention_comuna({"codigo_comuna_ine": "99999", "comuna": "X"}, valid_codes={"13101"}) is None
