"""Pruebas de la comparacion de red de actores conservadora vs inclusiva
(v2, reescrita tras revision adversarial de Sol, 2026-09-18).

No llaman a ninguna API; verifican con datos sinteticos la logica de
construccion de las 3 redes (bipartita actor-caso, coocurrencia
documental, copertenencia a caso) y los 2 hallazgos reales que motivaron
la reescritura: el bug union/interseccion de la v1, y la fusion global de
actores genericos entre casos sin relacion.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "Trabajo" / "scripts"))

import build_actor_network_comparison_v1 as net  # noqa: E402


def test_normalize_actor_name_collapses_case_and_whitespace():
    assert net.normalize_actor_name("  Corte  Suprema ") == net.normalize_actor_name("corte suprema")


def test_scope_actor_id_anchors_generic_terms_to_case_but_not_named_actors():
    assert net.scope_actor_id("la inmobiliaria", "caso_a") == "la inmobiliaria::caso_a"
    assert net.scope_actor_id("la inmobiliaria", "caso_b") == "la inmobiliaria::caso_b"
    assert net.scope_actor_id("patricio herman", "caso_a") == "patricio herman"
    assert net.scope_actor_id("patricio herman", "caso_b") == "patricio herman"


def _row(document_id, nombre, case_id, source_table="enrichment_actor_v3_2", es_institucional=0):
    return {
        "document_id": document_id,
        "nombre": nombre,
        "case_id": case_id,
        "source_table": source_table,
        "es_institucional": es_institucional,
    }


def test_generic_actor_never_bridges_two_unrelated_cases():
    """Hallazgo real de Sol: 'la inmobiliaria' de 2 casos sin relacion se
    fusionaba en un solo nodo global y actuaba como puente espurio. Tras
    el anclaje por caso, ya no deberia existir camino entre los casos."""
    rows = net._annotate([
        _row("d1", "La Inmobiliaria", "caso_a"),
        _row("d1", "Inmobiliaria A", "caso_a"),
        _row("d2", "La Inmobiliaria", "caso_b"),
        _row("d2", "Inmobiliaria B", "caso_b"),
    ])
    graph = net.build_case_comembership_network(rows)
    import networkx as nx

    assert not nx.has_path(graph, "inmobiliaria a", "inmobiliaria b")


def test_document_cooccurrence_only_links_actors_sharing_a_real_document():
    """Hallazgo real de Sol: la v1 usaba `docs_a | docs_b` (union) y le
    daba peso a pares que NUNCA compartieron un documento. Esta red se
    construye agrupando directamente por document_id, asi que un par sin
    documento en comun no puede tener arista."""
    rows = net._annotate([
        _row("d1", "Actor A", "caso_a"),
        _row("d2", "Actor B", "caso_a"),  # mismo caso, documento DISTINTO
        _row("d1", "Actor C", "caso_a"),  # comparte d1 con Actor A
    ])
    graph = net.build_document_cooccurrence_network(rows)
    assert graph.has_edge("actor a", "actor c")
    assert not graph.has_edge("actor a", "actor b")
    assert not graph.has_edge("actor b", "actor c")


def test_case_comembership_links_actors_without_requiring_shared_document():
    """La red de copertenencia SI conecta actores del mismo caso aunque
    nunca compartan documento -- por diseno, para eso existe (relacion de
    arena de conflicto compartida), a diferencia de doc_cooccurrence."""
    rows = net._annotate([
        _row("d1", "Actor A", "caso_a"),
        _row("d2", "Actor B", "caso_a"),
    ])
    graph = net.build_case_comembership_network(rows)
    assert graph.has_edge("actor a", "actor b")


def test_bipartite_actor_case_counts_multiaffiliation_via_degree():
    rows = net._annotate([
        _row("d1", "Actor A", "caso_a"),
        _row("d2", "Actor A", "caso_b"),
        _row("d3", "Actor B", "caso_a"),
    ])
    graph = net.build_bipartite_actor_case(rows)
    assert graph.degree("actor a") == 2  # aparece en 2 casos
    assert graph.degree("actor b") == 1


def test_load_rows_excludes_event_source_table_which_has_no_actor_names():
    """enrichment_evento_v3_2 'nombre' es la descripcion completa del
    hito, no un actor -- debe seguir excluida en la v2."""
    assert "enrichment_evento_v3_2" not in net.ACTOR_SOURCE_TABLES
    assert set(net.ACTOR_SOURCE_TABLES) == {
        "enrichment_actor_v3_2",
        "enrichment_institucion_v3_2",
        "actor_second_pass_v2",
    }


def test_load_rows_against_real_warehouse_never_returns_event_descriptions():
    import sqlite3

    warehouse = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2_bridge.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse_v3_2_bridge.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    rows = net.load_rows(conn, "actor_event_project_link_case_safe")
    conn.close()
    assert len(rows) > 0
    assert all(r["source_table"] != "enrichment_evento_v3_2" for r in rows)
    long_names = [r for r in rows if len(r["nombre"]) > 200]
    assert long_names == []


def test_network_excluding_confirmed_institutions_keeps_unclassified_nodes():
    """Hallazgo real de Sol: la exclusion solo saca es_institucional=True;
    False y None (sin clasificar) se mantienen -- por eso el nombre de la
    funcion/campo no dice 'sin instituciones'."""
    rows = net._annotate([
        _row("d1", "Corte Suprema", "caso_a", es_institucional=1),
        _row("d1", "Actor Sin Clasificar", "caso_a", es_institucional=None),
        _row("d1", "Actor No Institucional", "caso_a", es_institucional=0),
    ])
    graph = net.build_case_comembership_network(rows)
    filtered = net.network_excluding_confirmed_institutions(graph)
    assert "corte suprema" not in filtered.nodes
    assert "actor sin clasificar" in filtered.nodes
    assert "actor no institucional" in filtered.nodes


def test_rank_correlation_only_uses_actors_present_in_both_bipartites():
    rows_a = net._annotate([
        _row("d1", "Actor A", "caso_a"),
        _row("d2", "Actor B", "caso_a"),
        _row("d3", "Actor Solo En A", "caso_a"),
    ])
    rows_b = net._annotate([
        _row("d1", "Actor A", "caso_a"),
        _row("d1", "Actor A", "caso_b"),
        _row("d2", "Actor B", "caso_a"),
    ])
    bip_a = net.build_bipartite_actor_case(rows_a)
    bip_b = net.build_bipartite_actor_case(rows_b)
    result = net.rank_correlation_common_actors(bip_a, bip_b)
    assert result["n_actores_comunes"] == 2  # actor a y actor b, no "actor solo en a"
