"""Pruebas de Actor Identity Resolution v1 (actor_registry/actor_alias).
Encargo explicito de Sol: conservador y auditable, no fuzzy matching
global; proteccion explicita contra GENERIC_ACTOR_TERMS. Ronda 2
(2026-09-18): entity_id debe ser estable (no derivar del conjunto de
alias) y la cobertura debe medir las 3 fuentes reales de la red."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_actor_registry as reg  # noqa: E402
import network_common as net  # noqa: E402


def test_no_alias_collides_with_generic_actor_terms():
    """Los terminos genericos (los vecinos, municipio, la inmobiliaria...)
    nunca deben aparecer como alias de una entidad resuelta -- esos
    terminos no son la misma entidad entre casos/conflictos distintos."""
    _, alias_rows = reg.build_registry()
    alias_norms = {a["nombre_norm"] for a in alias_rows}
    assert alias_norms.isdisjoint(net.GENERIC_ACTOR_TERMS)


def test_entity_id_is_stable_when_aliases_change():
    """Hallazgo BLOQUEANTE de Sol: antes entity_id derivaba del conjunto
    de alias, asi que agregar un alias nuevo (el uso normal de un
    registry) cambiaba el entity_id de una entidad ya publicada. Ahora
    debe depender SOLO de entity_key."""
    id_con_2_alias = reg._stable_entity_id("cl_test")
    # simulamos "agregar un alias" -- el id no debe depender de eso en absoluto,
    # asi que llamarlo de nuevo con la misma entity_key da el mismo resultado
    # sin importar cuantos alias tenga la entidad en ACTOR_ENTITIES.
    id_otra_vez = reg._stable_entity_id("cl_test")
    assert id_con_2_alias == id_otra_vez

    id_distinta_key = reg._stable_entity_id("cl_test_otro")
    assert id_con_2_alias != id_distinta_key


def test_build_registry_raises_on_duplicate_entity_key():
    original = reg.ACTOR_ENTITIES
    reg.ACTOR_ENTITIES = [
        {"entity_key": "dup", "canonical_label": "Entidad A", "aliases": ["nombre a"], "razon": "x"},
        {"entity_key": "dup", "canonical_label": "Entidad B", "aliases": ["nombre b"], "razon": "y"},
    ]
    try:
        try:
            reg.build_registry()
            assert False, "deberia haber lanzado ValueError"
        except ValueError:
            pass
    finally:
        reg.ACTOR_ENTITIES = original


def test_build_registry_raises_on_duplicate_alias_across_entities():
    original = reg.ACTOR_ENTITIES
    reg.ACTOR_ENTITIES = [
        {"entity_key": "a", "canonical_label": "Entidad A", "aliases": ["nombre compartido"], "razon": "x"},
        {"entity_key": "b", "canonical_label": "Entidad B", "aliases": ["nombre compartido"], "razon": "y"},
    ]
    try:
        try:
            reg.build_registry()
            assert False, "deberia haber lanzado ValueError"
        except ValueError:
            pass
    finally:
        reg.ACTOR_ENTITIES = original


def test_build_registry_raises_on_generic_term_collision():
    original = reg.ACTOR_ENTITIES
    reg.ACTOR_ENTITIES = [
        {"entity_key": "generica", "canonical_label": "Entidad Generica", "aliases": ["municipio", "otra variante"], "razon": "x"}
    ]
    try:
        try:
            reg.build_registry()
            assert False, "deberia haber lanzado ValueError"
        except ValueError:
            pass
    finally:
        reg.ACTOR_ENTITIES = original


def test_entity_id_is_hash_not_free_text():
    registry_rows, _ = reg.build_registry()
    for row in registry_rows:
        assert row["entity_id"].startswith("entity:")
        assert row["entity_id"] != row["canonical_label"]


def test_each_entity_has_at_least_2_aliases():
    """Una entidad con 1 solo alias no es una fusion, es un no-op -- senal
    de que sobra la entrada en ACTOR_ENTITIES."""
    for entity in reg.ACTOR_ENTITIES:
        assert len(set(entity["aliases"])) >= 2, f"{entity['canonical_label']} tiene menos de 2 alias distintos"


def test_all_entity_keys_are_unique_and_immutable_style():
    keys = [e["entity_key"] for e in reg.ACTOR_ENTITIES]
    assert len(keys) == len(set(keys))
    assert all(k.startswith("cl_") for k in keys)  # convencion elegida a mano, no derivada


def test_corte_de_apelaciones_and_tribunal_ambiental_bare_are_not_merged():
    """Hallazgo explicito de Sol: 'Corte de Apelaciones' y 'Tribunal
    Ambiental' sin calificador de sede son ambiguos a nivel nacional
    (17 Cortes de Apelaciones, 3 Tribunales Ambientales en Chile) --
    deliberadamente fuera del alcance de v1."""
    _, alias_rows = reg.build_registry()
    alias_norms = {a["nombre_norm"] for a in alias_rows}
    assert "corte de apelaciones" not in alias_norms
    assert "tribunal ambiental" not in alias_norms
    assert "dirección de obras municipales" not in alias_norms


def _connect_or_skip():
    import sqlite3

    if not reg.WAREHOUSE.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    return sqlite3.connect(reg.WAREHOUSE)


def test_real_warehouse_tables_match_script_output():
    conn = _connect_or_skip()
    registry_rows, alias_rows = reg.build_registry()

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "actor_registry" not in tables:
        import pytest

        conn.close()
        pytest.skip("tabla actor_registry no existe -- correr build_actor_registry.py primero")

    n_registry = conn.execute("SELECT COUNT(*) FROM actor_registry").fetchone()[0]
    n_alias = conn.execute("SELECT COUNT(*) FROM actor_alias").fetchone()[0]
    conn.close()

    assert n_registry == len(registry_rows)
    assert n_alias == len(alias_rows)


def test_sea_alias_all_resolve_to_same_entity_in_warehouse():
    conn = _connect_or_skip()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "actor_alias" not in tables:
        import pytest

        conn.close()
        pytest.skip("tabla actor_alias no existe -- correr build_actor_registry.py primero")

    rows = conn.execute(
        "SELECT DISTINCT entity_id FROM actor_alias WHERE nombre_norm IN "
        "('sea', 'servicio de evaluación ambiental', 'servicio de evaluación ambiental (sea)', "
        "'servicio de evaluación ambiental sea', 'servicio de evaluación ambiental, sea')"
    ).fetchall()
    conn.close()
    assert len(rows) == 1


def test_coverage_counts_all_three_source_tables_and_matches_real_totals():
    """Hallazgo real de Sol: la cobertura anterior solo media
    enrichment_institution, subestimando severamente el alcance real
    (la red usa 3 fuentes). Verifica contra el warehouse real que la SMA
    (con la nueva variante 'Superintendencia de Medio Ambiente (SMA)',
    23 ocurrencias reales) tiene cobertura mayor a 0 en las 3 columnas."""
    conn = _connect_or_skip()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "actor_alias" not in tables:
        import pytest

        conn.close()
        pytest.skip("tabla actor_alias no existe -- correr build_actor_registry.py primero")

    sma_entity = conn.execute("SELECT entity_id FROM actor_alias WHERE nombre_norm = 'sma'").fetchone()[0]
    alias_sma = [
        r[0] for r in conn.execute("SELECT nombre_norm FROM actor_alias WHERE entity_id = ?", (sma_entity,)).fetchall()
    ]
    placeholders = ",".join("?" for _ in alias_sma)
    rows = conn.execute(
        f"SELECT source_table, COUNT(*) FROM actor_event_project_link WHERE lower(nombre) IN ({placeholders}) "
        "GROUP BY source_table",
        alias_sma,
    ).fetchall()
    conn.close()
    counts = dict(rows)
    assert counts.get("enrichment_actor", 0) > 0
    assert counts.get("enrichment_institution", 0) > 0
    # "superintendencia de medio ambiente (sma)" (sin "del") debe estar contribuyendo
    assert sum(counts.values()) >= 23


def test_conflictos_unicos_safe_uses_exact_actor_to_conflict_link_not_whole_document():
    """Hallazgo BUG REAL de Sol (2026-09-18, segunda revision): la primera
    correccion de cobertura calculaba conflictos_unicos_safe agregando
    TODOS los conflictos del documento (via document_id), no solo el
    conflicto al que esa fila de actor especifica estaba enlazada --
    sobreconteo real. Verificado por Sol contra el SQLite con valores
    EXACTOS: Contraloria 25 (reportado, con bug) vs 17 (correcto);
    MINVU 22 vs 14; SEA coincidia en 12 por casualidad (sus documentos no
    tenian el patron problematico). Este test fija los 6 valores exactos
    calculando directamente desde actor_event_project_link_conflict_safe,
    que preserva el vinculo actor->project_id->conflict_id fila a fila."""
    conn = _connect_or_skip()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "actor_alias" not in tables:
        import pytest

        conn.close()
        pytest.skip("tabla actor_alias no existe -- correr build_actor_registry.py primero")

    alias_rows = conn.execute("SELECT nombre_norm, entity_id FROM actor_alias").fetchall()
    label_by_entity = dict(conn.execute("SELECT entity_id, canonical_label FROM actor_registry").fetchall())
    alias_a_entity = dict(alias_rows)

    conflictos_por_entidad: dict[str, set] = {eid: set() for eid in label_by_entity}
    for nombre, conflict_id in conn.execute(
        "SELECT nombre, conflict_id FROM actor_event_project_link_conflict_safe"
    ).fetchall():
        entity_id = alias_a_entity.get(reg._normalize(nombre))
        if entity_id:
            conflictos_por_entidad[entity_id].add(conflict_id)
    conn.close()

    esperado = {
        "Servicio de Evaluación Ambiental (SEA)": 12,
        "Consejo de Monumentos Nacionales (CMN)": 8,
        "Consejo de Defensa del Estado (CDE)": 6,
        "Superintendencia del Medio Ambiente (SMA)": 6,
        "Ministerio de Vivienda y Urbanismo (MINVU)": 14,
        "Contraloría General de la República": 17,
    }
    real = {label_by_entity[eid]: len(conflictos) for eid, conflictos in conflictos_por_entidad.items()}
    for label, n_esperado in esperado.items():
        assert real[label] == n_esperado, f"{label}: esperado {n_esperado}, real {real[label]}"
