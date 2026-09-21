"""Compara la estructura de actores construida con el filtro conservador
(actor_event_project_link_case_safe) contra la version mas inclusiva
(actor_event_project_link_include_inferred).

Segunda versión (2026-09-18), reescrita tras una revisión adversarial de la v1.
La revisión confirmó 2 problemas reales de diseño en la v1 (no
cosmeticos, verificados contra el codigo real antes de corregir):

1. La arista de "coocurrencia" en realidad usaba `docs_a | docs_b` (union)
   en vez de interseccion -- daba peso > 0 a pares de actores que NUNCA
   aparecieron juntos en un documento. Ademas, esa red de clique-por-caso
   no es "coocurrencia documental": es "copertenencia al mismo caso". Se
   separan aqui en 2 objetos distintos y con nombre honesto:
   - build_document_cooccurrence_network(): coocurrencia real (mismo
     documento), sin el bug -- se agrupa directamente por document_id, no
     por interseccion de sets, asi que el bug no puede reaparecer por
     construccion.
   - build_case_comembership_network(): la red de clique-por-caso de la
     v1, renombrada para no prometer "coocurrencia" que no mide.

2. `normalize_actor_name()` fusiona globalmente terminos genericos
   ("la inmobiliaria", "los vecinos", "municipio") que NO son la misma
   entidad entre casos distintos -- eso crea puentes espurios entre casos
   sin ningun actor real en comun. GENERIC_ACTOR_TERMS + scope_actor_id()
   los ancla a su case_id (identidad contextual) en vez de fusionarlos
   globalmente. Es una lista curada a mano desde los resultados reales de
   la v1 (no una heuristica automatica), documentada como parcial.

La revisión también señaló, correctamente, que el objeto primario para el arco de
Dario deberia ser la red bipartita ACTOR <-> CASO (evita la explosion de
clique N(N-1)/2 y responde preguntas directamente interpretables: en
cuantos casos aparece un actor, que actores conectan casos distintos).
Se agrega build_bipartite_actor_case() como resultado principal; las 2
redes actor-actor quedan como material secundario/diagnostico.

Limitaciones que quedan explicitamente sin resolver en esta version
(documentadas, no escondidas):
- Identidad de actor sigue siendo nombre normalizado, no resuelta via
  entity_actor_crosswalk (cobertura ~45%, mezclarla de forma desigual
  entre vistas sesgaria la comparacion). "Servicio de Evaluacion
  Ambiental" y "Servicio de Evaluacion Ambiental (SEA)" siguen siendo 2
  nodos distintos.
- La clasificacion institucional sigue siendo parcial (312/1222 nodos sin
  clasificar en la conservadora, 25.5%): actor_second_pass_v2 no tiene
  columna tipo copiada a este warehouse, y el tipo='otro' de
  enrichment_actor mete a 'Estado' en el mismo saco que actores no
  institucionales. Por eso el campo se llama explicitamente
  'red_excluyendo_actores_confirmados_institucionales', no 'red sin
  instituciones' -- False y None conservan el nodo, solo True lo excluye.
"""

import json
import sqlite3
import statistics
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
OUTPUT = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "comparacion_red_actores_conservadora_vs_inclusiva.json"

VIEWS = {
    "conservadora": "actor_event_project_link_case_safe",
    "inclusiva": "actor_event_project_link_include_inferred",
}

# enrichment_event NO contiene nombres de actor: su columna 'nombre'
# es la descripcion completa del hito. Excluirla es un requisito de tipo,
# no una eleccion de diseno (ver test_load_rows_against_real_warehouse...).
ACTOR_SOURCE_TABLES = ("enrichment_actor", "enrichment_institution", "actor_second_pass_v2")

INSTITUTIONAL_ACTOR_TIPOS = {
    "municipio",
    "poder_judicial",
    "contraloria",
    "seremi_minvu",
    "consejo_monumentos_nacionales",
}

