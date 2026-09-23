import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import project_case_mention as pcm


def test_exact_object_quote_creates_verified_direct_link():
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "El proyecto Torre Alameda fue impugnado", "verified": 1}],
        project_aliases={"p1": ["Torre Alameda"]},
    )
    assert len(rows) == 1
    assert rows[0]["link_status"] == "verified_direct"
    assert rows[0]["case_mention_id"] == "cm1"
    assert rows[0]["evidence_id"] == "ev1"


def test_same_document_with_two_matching_mentions_is_ambiguous_not_verified():
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[
            {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"},
            {"case_mention_id": "cm2", "document_id": "d1", "decision_final_amplio": "include"},
        ],
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d1", "case_mention_id": "cm2", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1},
        ],
        project_aliases={"p1": ["Torre Alameda"]},
    )
    assert {row["link_status"] for row in rows} == {"ambiguous_direct"}
    assert all(row["case_mention_id"] in {"cm1", "cm2"} for row in rows)


def test_excluded_case_mention_never_becomes_verified_link():
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "exclude"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1}],
        project_aliases={"p1": ["Torre Alameda"]},
    )
    assert rows
    assert all(row["link_status"] != "verified_direct" for row in rows)
    assert rows[0]["link_status"] == "excluded_case_mention"


def test_nonmatching_object_quote_is_document_level_candidate_only():
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "un complejo habitacional", "verified": 1}],
        project_aliases={"p1": ["Torre Alameda"]},
    )
    assert len(rows) == 1
    assert rows[0]["link_status"] == "document_level_candidate"
    assert rows[0]["evidence_id"] is None


def test_string_zero_verified_flag_is_not_treated_as_verified():
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": "0"}],
        project_aliases={"p1": ["Torre Alameda"]},
    )
    assert rows[0]["link_status"] == "document_level_candidate"


def test_uncertain_case_mention_is_not_labeled_as_excluded():
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Edificio CChC"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "uncertain"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Edificio CChC", "verified": 1}],
    )
    assert rows[0]["link_status"] == "non_included_case_mention"
    assert rows[0]["decision_final_amplio"] == "uncertain"


def test_insufficient_content_case_mention_is_non_included_not_excluded():
    """Item 3 del diseno: un estado distinto de exclude (insufficient_content,
    como uncertain) nunca debe confundirse con una exclusion explicita."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "insufficient_content"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1}],
    )
    assert rows[0]["link_status"] == "non_included_case_mention"


def test_non_objeto_quote_role_never_creates_direct_link():
    """Item 5 del diseno: una cita de rol accion/geografica, aunque verificada
    y aunque contenga el nombre del proyecto, no cuenta como respaldo de
    objeto -- solo quote_role='objeto' puede generar verified_direct."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "accion", "quote_text": "Torre Alameda fue impugnada", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "geografica", "quote_text": "Torre Alameda, Providencia", "verified": 1},
        ],
    )
    assert rows[0]["link_status"] == "document_level_candidate"


def test_evidence_from_a_different_document_is_never_linked():
    """Item 6 del diseno (gap real encontrado en la revision externa, 2026-09-23):
    una evidencia cuyo document_id no coincide con el de la case_mention que
    referencia no debe poder respaldar ningun enlace, aunque el texto calce.
    Antes de este fix el codigo agrupaba evidence_by_cm solo por
    case_mention_id, sin comprobar document_id -- sobre el warehouse real no
    habia filas discrepantes (0/0 verificado), pero el guard protege contra
    datos corruptos o fixtures adversariales."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[
            # document_id="d2" no coincide con el document_id="d1" de cm1 -- debe descartarse.
            {"evidence_id": "ev1", "document_id": "d2", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1},
        ],
    )
    assert rows[0]["link_status"] == "document_level_candidate"
    assert rows[0]["evidence_id"] is None


def test_known_limitation_v1_generic_short_fragment_can_match():
    """Item 7 del diseno (gap real, NO corregido en v1 -- requiere una v2
    versionada del criterio de coincidencia, ver docstring del modulo).
    `_matches_project` acepta contencion bidireccional (`term in quote or
    quote in term`), asi que un nombre de proyecto muy corto/generico puede
    calzar con cualquier cita que lo contenga como substring, sin exigir
    distintividad. Este test documenta el comportamiento ACTUAL de v1 --no lo
    aprueba-- para que quede protegido por regresion mientras no exista v2."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Villa"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[{"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Villa Los Presidentes, un conjunto de 400 viviendas", "verified": 1}],
    )
    assert rows[0]["link_status"] == "verified_direct"  # limitacion conocida de v1, no un resultado deseable


def test_known_limitation_v1_hides_parallel_excluded_collision():
    """Item 8 del diseno (gap real, NO corregido en v1). Cuando existe
    exactamente una case_mention incluida que calza (-> verified_direct), la
    funcion corta el analisis (`continue`) sin registrar que TAMBIEN existia
    una coincidencia paralela en una case_mention excluida del mismo
    documento. Este test documenta que la fila excluida NUNCA aparece en la
    salida en ese escenario -- limitacion conocida, no deseable, pendiente de
    una v2 que preserve ambas senales."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[
            {"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"},
            {"case_mention_id": "cm2", "document_id": "d1", "decision_final_amplio": "exclude"},
        ],
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d1", "case_mention_id": "cm2", "quote_role": "objeto", "quote_text": "Torre Alameda", "verified": 1},
        ],
    )
    assert len(rows) == 1  # la coincidencia excluida (cm2) queda oculta
    assert rows[0]["link_status"] == "verified_direct"
    assert rows[0]["case_mention_id"] == "cm1"


def test_multiple_object_quotes_same_case_mention_do_not_duplicate_project_count():
    """Item 9 del diseno: varias citas de objeto verificadas dentro de la
    MISMA case_mention incluida producen varias filas de evidencia, pero
    todas apuntan al mismo (project_id, case_mention_id) -- un consumidor que
    cuente project_id distintos (no filas) nunca debe inflar el conteo."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[{"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre Alameda"}],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "el proyecto Torre Alameda", "verified": 1},
            {"evidence_id": "ev2", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "Torre Alameda contempla 200 deptos", "verified": 1},
        ],
    )
    assert len(rows) == 2
    assert {r["link_status"] for r in rows} == {"verified_direct"}
    assert {r["case_mention_id"] for r in rows} == {"cm1"}
    assert len({r["project_id"] for r in rows}) == 1


def test_link_output_never_claims_focal_role():
    """Item 10 del diseno: una cita de objeto puede nombrar varios proyectos
    a la vez (ej. una comparacion), pero el enlace del linker no debe incluir
    ningun campo de 'rol focal/co-focal' -- esa determinacion pertenece a
    document_conflict/build_conflicts.py, nunca se infiere aqui a partir de
    que el nombre calce con una cita."""
    rows = pcm.build_project_case_mention_links(
        project_mentions=[
            {"document_id": "d1", "project_id": "p1", "raw_nombre_proyecto": "Torre A"},
            {"document_id": "d1", "project_id": "p2", "raw_nombre_proyecto": "Torre B"},
        ],
        case_mentions=[{"case_mention_id": "cm1", "document_id": "d1", "decision_final_amplio": "include"}],
        evidence=[
            {"evidence_id": "ev1", "document_id": "d1", "case_mention_id": "cm1", "quote_role": "objeto", "quote_text": "los proyectos Torre A y Torre B fueron impugnados", "verified": 1},
        ],
    )
    assert len(rows) == 2
    for row in rows:
        assert "role" not in row
        assert "focal" not in row
        assert row["link_status"] == "verified_direct"
