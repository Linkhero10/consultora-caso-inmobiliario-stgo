"""Mide el impacto de Actor Identity Resolution v1 (actor_registry/
actor_alias) sobre la red ACTOR<->CONFLICT -- el experimento que la revisión pidio
explicitamente tras cerrar el registry (2026-09-18):

    ACTOR<->CONFLICT raw
            v
    actor_alias / actor_registry
            v
    ACTOR_ENTITY<->CONFLICT

Requisitos explicitos de la revisión para esta aplicacion (no para el registry en
si, que ya quedo cerrado):

1. Cuando distintos alias de una misma entidad aparecen en el MISMO
   conflicto, la arista entity_id<->conflict_id debe existir UNA sola
   vez, no una por variante textual. Se logra automaticamente reusando
   build_bipartite_actor_case() de build_actor_network_comparison_v1.py:
   esa funcion ya agrupa aristas por (actor_scoped, case_id) con un set
   de document_id -- si TODAS las filas de una entidad resuelta comparten
   el mismo actor_scoped=entity_id, las aristas se colapsan solas, con
   n_documentos = union real de documentos de todos sus alias.
2. El registry es autoridad superior de tipo institucional: cualquier
   fila resuelta a una entidad de ACTOR_ENTITIES (todas
   'institucion_nacional_verificada') se marca es_institucional=1, sin
   importar como se clasifico esa fila individual en su tabla de origen.
3. Provenance: que alias contribuyeron a cada entidad resuelta ya vive
   completo en actor_alias/actor_registry (incluye 'razon' por alias).
   [PRECISION 2026-09-18, la revisión] Lo que build_variant_breakdown() agrega
   aqui es el GRADO EN LA RED RAW de cada alias por separado (cuantos
   conflictos tenia esa variante ANTES de resolver) -- util para ver de
   donde viene la ganancia del nodo consolidado, pero no un conteo de
   filas/documentos por alias (eso, si se necesita, se consulta
   directamente en actor_alias/actor_event_project_link).

No se toca la logica de anclaje de terminos genericos (GENERIC_ACTOR_TERMS
sigue funcionando exactamente igual, fuera del alcance de este registry).
"""

import json
import sqlite3
from pathlib import Path

import build_actor_network as acn
import network_common as net
import build_actor_registry as reg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
OUTPUT = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "impacto_actor_registry_en_red_conflict.json"

VIEW = acn.VIEWS_CONFLICT["conflict_safe"]


def resolve_identity(rows: list[dict], alias_to_entity: dict[str, str], entity_label: dict[str, str]) -> list[dict]:
    """Para cada fila anotada, si su nombre normalizado resuelve a una
    entidad del registry, sobreescribe actor_scoped=entity_id (colapsa
    todos sus alias al mismo nodo), nombre=canonical_label (garantiza que
    _node_metadata elija siempre esa etiqueta, no depende de cual variante
    fue mas frecuente) y es_institucional=1 (el registry es autoridad
    superior de tipo para estas 6 entidades). Filas sin match quedan tal
    cual (siguen su propia identidad sin resolver, incluidos los terminos
    genericos anclados)."""
    out = []
    for row in rows:
        entity_id = alias_to_entity.get(row["actor_norm"])
        if entity_id is None:
            out.append(row)
            continue
        out.append({**row, "actor_scoped": entity_id, "nombre": entity_label[entity_id], "es_institucional": 1})
    return out


