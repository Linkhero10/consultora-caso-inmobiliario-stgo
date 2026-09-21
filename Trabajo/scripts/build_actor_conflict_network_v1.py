"""Reconstruye la red de actores usando CONFLICT como unidad sociologica
en vez de project.case_id -- el paso que la revisión pidio explicitamente al
cerrar CONFLICT v1 (2026-09-18): "ahora si reconstruiria la red como
ACTOR <-> CONFLICT ... y mediria cuanto de la centralidad anterior era
artefacto de fragmentar un mismo conflicto en varios proyectos".

Reutiliza toda la logica de construccion de red de
build_actor_network_comparison_v1.py (normalizacion de nombre, anclaje de
terminos genericos, clasificacion institucional, bipartita actor<->unidad,
correlacion de rango) sin duplicarla: esas funciones son genericas sobre
una clave de agrupacion llamada 'case_id' en los dicts de fila -- aqui se
puebla esa misma clave con conflict_id en vez de project.case_id. El
nombre de la clave no cambia (para poder reusar el codigo tal cual);
donde importa la distincion se documenta explicitamente.

Comparaciones que arma este script:
1. Bipartita ACTOR<->CONFLICT (safe: role focal/co_focal; extended: +
   contextual_mention) -- mismo patron conservadora/inclusiva de antes,
   pero la variable que cambia ahora es el gate documental de CONFLICT
   (document_conflict_case_safe/extended), no resolution_status (que se
   mantiene fijo en 'resolved_explicit' para ambas).
2. [CORREGIDO 2026-09-18, hallazgo metodologico real de la revisión] La primera
   version de este script comparaba directamente CONFLICT_SAFE contra la
   red vieja CASE_OLD (actor_event_project_link_case_safe) y atribuia
   CUALQUIER caida de multiafiliacion a "fragmentacion de un mismo
   conflicto en varios case_id". Eso confunde 2 efectos distintos, porque
   al pasar de CASE_OLD a CONFLICT_SAFE cambian a la vez la unidad
   (case_id->conflict_id) Y el universo de evidencia (CONFLICT_SAFE exige
   ademas que el documento trate ese conflicto como focal/co_focal via
   document_conflict_case_safe -- CASE_OLD solo exigia unidad_caso_tipo=
   'caso_unico'). La revisión verificó contra el mismo SQLite: de 49 actores con
   caida aparente, 48/49 se explican enteramente por el gate documental
   (CASE_OLD->CASE_MATCHED) y solo 1/49 (Seremi de Bienes Nacionales) por
   la fusion CASE->CONFLICT en si misma.

   La descomposicion correcta usa un tercer universo intermedio:
     CASE_OLD      = actor_event_project_link_case_safe (red anterior)
     CASE_MATCHED  = MISMAS filas que CONFLICT_SAFE, agrupadas por
                     project.case_id en vez de conflict_id (se obtiene
                     con net.load_rows() sobre la MISMA vista
                     actor_event_project_link_conflict_safe -- esa vista
                     ya trae project_id, net.load_rows() lo agrupa por
                     case_id via el JOIN a project que ya hace)
     CONFLICT_SAFE = esas mismas filas agrupadas por conflict_id
   Y descompone, por actor:
     delta_gate              = n_case_matched - n_case_old
     delta_conflict_collapse = n_conflicts - n_case_matched
     delta_total              = n_conflicts - n_case_old
   Propiedad garantizada matematicamente (conflict_id es una funcion
   many-to-one de case_id DENTRO del mismo universo): para cualquier
   actor, n_conflicts <= n_case_matched siempre -- si delta_conflict_collapse
   fuera positivo, seria un bug (universo distinto o identidad de actor
   no comparable), nunca un hallazgo real. Protegido con test dedicado.
"""

import json
import sqlite3
from pathlib import Path

import build_actor_network_comparison_v1 as net

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2_bridge.sqlite"
OUTPUT = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "comparacion_red_actores_conflict_vs_case.json"