# Terminos genericos/contextuales identificados a mano en el top-15 real
# de la v1 (la revisión, 2026-09-18): ninguno de estos identifica una entidad
# persistente entre casos -- "la inmobiliaria" del caso A y la del caso B
# casi nunca son la misma empresa. Lista parcial, no exhaustiva: cualquier
# termino nuevo de este tipo que aparezca en un futuro top-N deberia
# agregarse aqui, no asumirse resuelto por esta lista.
GENERIC_ACTOR_TERMS = {
    "municipio",
    "el municipio",
    "la municipalidad",
    "municipalidad",
    "los vecinos",
    "vecinos",
    "vecinos de la comuna",
    "grupo de vecinos de esa comuna",
    "un grupo de vecinos de esa comuna",
    "residentes",
    "las familias",
    "familias",
    "la comunidad",
    "el gobierno",
    "la inmobiliaria",
    "las inmobiliarias",
    "inmobiliarias",
    "la empresa",
    "las empresas",
    "estado",
    "el estado",
}


def normalize_actor_name(raw: str) -> str:
    return " ".join(raw.strip().split()).lower()


def scope_actor_id(actor_norm: str, case_id: str) -> str:
    """Ancla un termino generico a su caso para que nunca se fusione
    globalmente con el mismo termino de otro caso (ver GENERIC_ACTOR_TERMS
    en el docstring del modulo)."""
    if actor_norm in GENERIC_ACTOR_TERMS:
        return f"{actor_norm}::{case_id}"
    return actor_norm


def load_rows(conn: sqlite3.Connection, view: str) -> list[dict]:
    placeholders = ",".join("?" for _ in ACTOR_SOURCE_TABLES)
    rows = conn.execute(
        f"""
        SELECT l.document_id, l.nombre, p.case_id, l.source_table,
               CASE
                   WHEN l.source_table = 'enrichment_institution' THEN 1
                   WHEN l.source_table = 'enrichment_actor' AND ea.tipo IN ({",".join("?" for _ in INSTITUTIONAL_ACTOR_TIPOS)}) THEN 1
                   WHEN l.source_table = 'enrichment_actor' THEN 0
                   ELSE NULL
               END AS es_institucional
        FROM {view} l
        JOIN project p ON p.project_id = l.project_id
        LEFT JOIN enrichment_actor ea
            ON l.source_table = 'enrichment_actor' AND ea.actor_id = l.source_id
        WHERE l.source_table IN ({placeholders})
        """,
        (*INSTITUTIONAL_ACTOR_TIPOS, *ACTOR_SOURCE_TABLES),
    ).fetchall()
    return [
        {"document_id": r[0], "nombre": r[1], "case_id": r[2], "source_table": r[3], "es_institucional": r[4]}
        for r in rows
    ]


def _annotate(rows: list[dict]) -> list[dict]:
    """Agrega actor_norm (identidad cruda) y actor_scoped (identidad
    usada como nodo, con anclaje de contexto para terminos genericos)."""
    out = []
    for row in rows:
        actor_norm = normalize_actor_name(row["nombre"])
        if not actor_norm:
            continue
        out.append({**row, "actor_norm": actor_norm, "actor_scoped": scope_actor_id(actor_norm, row["case_id"])})
    return out


def _node_metadata(rows: list[dict]) -> dict[str, dict]:
    """actor_scoped -> {label, es_institucional} agregando votos por nodo."""
    display_labels: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    institutional_votes: dict[str, dict] = defaultdict(lambda: {0: 0, 1: 0})
    for row in rows:
        node = row["actor_scoped"]
        display_labels[node][row["nombre"].strip()] += 1
        if row["es_institucional"] is not None:
            institutional_votes[node][row["es_institucional"]] += 1

    meta = {}
    for node, labels in display_labels.items():
        label = max(labels.items(), key=lambda kv: kv[1])[0]
        votes = institutional_votes.get(node)
        if not votes or (votes[0] == 0 and votes[1] == 0):
            es_institucional = None
        else:
            es_institucional = votes[1] >= votes[0]
        meta[node] = {"label": label, "es_institucional": es_institucional}
    return meta


def build_document_cooccurrence_network(rows: list[dict]) -> nx.Graph:
    """Arista = 2 actores mencionados en el MISMO documento. Peso = numero
    de documentos distintos en que ese par co-aparece. Se agrupa
    directamente por document_id (no por interseccion de sets de
    documentos), asi que no puede reproducir el bug union/interseccion de
    la v1: la unidad de agrupacion YA es el documento."""
    meta = _node_metadata(rows)
    graph = nx.Graph()
    for node, m in meta.items():
        graph.add_node(node, **m)

    actors_by_doc: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        actors_by_doc[row["document_id"]].add(row["actor_scoped"])

    for doc_id, actors in actors_by_doc.items():
        if len(actors) < 2:
            continue
        for a, b in combinations(sorted(actors), 2):
            if graph.has_edge(a, b):
                graph[a][b]["weight"] += 1
                graph[a][b]["documentos"].append(doc_id)
            else:
                graph.add_edge(a, b, weight=1, documentos=[doc_id])

    return graph