def build_alias_map(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    alias_to_entity = dict(conn.execute("SELECT nombre_norm, entity_id FROM actor_alias").fetchall())
    entity_label = dict(conn.execute("SELECT entity_id, canonical_label FROM actor_registry").fetchall())
    return alias_to_entity, entity_label


def compare_raw_vs_resolved(bip_raw: "net.nx.Graph", bip_resolved: "net.nx.Graph", entity_ids: set[str]) -> dict:
    actors_raw = set(net.actor_nodes(bip_raw))
    actors_resolved = set(net.actor_nodes(bip_resolved))

    # Actores NO tocados por el registry: mismo node id en ambos grafos --
    # base valida para correlacion de rango (comparan exactamente la
    # misma identidad, la unica variable que cambia es la presencia de
    # las 6 entidades consolidadas alrededor).
    actors_unresolved_common = sorted((actors_raw & actors_resolved) - entity_ids)

    ranks_raw = [bip_raw.degree(a) for a in actors_unresolved_common]
    ranks_resolved = [bip_resolved.degree(a) for a in actors_unresolved_common]

    # [PRECISION 2026-09-18, la revisión] rho=1.0 aqui es una propiedad ESPERADA
    # de la transformacion, no un hallazgo empirico: en una bipartita
    # ACTOR<->CONFLICT, fusionar OTROS nodos actor nunca cambia el grado
    # de un actor no tocado (su grado cuenta en cuantos conflictos
    # aparece el, no como se etiquetan otros nodos). Se reporta el
    # conteo directo (cuantos conservaron su grado exacto) como metrica
    # principal, y Spearman queda solo como confirmacion secundaria.
    n_grado_identico = sum(1 for a, b in zip(ranks_raw, ranks_resolved) if a == b)

    rho, p = (None, None)
    if len(actors_unresolved_common) >= 3:
        from scipy.stats import spearmanr

        rho, p = spearmanr(ranks_raw, ranks_resolved)
        rho, p = round(float(rho), 3), round(float(p), 5)

    # Para cada entidad resuelta: cual era el MAYOR grado que tenia
    # CUALQUIERA de sus variantes por separado en la red raw, vs su grado
    # consolidado en la red resuelta -- eso es "cuanto gana por fusionar
    # alias", no una comparacion contra un nodo que ya no existe.
    ganadores = []
    for entity_id in sorted(entity_ids):
        if entity_id not in actors_resolved:
            continue
        label = bip_resolved.nodes[entity_id]["label"]
        grado_resuelto = bip_resolved.degree(entity_id)
        ganadores.append({"entity_id": entity_id, "label": label, "grado_consolidado": grado_resuelto})

    return {
        "n_actores_nodos_raw": len(actors_raw),
        "n_actores_nodos_resolved": len(actors_resolved),
        "delta_n_nodos": len(actors_resolved) - len(actors_raw),
        "n_links_raw": bip_raw.number_of_edges(),
        "n_links_resolved": bip_resolved.number_of_edges(),
        "n_actores_no_tocados_por_registry_comunes": len(actors_unresolved_common),
        "n_actores_no_tocados_con_grado_identico": n_grado_identico,
        "spearman_rho_actores_no_tocados": rho,
        "spearman_p_actores_no_tocados": p,
        "entidades_consolidadas": ganadores,
        "nota": (
            f"{n_grado_identico}/{len(actors_unresolved_common)} actores no tocados por el "
            "registry conservaron su grado exacto -- esto es una PROPIEDAD ESPERADA de la "
            "transformacion (bipartita ACTOR<->CONFLICT: fusionar otros nodos actor nunca "
            "cambia cuantos conflictos tiene un actor no tocado), no un hallazgo empirico "
            "independiente. spearman_rho se deja como confirmacion secundaria, no como la "
            "metrica principal. Las 6 entidades consolidadas se reportan aparte porque no "
            "tienen un unico nodo "
            "'antes' comparable (eran 2-6 nodos distintos cada una)."
        ),
    }


def build_variant_breakdown(conn: sqlite3.Connection, registry_rows: list[dict], alias_rows: list[dict], bip_raw: "net.nx.Graph") -> list[dict]:
    """Provenance: para cada entidad, que grado tenia CADA uno de sus
    alias por separado en la red raw (antes de resolver), para poder
    verificar que el grado consolidado no perdio informacion."""
    breakdown = []
    for row in registry_rows:
        alias_de_entidad = [a["nombre_norm"] for a in alias_rows if a["entity_id"] == row["entity_id"]]
        variantes = []
        for alias_norm in alias_de_entidad:
            nodo = alias_norm  # en la red raw, actores no-genericos usan el nombre normalizado tal cual
            if bip_raw.has_node(nodo):
                variantes.append({"alias": alias_norm, "grado_en_red_raw": bip_raw.degree(nodo)})
            else:
                variantes.append({"alias": alias_norm, "grado_en_red_raw": 0})
        breakdown.append({"canonical_label": row["canonical_label"], "entity_key": row["entity_key"], "variantes": variantes})
    return breakdown


def main():
    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")

    registry_rows, alias_rows = reg.build_registry()
    alias_to_entity, entity_label = build_alias_map(conn)
    entity_ids = set(entity_label.keys())

    rows_raw = net._annotate(acn.load_rows_conflict(conn, VIEW))
    bip_raw = net.build_bipartite_actor_case(rows_raw)

    rows_resolved = resolve_identity(rows_raw, alias_to_entity, entity_label)
    bip_resolved = net.build_bipartite_actor_case(rows_resolved)

    comparacion = compare_raw_vs_resolved(bip_raw, bip_resolved, entity_ids)
    variantes = build_variant_breakdown(conn, registry_rows, alias_rows, bip_raw)

    max_variante_por_entidad = {
        row["entity_id"]: max((v["grado_en_red_raw"] for v in vb["variantes"]), default=0)
        for row, vb in zip(registry_rows, variantes)
    }
    for g in comparacion["entidades_consolidadas"]:
        max_variante = max_variante_por_entidad.get(g["entity_id"], 0)
        g["max_grado_de_una_sola_variante_raw"] = max_variante
        g["ganancia_por_consolidacion"] = g["grado_consolidado"] - max_variante

    top_resolved = sorted(
        ((bip_resolved.nodes[n]["label"], bip_resolved.degree(n)) for n in net.actor_nodes(bip_resolved)),
        key=lambda kv: kv[1],
        reverse=True,
    )[:20]
    top_raw = sorted(
        ((bip_raw.nodes[n]["label"], bip_raw.degree(n)) for n in net.actor_nodes(bip_raw)),
        key=lambda kv: kv[1],
        reverse=True,
    )[:20]

    output = {
        "fuente": str(WAREHOUSE.relative_to(PROJECT_ROOT)),
        "contexto": (
            "Impacto de Actor Identity Resolution v1 (6 entidades, 29 alias) sobre la red "
            "ACTOR<->CONFLICT (vista actor_event_project_link_conflict_safe). Aristas "
            "entity_id<->conflict_id se deduplican automaticamente al reutilizar "
            "build_bipartite_actor_case() con actor_scoped=entity_id para filas resueltas -- "
            "misma logica que ya deduplica actores no-resueltos, sin codigo nuevo de dedup."
        ),
        "top20_multiafiliacion_raw": [{"actor": a, "n_conflicts": n} for a, n in top_raw],
        "top20_multiafiliacion_resolved": [{"actor": a, "n_conflicts": n} for a, n in top_resolved],
        "comparacion": comparacion,
        "provenance_por_entidad": variantes,
    }

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(comparacion, ensure_ascii=False, indent=2))
    print(f"\nEscrito: {OUTPUT.relative_to(PROJECT_ROOT)}")

    conn.close()
    return output


if __name__ == "__main__":
    main()
