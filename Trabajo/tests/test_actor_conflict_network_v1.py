"""Pruebas de la red ACTOR<->CONFLICT (siguiente paso pedido por Sol tras
cerrar CONFLICT v1). Reutiliza la logica de build_actor_network_comparison_v1.py
via la clave generica 'case_id', poblada aqui con conflict_id."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "Trabajo" / "scripts"))

import build_actor_conflict_network_v1 as acn  # noqa: E402
import build_actor_network_comparison_v1 as net  # noqa: E402


def _connect_or_skip():
    import sqlite3

    if not acn.WAREHOUSE.exists():
        import pytest

        pytest.skip("warehouse_v3_2_bridge.sqlite no existe en este entorno")
    conn = sqlite3.connect(acn.WAREHOUSE)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "conflict" not in tables:
        import pytest

        conn.close()
        pytest.skip("tabla conflict no existe -- correr build_conflict_registry_v1.py primero")
    return conn


def test_load_rows_conflict_populates_case_id_key_with_conflict_id():
    """La clave 'case_id' del dict de fila, pese al nombre, debe contener
    un conflict_id (formato 'conflict:...') cuando viene de las vistas
    conflict_safe/extended -- verifica el reuso deliberado de la logica
    generica de build_actor_network_comparison_v1.py."""
    conn = _connect_or_skip()
    rows = acn.load_rows_conflict(conn, "actor_event_project_link_conflict_safe")
    conn.close()
    assert rows
    assert all(r["case_id"].startswith("conflict:") for r in rows)


def _build_three_universos(conn):
    rows_case_old = net._annotate(net.load_rows(conn, acn.VIEW_CASE_SAFE))
    bip_case_old = net.build_bipartite_actor_case(rows_case_old)
    rows_case_matched = net._annotate(net.load_rows(conn, acn.VIEWS_CONFLICT["conflict_safe"]))
    bip_case_matched = net.build_bipartite_actor_case(rows_case_matched)
    rows_conflict = net._annotate(acn.load_rows_conflict(conn, acn.VIEWS_CONFLICT["conflict_safe"]))
    bip_conflict = net.build_bipartite_actor_case(rows_conflict)
    return bip_case_old, bip_case_matched, bip_conflict


def test_case_matched_has_same_actor_universe_as_conflict_safe():
    """Hallazgo metodologico real de Sol: CASE_MATCHED debe compartir
    EXACTAMENTE el mismo universo de documentos/menciones que
    conflict_safe (misma vista, solo cambia la clave de agrupacion) --
    si difiere, la descomposicion gate/collapse deja de ser valida.

    Node-por-node exacto solo se cumple para actores NO genericos: los
    terminos de GENERIC_ACTOR_TERMS se anclan a la clave de agrupacion
    (scope_actor_id), asi que 'la municipalidad::<case_id>' y
    'la municipalidad::<conflict_id>' son nodos distintos aunque vengan
    de la misma mencion -- eso es un efecto esperado del diseno de
    anclaje, no un problema de universo. La cardinalidad total SI debe
    coincidir exactamente (mismo numero de menciones de actor)."""
    conn = _connect_or_skip()
    _, bip_case_matched, bip_conflict = _build_three_universos(conn)
    conn.close()
    actors_matched = set(net.actor_nodes(bip_case_matched))
    actors_conflict = set(net.actor_nodes(bip_conflict))
    assert len(actors_matched) == len(actors_conflict)

    no_genericos_matched = {a for a in actors_matched if "::" not in a}
    no_genericos_conflict = {a for a in actors_conflict if "::" not in a}
    assert no_genericos_matched == no_genericos_conflict


def test_conflict_collapse_never_positive_mathematical_invariant():
    """Propiedad estructural garantizada, pedida explicitamente por Sol:
    conflict_id es una funcion many-to-one de case_id DENTRO del mismo
    universo (CASE_MATCHED vs CONFLICT_SAFE), asi que para cualquier
    actor comparable, n_conflicts <= n_case_matched siempre. Un valor
    positivo seria un bug (universo distinto o identidad de actor no
    comparable), nunca un hallazgo real -- no es un test empirico, es un
    invariante matematico del mapeo."""
    conn = _connect_or_skip()
    bip_case_old, bip_case_matched, bip_conflict = _build_three_universos(conn)
    conn.close()
    dec = acn.decompose_gate_vs_conflict_collapse(bip_case_old, bip_case_matched, bip_conflict)
    assert dec["n_actores_caida_por_ambos_efectos"] >= 0  # sanity, no lanza
    # verificar directamente sobre todos los actores comparables, no solo el top-15
    common = set(net.actor_nodes(bip_case_matched)) & set(net.actor_nodes(bip_conflict))
    assert all(bip_conflict.degree(a) <= bip_case_matched.degree(a) for a in common)


def test_seremi_bienes_nacionales_is_the_real_conflict_collapse_example():
    """Prueba sustantiva concreta verificada por Sol contra el mismo
    SQLite: de 49 actores con caida aparente en la comparacion anterior
    (CASE_OLD vs CONFLICT_SAFE, universo distinto), solo 1 -- Seremi de
    Bienes Nacionales -- cae por la fusion CASE->CONFLICT en si misma
    (delta_gate=0, delta_conflict_collapse=-1). Corte Suprema, que la v1
    de este script presentaba como el ejemplo estrella de fragmentacion,
    en realidad tiene delta_conflict_collapse=0 (su caida es integra del
    gate documental, no de fusionar casos)."""
    conn = _connect_or_skip()
    bip_case_old, bip_case_matched, bip_conflict = _build_three_universos(conn)
    conn.close()
    dec = acn.decompose_gate_vs_conflict_collapse(bip_case_old, bip_case_matched, bip_conflict)

    assert dec["n_actores_caida_solo_por_fusion_case_conflict"] == 1
    assert dec["n_actores_caida_solo_por_gate_documental"] == 48

    # Corte Suprema: siempre esta en el top-15 de mayor caida total, y su
    # caida es integra del gate documental, no de fusionar case_id.
    by_actor = {r["actor"]: r for r in dec["actores_con_mayor_caida_total"]}
    corte_suprema = by_actor["Corte Suprema"]
    assert corte_suprema["delta_conflict_collapse"] == 0
    assert corte_suprema["delta_gate"] < 0

    # Seremi de Bienes Nacionales es el unico caso real de fusion
    # case->conflict -- verificado directo contra los grafos, no contra
    # el top-15 (su caida es de solo -1, puede no entrar al slice).
    node = "seremi de bienes nacionales"
    assert bip_case_old.degree(node) == bip_case_matched.degree(node)  # delta_gate == 0
    assert bip_conflict.degree(node) == bip_case_matched.degree(node) - 1  # delta_conflict_collapse == -1


def test_decompose_reports_excluded_generic_nodes_explicitly():
    """Hallazgo/precision de Sol: CASE_MATCHED y CONFLICT_SAFE tienen el
    mismo numero de nodos actor (1001) pero solo 971 son identidades
    persistentes comparables -- los 30 restantes de cada lado son
    terminos genericos anclados a su propia unidad de agrupacion
    (case_id vs conflict_id), asi que la misma mencion generica se
    vuelve un nodo distinto en cada red por diseno. Deben reportarse
    explicitamente, no quedar implicitos en la interseccion."""
    conn = _connect_or_skip()
    bip_case_old, bip_case_matched, bip_conflict = _build_three_universos(conn)
    conn.close()
    dec = acn.decompose_gate_vs_conflict_collapse(bip_case_old, bip_case_matched, bip_conflict)

    assert dec["n_actores_comparables_en_los_3_universos"] == 971
    assert dec["n_nodos_genericos_excluidos_case_matched"] == 30
    assert dec["n_nodos_genericos_excluidos_conflict_safe"] == 30
    assert all("::" in n for n in dec["nodos_genericos_excluidos_case_matched"])
    assert all("::" in n for n in dec["nodos_genericos_excluidos_conflict_safe"])


def test_decompose_reports_correlation_and_common_actor_count():
    conn = _connect_or_skip()
    bip_case_old, bip_case_matched, bip_conflict = _build_three_universos(conn)
    conn.close()
    dec = acn.decompose_gate_vs_conflict_collapse(bip_case_old, bip_case_matched, bip_conflict)
    assert dec["n_actores_comparables_en_los_3_universos"] > 0