def build_case_comembership_network(rows: list[dict]) -> nx.Graph:
    """Arista = 2 actores asociados al mismo case_id (sin exigir que
    compartan documento). Peso = numero de casos que aportan la arista
    (relacion de copertenencia a arena de conflicto compartida, NO de
    coocurrencia documental -- ver docstring del modulo, punto 1)."""
    meta = _node_metadata(rows)
    graph = nx.Graph()
    for node, m in meta.items():
        graph.add_node(node, **m)

    actors_by_case: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        actors_by_case[row["case_id"]].add(row["actor_scoped"])

    for case_id, actors in actors_by_case.items():
        if len(actors) < 2:
            continue
        for a, b in combinations(sorted(actors), 2):
            if graph.has_edge(a, b):
                graph[a][b]["n_casos_soporte"] += 1
                graph[a][b]["casos"].append(case_id)
            else:
                graph.add_edge(a, b, n_casos_soporte=1, casos=[case_id])

    return graph


def build_bipartite_actor_case(rows: list[dict]) -> nx.Graph:
    """Red bipartita actor <-> caso (objeto primario recomendado por
    la revisión): evita la explosion de clique N(N-1)/2 de las redes actor-actor
    y responde directamente 'en cuantos casos aparece este actor' /
    'que actores conectan casos distintos' (multiafiliacion)."""
    meta = _node_metadata(rows)
    graph = nx.Graph()
    for node, m in meta.items():
        graph.add_node(node, tipo="actor", **m)

    docs_by_actor_case: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        docs_by_actor_case[(row["actor_scoped"], row["case_id"])].add(row["document_id"])

    for (actor_node, case_id), docs in docs_by_actor_case.items():
        if not graph.has_node(case_id):
            graph.add_node(case_id, tipo="caso")
        graph.add_edge(actor_node, case_id, n_documentos=len(docs))

    return graph


def actor_nodes(graph: nx.Graph) -> list[str]:
    return [n for n, d in graph.nodes(data=True) if d.get("tipo") == "actor"]


def summarize_bipartite(graph: nx.Graph, rows: list[dict]) -> dict:
    actors = actor_nodes(graph)
    n_casos_por_actor = {a: graph.degree(a) for a in actors}
    top_multiafiliacion = sorted(
        ((graph.nodes[a]["label"], n) for a, n in n_casos_por_actor.items()),
        key=lambda kv: kv[1],
        reverse=True,
    )[:15]

    n_institucionales = sum(1 for a in actors if graph.nodes[a]["es_institucional"] is True)
    n_no_institucionales = sum(1 for a in actors if graph.nodes[a]["es_institucional"] is False)
    n_sin_clasificar = len(actors) - n_institucionales - n_no_institucionales

    docs_per_case: dict[str, set] = defaultdict(set)
    actors_by_case: dict[str, set] = defaultdict(set)
    for row in rows:
        actors_by_case[row["case_id"]].add(row["actor_scoped"])
        docs_per_case[row["case_id"]].add(row["document_id"])
    actors_per_case_list = [len(v) for v in actors_by_case.values()]
    docs_per_case_list = [len(v) for v in docs_per_case.values()]

    return {
        "n_actores_nodos": len(actors),
        "n_casos_nodos": graph.number_of_nodes() - len(actors),
        "n_actor_case_links": graph.number_of_edges(),
        "n_documentos_unicos": len({r["document_id"] for r in rows}),
        "n_casos_unicos": len({r["case_id"] for r in rows}),
        "actores_por_caso_mediana": round(statistics.median(actors_per_case_list), 1) if actors_per_case_list else 0,
        "actores_por_caso_p90": (
            round(statistics.quantiles(actors_per_case_list, n=10)[8], 1) if len(actors_per_case_list) >= 10 else max(actors_per_case_list, default=0)
        ),
        "actores_por_caso_max": max(actors_per_case_list, default=0),
        "documentos_por_caso_mediana": round(statistics.median(docs_per_case_list), 1) if docs_per_case_list else 0,
        "n_actores_institucionales": n_institucionales,
        "n_actores_no_institucionales": n_no_institucionales,
        "n_actores_sin_clasificar_institucional": n_sin_clasificar,
        "actores_mas_multiafiliados_por_n_casos": [{"actor": label, "n_casos": n} for label, n in top_multiafiliacion],
        "nota_centralidad": (
            "n_casos (grado en la bipartita) es multiafiliacion real: en cuantos "
            "casos distintos aparece el actor. Es mas interpretable que el grado "
            "bruto de una proyeccion actor-actor, que se infla artificialmente en "
            "casos con muchos actores (clique de tamano N genera N(N-1)/2 aristas "
            "sin que ningun par haya interactuado directamente)."
        ),
    }