VIEWS_CONFLICT = {
    "conflict_safe": "actor_event_project_link_conflict_safe",
    "conflict_extended": "actor_event_project_link_conflict_extended",
}
VIEW_CASE_SAFE = "actor_event_project_link_case_safe"


def load_rows_conflict(conn: sqlite3.Connection, view: str) -> list[dict]:
    """Igual que net.load_rows(), pero la vista ya trae conflict_id
    materializado (no hay que hacer JOIN a project.case_id) -- ese valor
    se puebla en la clave 'case_id' de cada fila para poder reutilizar sin
    cambios build_bipartite_actor_case()/build_case_comembership_network()/
    etc., que son genericas sobre esa clave de agrupacion."""
    placeholders = ",".join("?" for _ in net.ACTOR_SOURCE_TABLES)
    rows = conn.execute(
        f"""
        SELECT l.document_id, l.nombre, l.conflict_id, l.source_table,
               CASE
                   WHEN l.source_table = 'enrichment_institucion_v3_2' THEN 1
                   WHEN l.source_table = 'enrichment_actor_v3_2' AND ea.tipo IN ({",".join("?" for _ in net.INSTITUTIONAL_ACTOR_TIPOS)}) THEN 1
                   WHEN l.source_table = 'enrichment_actor_v3_2' THEN 0
                   ELSE NULL
               END AS es_institucional
        FROM {view} l
        LEFT JOIN enrichment_actor_v3_2 ea
            ON l.source_table = 'enrichment_actor_v3_2' AND ea.actor_id = l.source_id
        WHERE l.source_table IN ({placeholders})
        """,
        (*net.INSTITUTIONAL_ACTOR_TIPOS, *net.ACTOR_SOURCE_TABLES),
    ).fetchall()
    return [
        {"document_id": r[0], "nombre": r[1], "case_id": r[2], "source_table": r[3], "es_institucional": r[4]}
        for r in rows
    ]


