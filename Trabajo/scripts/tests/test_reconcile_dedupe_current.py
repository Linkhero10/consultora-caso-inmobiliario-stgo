from pathlib import Path

from reconcile_dedupe_current import reconcile_records


def test_reconcile_uses_current_text_and_groups_exact_duplicates():
    records = [
        {
            "url": "https://example.test/short",
            "text": "A noticia urbana completa.",
            "char_count": 0,
            "fetched_at": "2026-09-01T00:00:00+00:00",
            "lineage": {"query_hash": "q1"},
        },
        {
            "url": "https://example.test/copy",
            "text": "A noticia urbana completa.",
            "char_count": 0,
            "fetched_at": "2026-09-02T00:00:00+00:00",
            "lineage": {"query_hash": "q2"},
        },
        {
            "url": "https://example.test/empty",
            "text": "",
            "char_count": 0,
            "lineage": {"query_hash": "q3"},
        },
    ]

    result = reconcile_records(records, min_content_chars=10)

    assert result.stats["current_eligible"] == 2
    assert result.stats["duplicate_exact_groups"] == 1
    assert {row["tipo"] for row in result.manifest_rows} == {
        "canonico",
        "duplicado_exacto",
        "not_eligible_for_dedupe",
    }
    canonical = next(row for row in result.manifest_rows if row["tipo"] == "canonico")
    assert canonical["url"] == "https://example.test/short"
    assert canonical["origins"][0]["lineage"]["query_hash"] == "q1"


def test_reconcile_marks_short_fingerprint_as_candidate_only():
    records = [
        {
            "url": "https://example.test/a",
            "text": "Encabezado comun. Texto A diferente.",
            "fetched_at": "2026-09-01T00:00:00+00:00",
            "lineage": {},
        },
        {
            "url": "https://example.test/b",
            "text": "Encabezado comun. Texto B diferente.",
            "fetched_at": "2026-09-02T00:00:00+00:00",
            "lineage": {},
        },
    ]
    result = reconcile_records(records, min_content_chars=10, fingerprint_chars=17)
    assert result.stats["duplicate_exact_groups"] == 0
    assert result.stats["fingerprint_candidates"] == 1
    assert not any(row["tipo"] == "duplicado_exacto" for row in result.manifest_rows)
