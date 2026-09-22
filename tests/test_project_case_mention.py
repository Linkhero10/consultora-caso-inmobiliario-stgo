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