def decompose_gate_vs_conflict_collapse(
    bip_case_old: "net.nx.Graph", bip_case_matched: "net.nx.Graph", bip_conflict_safe: "net.nx.Graph"
) -> dict:
    """Descompone, por actor, cuanto de la caida de multiafiliacion viene
    del gate documental (CASE_OLD->CASE_MATCHED, universo cambia) y
    cuanto viene de la fusion CASE->CONFLICT en si misma (CASE_MATCHED->
    CONFLICT_SAFE, mismo universo). Ver docstring del modulo para la
    motivacion (hallazgo real de la revisión: confundir ambos efectos)."""
    actors_old = set(net.actor_nodes(bip_case_old))
    actors_matched = set(net.actor_nodes(bip_case_matched))
    actors_conflict = set(net.actor_nodes(bip_conflict_safe))
    common = sorted(actors_old & actors_matched & actors_conflict)

    # [AGREGADO 2026-09-18, precision pedida por la revisión] CASE_MATCHED y
    # CONFLICT_SAFE tienen el mismo NUMERO de nodos actor (1001 cada uno),
    # pero no coinciden nodo por nodo: los terminos de GENERIC_ACTOR_TERMS
    # se anclan via scope_actor_id() a la clave de agrupacion misma
    # ('actor::case_id' en CASE_MATCHED vs 'actor::conflict_id' en
    # CONFLICT_SAFE), asi que la MISMA mencion generica ("los vecinos",
    # "municipio", "estado", "la inmobiliaria"...) se vuelve un nodo
    # distinto en cada red -- por diseno correcto (esos terminos NUNCA
    # deben fusionarse globalmente entre unidades distintas, ver
    # docstring de build_actor_network_comparison_v1.py), no por error.
    # La descomposicion gate/collapse solo tiene sentido para identidades
    # PERSISTENTES (no anclas contextuales), asi que se reportan aparte
    # los nodos genericos excluidos de cada lado en vez de dejarlos
    # implicitos en la interseccion.
    genericos_solo_case_matched = sorted(actors_matched - actors_conflict)
    genericos_solo_conflict_safe = sorted(actors_conflict - actors_matched)

    rows = []
    for a in common:
        n_case_old = bip_case_old.degree(a)
        n_case_matched = bip_case_matched.degree(a)
        n_conflicts = bip_conflict_safe.degree(a)
        rows.append(
            {
                "actor": bip_conflict_safe.nodes[a]["label"],
                "n_case_old": n_case_old,
                "n_case_matched": n_case_matched,
                "n_conflicts": n_conflicts,
                "delta_gate": n_case_matched - n_case_old,
                "delta_conflict_collapse": n_conflicts - n_case_matched,
                "delta_total": n_conflicts - n_case_old,
            }
        )

    n_solo_gate = sum(1 for r in rows if r["delta_gate"] < 0 and r["delta_conflict_collapse"] == 0)
    n_solo_collapse = sum(1 for r in rows if r["delta_gate"] == 0 and r["delta_conflict_collapse"] < 0)
    n_ambos = sum(1 for r in rows if r["delta_gate"] < 0 and r["delta_conflict_collapse"] < 0)
    n_sin_cambio = sum(1 for r in rows if r["delta_total"] == 0)

    rows_con_caida = [r for r in rows if r["delta_total"] < 0]
    rows_con_caida.sort(key=lambda r: r["delta_total"])

    return {
        "n_actores_comparables_en_los_3_universos": len(common),
        "n_actores_sin_cambio": n_sin_cambio,
        "n_actores_caida_solo_por_gate_documental": n_solo_gate,
        "n_actores_caida_solo_por_fusion_case_conflict": n_solo_collapse,
        "n_actores_caida_por_ambos_efectos": n_ambos,
        "actores_con_mayor_caida_total": rows_con_caida[:15],
        "n_nodos_genericos_excluidos_case_matched": len(genericos_solo_case_matched),
        "n_nodos_genericos_excluidos_conflict_safe": len(genericos_solo_conflict_safe),
        "nodos_genericos_excluidos_case_matched": genericos_solo_case_matched,
        "nodos_genericos_excluidos_conflict_safe": genericos_solo_conflict_safe,
        "nota": (
            "delta_gate = n_case_matched - n_case_old: efecto de exigir ademas que "
            "el documento trate el proyecto/conflicto como focal/co_focal "
            "(document_conflict_case_safe), NO tiene que ver con CASE vs CONFLICT. "
            "delta_conflict_collapse = n_conflicts - n_case_matched (mismo universo "
            "exacto en ambos lados): efecto PURO de fusionar case_id en conflict_id. "
            "Garantizado matematicamente que delta_conflict_collapse <= 0 siempre "
            "(conflict_id es funcion many-to-one de case_id) -- un valor positivo "
            "seria un bug, no un hallazgo."
        ),
        "nota_genericos": (
            "CASE_MATCHED y CONFLICT_SAFE tienen el MISMO numero de nodos actor "
            "(1001 cada uno) pero solo 971 son identidades persistentes "
            "comparables entre ambos. Los 30 restantes de cada lado son terminos "
            "de GENERIC_ACTOR_TERMS anclados a su unidad de agrupacion "
            "(case_id o conflict_id segun la red) -- la MISMA mencion generica "
            "('los vecinos', 'municipio', 'estado', 'la inmobiliaria'...) se "
            "vuelve un nodo distinto en cada red por diseno (nunca deben "
            "fusionarse globalmente entre unidades distintas). El 48/1 de la "
            "descomposicion arriba se calcula SOLO sobre los 971 actores "
            "persistentes -- no representa a los 1001 nodos totales de cada red."
        ),
    }


