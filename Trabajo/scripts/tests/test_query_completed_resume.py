"""Prueba reproducible del fix de reanudacion dentro de una consulta
(2026-09-12, hallazgo Codex/Luna en Auditoria/codex_fleet/OPEN_FINDINGS_20260912.md
punto 1). No hace llamadas de red ni API -- opera sobre un manifest sintetico.

Ejecutar:
  python Trabajo/scripts/tests/test_query_completed_resume.py

Codex/Luna anoto (turn-20260912-232713-166981) que la primera version de
esta prueba se corrio inline y no quedo como artefacto reproducible -- este
archivo cierra ese hallazgo.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import brightdata_discovery as bd  # noqa: E402
import snapshot_discovery as sd  # noqa: E402


def test_combo_completo_se_reconoce_e_incompleto_queda_pendiente() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "discovery_manifest.jsonl"
        lines = [
            {"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 1, "resolved_url": "urlA1", "record_hash": "hA1"},
            {"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 2, "resolved_url": "urlA2", "record_hash": "hA2"},
            {"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 3, "resolved_url": "urlA3", "record_hash": "hA3"},
            {"event": "query_completed", "comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "organic_count": 3},
            # Combo B: proceso "muerto" a mitad -- 2 filas escritas, sin
            # query_completed. Simula un kill externo del proceso (no una
            # excepcion de codigo: resolve_goto_link() ya tiene su propio
            # try/except y nunca deja el loop a medias por si sola).
            {"comuna": "B", "termino": "t2", "periodo": "p1", "nivel": "comuna", "query": "qB", "rank": 1, "resolved_url": "urlB1", "record_hash": "hB1"},
            {"comuna": "B", "termino": "t2", "periodo": "p1", "nivel": "comuna", "query": "qB", "rank": 2, "resolved_url": "urlB2", "record_hash": "hB2"},
        ]
        manifest.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8")

        done = bd.already_queried_combos(manifest)
        assert ("A", "t1", "p1", "comuna") in done, "combo A (con query_completed) deberia estar hecho"
        assert ("B", "t2", "p1", "comuna") not in done, "combo B (sin query_completed) NO deberia estar hecho"
    print("OK: test_combo_completo_se_reconoce_e_incompleto_queda_pendiente")


def test_legacy_any_row_combos_es_solo_para_transicion() -> None:
    """Hallazgo Codex/Luna (turn-20260912-232630-82c57a): el manifest de la
    corrida activa (iniciada antes del fix) tenia 0 eventos query_completed.
    already_queried_combos() por defecto exige ese evento -- si se usara
    para reanudar esa corrida especifica, veria 0 combos completos y
    re-consultaria las 2336 queries del plan desde cero. legacy_any_row_combos()
    existe solo para esa transicion puntual (--trust-legacy-rows-once)."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "discovery_manifest.jsonl"
        lines = [
            {"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 1, "resolved_url": "urlA1", "record_hash": "hA1"},
        ]
        manifest.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8")

        strict = bd.already_queried_combos(manifest)
        legacy = bd.legacy_any_row_combos(manifest)
        assert strict == set(), "sin query_completed, el modo estricto (default) no debe marcar nada como hecho"
        assert ("A", "t1", "p1", "comuna") in legacy, "el modo legacy (solo con --trust-legacy-rows-once) si debe reconocerlo"
    print("OK: test_legacy_any_row_combos_es_solo_para_transicion")


def test_trust_legacy_rows_once_se_rechaza_tras_la_transicion() -> None:
    """Hallazgo Codex/Luna (turn-20260913-000857-3d5bac): "once" en el
    nombre del flag no bastaba, hacia falta un guard mecanico. Un manifest
    puramente legacy (sin ningun query_completed) debe permitir el flag;
    un manifest que ya tiene al menos un query_completed (la transicion ya
    ocurrio) debe rechazarlo."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest_legacy = Path(tmp) / "legacy.jsonl"
        manifest_legacy.write_text(
            json.dumps({"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 1, "resolved_url": "urlA1", "record_hash": "hA1"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        allowed, _ = bd.legacy_flag_is_safe(manifest_legacy)
        assert allowed, "un manifest sin ningun query_completed debe permitir la transicion"

        manifest_transicionado = Path(tmp) / "transicionado.jsonl"
        manifest_transicionado.write_text(
            "\n".join(json.dumps(l, ensure_ascii=False) for l in [
                {"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 1, "resolved_url": "urlA1", "record_hash": "hA1"},
                {"event": "query_completed", "comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "organic_count": 1},
                {"comuna": "B", "termino": "t2", "periodo": "p1", "nivel": "comuna", "query": "qB", "rank": 1, "resolved_url": "urlB1", "record_hash": "hB1"},
            ]) + "\n",
            encoding="utf-8",
        )
        allowed, reason = bd.legacy_flag_is_safe(manifest_transicionado)
        assert not allowed, "un manifest con al menos un query_completed ya paso la transicion -- debe rechazarse"
        assert reason
    print("OK: test_trust_legacy_rows_once_se_rechaza_tras_la_transicion")


def test_snapshot_discovery_excluye_eventos_de_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        manifest = tmp_path / "discovery_manifest.jsonl"
        snapshots_dir = tmp_path / "snapshots"
        lines = [
            {"comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "query": "qA", "rank": 1, "resolved_url": "urlA1", "record_hash": "hA1"},
            {"event": "query_completed", "comuna": "A", "termino": "t1", "periodo": "p1", "nivel": "comuna", "organic_count": 1},
            {"comuna": "LEGACY", "termino": "", "periodo": "", "nivel": "", "query": "", "rank": 1, "resolved_url": "urlLegacy", "record_hash": ""},
        ]
        manifest.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8")

        original_manifest, original_snapshots_dir = sd.ACTIVE_MANIFEST, sd.SNAPSHOTS_DIR
        sd.ACTIVE_MANIFEST = manifest
        sd.SNAPSHOTS_DIR = snapshots_dir
        try:
            rc = sd._run()
            assert rc == 0
            meta_path = sorted(snapshots_dir.glob("*.meta.json"))[-1]
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta["contract_version_counts"] == {"discovery_v2": 1, "legacy_v1": 1}
            assert meta["lines_control_events_excluded"] == 1
        finally:
            sd.ACTIVE_MANIFEST, sd.SNAPSHOTS_DIR = original_manifest, original_snapshots_dir
    print("OK: test_snapshot_discovery_excluye_eventos_de_control")


def test_query_hash_cambia_si_cambia_la_query_completa() -> None:
    item = {
        "comuna": "A",
        "termino": "t1",
        "periodo": "p1",
        "nivel": "comuna",
        "query": '"t1" "A" -site:example.org',
        "cd_min": "1/1/2024",
        "cd_max": "12/31/2026",
    }
    original = bd.query_hash_for_item(item)
    changed = dict(item, query='"t1" "A" -site:other.org')
    assert original != bd.query_hash_for_item(changed), "query_hash debe detectar cambios en la query completa"
    print("OK: test_query_hash_cambia_si_cambia_la_query_completa")


def test_scope_backfill_deriva_temporal_legacy_y_mixto() -> None:
    import backfill_corpus_scope as bcs  # noqa: PLC0415

    temporal = {"periodo": "2024_2026", "nivel": "comuna"}
    legacy = {"periodo": "", "nivel": ""}
    mixed = {"periodo": "2024_2026", "nivel": "comuna", "origins": [legacy, temporal]}
    assert bcs.scope_for_record({"lineage": temporal}) == "temporal_v2"
    assert bcs.scope_for_record({"lineage": legacy}) == "legacy_sin_ventana"
    assert bcs.scope_for_record({"lineage": mixed}) == "temporal_v2_mixed_legacy"
    print("OK: test_scope_backfill_deriva_temporal_legacy_y_mixto")


if __name__ == "__main__":
    test_combo_completo_se_reconoce_e_incompleto_queda_pendiente()
    test_legacy_any_row_combos_es_solo_para_transicion()
    test_trust_legacy_rows_once_se_rechaza_tras_la_transicion()
    test_snapshot_discovery_excluye_eventos_de_control()
    test_query_hash_cambia_si_cambia_la_query_completa()
    test_scope_backfill_deriva_temporal_legacy_y_mixto()
    print("Todos los tests pasaron.")