def summarize_projection(graph: nx.Graph, weight_key: str) -> dict:
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    top_actors = sorted(
        ((graph.nodes[n]["label"], graph.degree(n)) for n in graph.nodes),
        key=lambda kv: kv[1],
        reverse=True,
    )[:15]
    largest_cc_nodes = components[0] if components else set()

    n_institucionales = sum(1 for n in graph.nodes if graph.nodes[n]["es_institucional"] is True)
    n_no_institucionales = sum(1 for n in graph.nodes if graph.nodes[n]["es_institucional"] is False)
    n_sin_clasificar = n_nodes - n_institucionales - n_no_institucionales

    return {
        "n_actores_nodos": n_nodes,
        "n_aristas": n_edges,
        "densidad": round(nx.density(graph), 5) if n_nodes > 1 else 0.0,
        "n_componentes_conexas": len(components),
        "tamano_componente_mayor": len(largest_cc_nodes),
        "pct_actores_en_componente_mayor": round(100 * len(largest_cc_nodes) / n_nodes, 1) if n_nodes else 0.0,
        "distribucion_tamano_componentes_top10": [len(c) for c in components[:10]],
        "actores_mas_conectados_por_grado_bruto": [{"actor": label, "grado": deg} for label, deg in top_actors],
        "n_actores_institucionales": n_institucionales,
        "n_actores_no_institucionales": n_no_institucionales,
        "n_actores_sin_clasificar_institucional": n_sin_clasificar,
    }


def network_excluding_confirmed_institutions(graph: nx.Graph) -> nx.Graph:
    """OJO: excluye SOLO nodos con es_institucional is True. False y None
    (sin clasificar) permanecen -- por eso el nombre no dice 'sin
    instituciones' sino 'excluyendo confirmados institucionales'. Con la
    clasificacion actual, 25.5% (conservadora) / 17.2% (inclusiva) de los
    nodos quedan sin clasificar y pueden incluir instituciones reales no
    detectadas (ej. 'Estado', tipo='otro' en la fuente)."""
    keep = [n for n in graph.nodes if graph.nodes[n]["es_institucional"] is not True]
    return graph.subgraph(keep).copy()


def rank_correlation_common_actors(bip_a: nx.Graph, bip_b: nx.Graph) -> dict:
    """Spearman entre n_casos(actor) en conservadora vs inclusiva, SOLO
    sobre actores presentes en ambas redes -- aisla si la version
    inclusiva reordena a los mismos actores, en vez de solo agregar
    actores nuevos que inflan el top-N por volumen."""
    actors_a = {n for n in actor_nodes(bip_a)}
    actors_b = {n for n in actor_nodes(bip_b)}
    common = sorted(actors_a & actors_b)
    if len(common) < 3:
        return {"n_actores_comunes": len(common), "spearman_rho": None, "spearman_p": None}

    ranks_a = [bip_a.degree(n) for n in common]
    ranks_b = [bip_b.degree(n) for n in common]
    rho, p = spearmanr(ranks_a, ranks_b)
    return {
        "n_actores_comunes": len(common),
        "spearman_rho": round(float(rho), 3),
        "spearman_p": round(float(p), 5),
        "nota": (
            "rho cercano a 1 = los mismos actores mantienen su orden relativo "
            "de multiafiliacion al pasar de conservadora a inclusiva (la version "
            "inclusiva solo agrega volumen). rho bajo = la version inclusiva "
            "reordena la importancia relativa incluso entre actores que ya "
            "estaban en la conservadora."
        ),
    }


def top15_overlap(proj_a: dict, proj_b: dict) -> dict:
    top_a = {d["actor"] for d in proj_a["actores_mas_conectados_por_grado_bruto"]}
    top_b = {d["actor"] for d in proj_b["actores_mas_conectados_por_grado_bruto"]}
    return {
        "solo_en_conservadora": sorted(top_a - top_b),
        "solo_en_inclusiva": sorted(top_b - top_a),
        "en_ambas": sorted(top_a & top_b),
    }