def main():
    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")

    data = {}
    for label, view in VIEWS_CONFLICT.items():
        rows = net._annotate(load_rows_conflict(conn, view))
        bip = net.build_bipartite_actor_case(rows)
        data[label] = {"rows": rows, "bipartite": bip, "bipartite_summary": net.summarize_bipartite(bip, rows)}
        b = data[label]["bipartite_summary"]
        print(f"[{label}] bipartita: {b['n_actores_nodos']} actores, {b['n_casos_nodos']} conflictos, "
              f"{b['n_actor_case_links']} links")

    rows_case_old = net._annotate(net.load_rows(conn, VIEW_CASE_SAFE))
    bip_case_old = net.build_bipartite_actor_case(rows_case_old)
    case_old_summary = net.summarize_bipartite(bip_case_old, rows_case_old)
    print(f"[CASE_OLD, red anterior] bipartita: {case_old_summary['n_actores_nodos']} actores, "
          f"{case_old_summary['n_casos_nodos']} case_id, {case_old_summary['n_actor_case_links']} links")

    # CASE_MATCHED: EXACTAMENTE las mismas filas que conflict_safe (mismo
    # universo de documentos/actores/links), pero agrupadas por
    # project.case_id -- se obtiene con net.load_rows() sobre la misma
    # vista actor_event_project_link_conflict_safe, que ya expone
    # project_id y que net.load_rows() agrupa via su propio JOIN a project.
    rows_case_matched = net._annotate(net.load_rows(conn, VIEWS_CONFLICT["conflict_safe"]))
    bip_case_matched = net.build_bipartite_actor_case(rows_case_matched)
    case_matched_summary = net.summarize_bipartite(bip_case_matched, rows_case_matched)
    print(f"[CASE_MATCHED, mismo universo que conflict_safe] bipartita: "
          f"{case_matched_summary['n_actores_nodos']} actores, {case_matched_summary['n_casos_nodos']} case_id, "
          f"{case_matched_summary['n_actor_case_links']} links")

    comparacion_safe_vs_extended = {
        "top15_overlap": {
            "solo_en_conflict_safe": sorted(
                {d["actor"] for d in data["conflict_safe"]["bipartite_summary"]["actores_mas_multiafiliados_por_n_casos"]}
                - {d["actor"] for d in data["conflict_extended"]["bipartite_summary"]["actores_mas_multiafiliados_por_n_casos"]}
            ),
            "solo_en_conflict_extended": sorted(
                {d["actor"] for d in data["conflict_extended"]["bipartite_summary"]["actores_mas_multiafiliados_por_n_casos"]}
                - {d["actor"] for d in data["conflict_safe"]["bipartite_summary"]["actores_mas_multiafiliados_por_n_casos"]}
            ),
        },
        "correlacion_spearman": net.rank_correlation_common_actors(data["conflict_safe"]["bipartite"], data["conflict_extended"]["bipartite"]),
    }

    decomposicion = decompose_gate_vs_conflict_collapse(bip_case_old, bip_case_matched, data["conflict_safe"]["bipartite"])

    output = {
        "fuente": str(WAREHOUSE.relative_to(PROJECT_ROOT)),
        "contexto": (
            "Red ACTOR<->CONFLICT (siguiente paso pedido en revisión tras cerrar "
            "CONFLICT v1). conflict_safe usa actor_event_project_link_conflict_safe "
            "(resolution_status='resolved_explicit' + document_conflict role IN "
            "('focal','co_focal')); conflict_extended agrega contextual_mention. "
            "case_safe es la red ANTERIOR (actor_event_project_link_case_safe, "
            "agrupando por project.case_id en vez de conflict_id), conservada aqui "
            "solo para la comparacion, no como resultado nuevo."
        ),
        "conflict_safe": {k: v for k, v in data["conflict_safe"].items() if k not in ("rows", "bipartite")},
        "conflict_extended": {k: v for k, v in data["conflict_extended"].items() if k not in ("rows", "bipartite")},
        "case_old_red_anterior": {"bipartite_summary": case_old_summary},
        "case_matched_mismo_universo_que_conflict_safe": {"bipartite_summary": case_matched_summary},
        "comparacion_conflict_safe_vs_extended": comparacion_safe_vs_extended,
        "descomposicion_gate_vs_fusion_case_conflict": decomposicion,
    }

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEscrito: {OUTPUT.relative_to(PROJECT_ROOT)}")

    conn.close()
    return output


if __name__ == "__main__":
    main()