def main():
    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")

    data = {}
    for label, view in VIEWS.items():
        rows = _annotate(load_rows(conn, view))

        bip = build_bipartite_actor_case(rows)
        doc_cooc = build_document_cooccurrence_network(rows)
        case_comembership = build_case_comembership_network(rows)
        case_comembership_excl_inst = network_excluding_confirmed_institutions(case_comembership)

        data[label] = {
            "rows": rows,
            "bipartite": bip,
            "bipartite_summary": summarize_bipartite(bip, rows),
            "doc_cooccurrence_summary": summarize_projection(doc_cooc, "weight"),
            "case_comembership_summary": summarize_projection(case_comembership, "n_casos_soporte"),
            "case_comembership_excl_inst_summary": summarize_projection(case_comembership_excl_inst, "n_casos_soporte"),
        }
        b = data[label]["bipartite_summary"]
        print(f"[{label}] bipartita: {b['n_actores_nodos']} actores, {b['n_casos_nodos']} casos, "
              f"{b['n_actor_case_links']} links; actores_por_caso_mediana={b['actores_por_caso_mediana']}")

    comparacion = {
        "top15_doc_cooccurrence": top15_overlap(
            data["conservadora"]["doc_cooccurrence_summary"], data["inclusiva"]["doc_cooccurrence_summary"]
        ),
        "top15_case_comembership": top15_overlap(
            data["conservadora"]["case_comembership_summary"], data["inclusiva"]["case_comembership_summary"]
        ),
        "correlacion_multiafiliacion_actores_comunes": rank_correlation_common_actors(
            data["conservadora"]["bipartite"], data["inclusiva"]["bipartite"]
        ),
        "nota": (
            "La correlacion de multiafiliacion se calcula SOLO sobre actores "
            "presentes en ambas versiones (bipartita conservadora ∩ inclusiva). "
            "Los conteos brutos de nodos/aristas de cada red completa no son "
            "comparables 1 a 1 porque la version inclusiva incorpora "
            "documentos/casos que la conservadora excluye por diseno -- ver "
            "n_documentos_unicos / n_casos_unicos en cada bloque."
        ),
    }

    output = {
        "fuente": str(WAREHOUSE.relative_to(PROJECT_ROOT)),
        "version": "v2 (correccion tras revision externa, 2026-09-18)",
        "definicion_bipartita": "actor <-> case_id; arista = actor mencionado en ese caso, con n_documentos de soporte",
        "definicion_doc_cooccurrence": "2 actores mencionados en el MISMO documento; peso = n documentos distintos donde co-aparecen (interseccion real, agrupado por document_id)",
        "definicion_case_comembership": "2 actores asociados al mismo case_id (clique por caso); NO implica que compartieran un documento -- es copertenencia a la misma arena de conflicto, no coocurrencia",
        "nota_identidad_actor": (
            "Nodo = nombre normalizado (lower + espacios colapsados), salvo "
            "terminos genericos en GENERIC_ACTOR_TERMS que se anclan a su "
            "case_id ('la inmobiliaria::<case_id>') para no fusionar entidades "
            "distintas entre casos. Sigue sin resolverse identidad global via "
            "entity_actor_crosswalk (cobertura ~45%); variantes como 'Servicio "
            "de Evaluacion Ambiental' / '... (SEA)' siguen siendo nodos "
            "distintos."
        ),
        "nota_institucional": (
            "'excluyendo_confirmados_institucionales' excluye SOLO nodos con "
            "es_institucional=True. La clasificacion es parcial: "
            "n_actores_sin_clasificar_institucional queda explicito en cada "
            "bloque para no subestimar cuanto del resultado depende de una "
            "taxonomia todavia incompleta."
        ),
        "conservadora": {k: v for k, v in data["conservadora"].items() if k != "rows" and k != "bipartite"},
        "inclusiva": {k: v for k, v in data["inclusiva"].items() if k != "rows" and k != "bipartite"},
        "comparacion": comparacion,
    }
    for label in ("conservadora", "inclusiva"):
        output[label]["vista_sql"] = VIEWS[label]

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEscrito: {OUTPUT.relative_to(PROJECT_ROOT)}")

    conn.close()
    return output


if __name__ == "__main__":
    main()
