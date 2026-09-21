#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Puente documento -> caso/proyecto -> actor/evento/evidencia.

Hallazgo real (la auditoría, 2026-09-17): ningun actor/institucion/evento del
warehouse tiene una identidad de PROYECTO estable entre documentos --
`proyecto_asociado` es una cadena cruda que solo tiene sentido DENTRO del
mismo documento (comparada contra `proyectos_mencionados` de ESE
documento). Dos articulos que mencionan "el mismo" proyecto con redaccion
distinta ("Torre Bellavista" vs "torre Bellavista") no tienen ningun vinculo
hoy. Ademas ya existen 3 capas de "actor" desconectadas en el warehouse
(entity/entity_role de Fase B-clasificacion, enrichment_actor_v3_2 de la
primera pasada v3.2, y actor_second_pass_v2 que ni siquiera esta en el
warehouse) mas una tabla `event` vestigial de un piloto de 11 documentos
(build_event_table_v1.py) -- este script NO intenta reconciliar esas 3
capas (son de granularidad y epoca distintas, un proyecto de reconciliacion
aparte); construye el puente sobre la capa v3.2 + actor_second_pass_v2,
que es la que va a alimentar el analisis de redes de Dario.

Verificado antes de disenar (no supuesto): 1405 menciones de proyecto en
934 documentos, 997 grupos unicos tras normalizar, 47 grupos donde la
normalizacion junta variantes reales de escritura (mayusculas, prefijos
"proyecto"/"edificio", guionado). 280/934 documentos (30%) mencionan 2+
proyectos -- la ambiguedad de asociacion es real y frecuente, no un caso
raro.

Reglas de resolucion, deliberadamente conservadoras ("no quiero llevarme
otra sorpresa"):

1. Dos menciones de proyecto se fusionan en el MISMO project_id SOLO si su
   nombre normalizado (acentos/mayusculas/articulos/puntuacion removidos)
   es IDENTICO. Nunca se fusiona por similitud parcial/substring entre
   documentos distintos -- "Torre Central" en dos comunas distintas podrian
   ser dos edificios diferentes, y una fusion erronea contaminaria
   silenciosamente una red de actores.
2. Pares de projects_id DISTINTOS cuyo nombre normalizado tiene una
   relacion de substring (candidato a ser el mismo proyecto escrito de
   forma muy distinta) se registran en `project_review_queue` para
   revision humana -- NUNCA se fusionan automaticamente.
3. La asociacion de un actor/institucion/evento a un project_id sigue esta
   prioridad, y CADA registro queda con un `resolution_status` explicito
   (nunca silencioso):
   - `resolved_explicit`: proyecto_asociado no vacio y coincide con una
     mencion de proyecto de ESE documento (ya validado rio arriba por
     sanitize_project_associations()).
   - `inferred_single_project` [RENOMBRADO 2026-09-18, hallazgo de la revisión,
     antes "resolved_single_project" -- ver resolve_association() para el
     caso real que motivo el cambio de nombre]: proyecto_asociado vacio,
     pero el documento menciona exactamente 1 proyecto -- sin ambiguedad
     de CUANTOS proyectos hay, pero SIN garantia de que el actor/evento
     realmente pertenezca a ese proyecto (puede ser una mencion
     comparativa/contextual). No tratar como equivalente a
     resolved_explicit.
   - `unresolved_ambiguous`: proyecto_asociado vacio Y el documento
     menciona 2+ proyectos -- NO se puede saber a cuál se refiere. La revisión lo
     anticipo: "las asociaciones no resolubles quedan explicitamente sin
     adjudicar", no se inventa un valor.
   - `unresolved_no_project`: el documento no menciona ningun proyecto con
     nombre propio.

No llama a la API. Copia warehouse_v3_2.sqlite a un archivo NUEVO
(warehouse_v3_2_bridge.sqlite) y agrega las tablas del puente ahi.

[ACTUALIZADO 2026-09-18, precision pedida por la revisión] warehouse_v3_2.sqlite
(sellado como produccion_completa) ya NO es estrictamente "nunca se
modifica en el lugar" -- apply_sol_document_corrections.py le agrega la
tabla document_unidad_caso_sol (gate documento->unidad_de_caso). La
garantia real, mas precisa, es: las tablas de ENRICHMENT ORIGINALES
(enrichment_document_v3_2 y las demas) permanecen inmutables siempre; se
permiten tablas NUEVAS de auditoria/gobernanza (append-only a nivel de
esquema, nunca se borra ni edita una columna existente de una tabla de
enrichment). Mismo patron que build_enrichment_tables_v3_2.py con
warehouse_v1, adaptado a este matiz.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_WAREHOUSE = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2.sqlite"
OUTPUT_WAREHOUSE = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2_bridge.sqlite"
ENRICHMENT_PATH = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_2_934" / "enrichment.jsonl"
ACTOR_SECOND_PASS_PATH = PROJECT_ROOT / "Auditoria" / "enriquecimiento_v3_2_934" / "actor_second_pass_v2" / "actor_second_pass_v2.jsonl"

STOPWORDS = {"el", "la", "los", "las", "de", "del", "un", "una", "y", "en", "a", "proyecto", "edificio"}


def normalize_project_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    n = re.sub(r"[^\w\s]", " ", n)
    tokens = [t for t in n.split() if t and t not in STOPWORDS]
    return " ".join(tokens)


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


# [AGREGADO 2026-09-18] Homonimos CONFIRMADOS donde el cluster EXACTO por
# nombre normalizado fusiono, sin pasar por project_review_queue (esa cola
# solo se activa entre project_id DISTINTOS con relacion de substring -- un
# match EXACTO nunca llega ahi), dos referencias reales distintas. Hallazgo
# de Claude al verificar el punto 8 de la segunda auditoría (riesgo
# de homonimos en el auto-merge exacto): "San Isidro" (bare) tenia 2
# menciones en 2 documentos -- una en "Las Rejas norte y calle Toro
# Mazotte, Estacion Central" (nada que ver con una planta de tratamiento) y
# otra en "norte de la comuna de Quilicura... Estero Las Cruces" (coherente
# con la Empresa San Isidro / planta de tratamiento de aguas servidas ya
# investigada en la cola de 253). document_id truncado a 16 caracteres por
# legibilidad -- ver KNOWN_HOMONYM_SPLITS para el valor completo.
KNOWN_HOMONYM_SPLITS: dict[tuple[str, str], str] = {
    ("san isidro", "e604fe1436ae5fdf514193a9ce8264613c475139ea396b0b4c2964391ddeffed"): "estacion_central_toro_mazotte",
    # [AGREGADO 2026-09-18, auditoria de los 150 clusters exactos multi-documento
    # pedida por la revisión tras el hallazgo San Isidro] "Costanera Center" (real,
    # Providencia) fusionaba con un documento sobre el proyecto de Cencosud
    # EN ARGENTINA (San Isidro, zona norte de Buenos Aires) -- ya identificado
    # antes como caso_focal_fuera_del_universo en la validacion humana de la revisión
    # (24% error_grave). Se separa esa unica mencion.
    ("costanera center", "894c62ee791c8af113381e6e77c84ac82f79acfb508bf3273172222ae992d7dc"): "cencosud_argentina",
    # "Plaza Egaña" fusionaba la interseccion real (Irarrazaval/Vespucio,
    # Ñuñoa/La Reina) con 2 documentos que ubican consistentemente un "Plaza
    # Egaña" distinto en Vitacura (paño de 25.000 m2, zona oriente) --
    # geograficamente incompatible con la interseccion real. Se separan esos
    # 2 documentos a un project_id propio.
    ("plaza egana", "7765d45503ecfb4d7ba4722549e1c0f4aa029faaede885bd06a0bb3318cedf00"): "vitacura_pano_25000m2",
    ("plaza egana", "a3fd98f337c6e4ca4b55164cd61f24618a020ad6d0f57ad4e1b58e71abb34160"): "vitacura_pano_25000m2",
}


def build_project_registry(enrichment_records: list[dict[str, Any]]) -> tuple[dict[str, dict], dict[tuple[str, str], str]]:
    """Devuelve (project_id -> info del proyecto, (document_id, raw_name) -> project_id).

    Cluster EXACTO por nombre normalizado, nunca por similitud parcial
    entre documentos distintos (ver regla 1 del docstring del modulo).
    Excepcion explicita y documentada: KNOWN_HOMONYM_SPLITS fuerza un
    project_id distinto para menciones especificas ya verificadas como
    homonimos reales (ver comentario de esa constante)."""
    groups: dict[str, dict[str, Any]] = {}
    mention_to_project: dict[tuple[str, str], str] = {}

    for record in enrichment_records:
        document_id = record["document_id"]
        for raw_name in record.get("proyectos_mencionados") or []:
            raw_name = (raw_name or "").strip()
            if not raw_name:
                continue
            norm = normalize_project_name(raw_name)
            if not norm:
                continue
            split_suffix = KNOWN_HOMONYM_SPLITS.get((norm, document_id))
            group_key = f"{norm}::{split_suffix}" if split_suffix else norm
            group = groups.setdefault(group_key, {"aliases": {}, "documents": set(), "norm": norm})
            group["aliases"][raw_name] = group["aliases"].get(raw_name, 0) + 1
            group["documents"].add(document_id)
            mention_to_project[(document_id, raw_name)] = group_key

    # [AGREGADO 2026-09-18, hallazgo BLOQUEANTE de la revisión tras el split de
    # Costanera Center] separar un homonimo a nivel de project_id NO basta:
    # resolve_project_review_queue.py decide fusiones por NOMBRE (classify()
    # solo recibe strings), asi que las dos mitades de un mismo homonimo
    # ("Costanera Center" Chile y Argentina) podian volver a conectarse
    # transitivamente al pasar ambas por el MISMO par con nombre identico
    # ("Costanera Center" vs "mall Costanera Center" -> merged para las dos).
    # homonym_partition marca, para cada norm que participa en
    # KNOWN_HOMONYM_SPLITS, una particion distinta por group_key (el "resto"
    # sin sufijo cuenta como su propia particion) -- resolve_project_review_
    # queue.py usa esto para VETAR cualquier union entre dos project_id de
    # particiones distintas de un mismo homonimo, sin importar lo que diga
    # la decision por nombre.
    split_norms = {norm for (norm, _doc_id) in KNOWN_HOMONYM_SPLITS}

    projects: dict[str, dict[str, Any]] = {}
    for group_key, group in groups.items():
        project_id = _stable_id("project", group_key)
        canonical_name = max(group["aliases"].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        projects[project_id] = {
            "project_id": project_id,
            "canonical_name": canonical_name,
            "normalized_name": group["norm"],
            "aliases": sorted(group["aliases"].keys()),
            "n_documents": len(group["documents"]),
            "n_mentions": sum(group["aliases"].values()),
            "homonym_partition": group_key if group["norm"] in split_norms else None,
        }

    resolved_mention_to_project = {
        key: _stable_id("project", group_key) for key, group_key in mention_to_project.items()
    }
    return projects, resolved_mention_to_project


# [AGREGADO 2026-09-18] Pares de nombre de proyecto que la auditoria de
# los 63 documentos 'caso_unico' con >1 case_id (conflict_unit) probo con
# citas verificadas que son el mismo proyecto escrito de forma tan
# distinta que NO comparten substring alguno -- find_review_candidates()
# nunca los habria generado (verificado: ninguno de estos 5 pares existia
# antes en la cola de 255). La revisión los marcó project_relation='alias' dentro
# de relaciones_case_groups_sol al clasificar los 63 documentos; ver
# Auditoria/integracion_v1/candidatos_project_review_queue_desde_conflict_unit_63.json
# para la evidencia y provenance completos. Se agregan aqui como
# candidatos EXTRA (no se fusionan solos -- la decision merged/kept_separate
# vive en resolve_project_review_queue.py::MANUAL_DECISIONS, igual que el
# resto de la cola).
MANUAL_EXTRA_REVIEW_PAIRS: list[tuple[str, str, str]] = [
    ("Villa San Luis", "Villa Carlos Cortés", "conflict_unit_63_sol_alias"),
    (
        "Club de Golf Hacienda Santa Martina Nature - Lo Barnechea",
        "Hacienda Santa Martina, Nature Club & Golf",
        "conflict_unit_63_sol_alias",
    ),
    ("Egaña Eco Sustentable", "Eco Egaña", "conflict_unit_63_sol_alias"),
    (
        "LA PLANTA DE CACA",
        "Solución transitoria para la provisión de los servicios de tratamiento y disposición de Aguas Servidas",
        "conflict_unit_63_sol_alias",
    ),
    ("Alto Las Condes 2", "Alto Norte", "conflict_unit_63_sol_alias"),
]


def find_review_candidates(projects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Pares de project_id DISTINTOS cuyo nombre normalizado tiene relacion
    de substring -- candidatos a ser el mismo proyecto escrito muy
    distinto. Se registran para revision humana, NUNCA se fusionan."""
    items = [(pid, info["normalized_name"]) for pid, info in projects.items() if len(info["normalized_name"]) >= 6]
    candidates = []
    for i, (pid_a, norm_a) in enumerate(items):
        for pid_b, norm_b in items[i + 1:]:
            if norm_a == norm_b:
                continue
            if norm_a in norm_b or norm_b in norm_a:
                candidates.append({
                    "project_id_a": pid_a,
                    "canonical_name_a": projects[pid_a]["canonical_name"],
                    "project_id_b": pid_b,
                    "canonical_name_b": projects[pid_b]["canonical_name"],
                    "reason": "substring_match_not_auto_merged",
                })

    # [ENDURECIDO 2026-09-18, fragilidad senalada por la revisión] name_to_pid
    # mapeaba con setdefault() -- si 2 project_id distintos tuvieran
    # exactamente el mismo canonical_name (ej. un homonimo particionado
    # cuyo lado veto no cambio el nombre visible), el primero encontrado
    # ganaba en silencio y el par manual podia apuntar al project_id
    # equivocado sin que nada lo avisara. Ahora se mapea a una LISTA de
    # pid por nombre y, si un nombre de MANUAL_EXTRA_REVIEW_PAIRS resulta
    # ambiguo (2+ project_id con el mismo canonical_name), se levanta un
    # error explicito en vez de elegir uno al azar -- no ocurre hoy con
    # los 5 pares reales (verificado por test de regresion), pero deja de
    # depender de que nunca ocurra en el futuro.
    name_to_pids: dict[str, list[str]] = defaultdict(list)
    for pid, info in projects.items():
        name_to_pids[info["canonical_name"]].append(pid)
    existing_pairs = {frozenset((c["canonical_name_a"], c["canonical_name_b"])) for c in candidates}
    for name_a, name_b, reason in MANUAL_EXTRA_REVIEW_PAIRS:
        pids_a, pids_b = name_to_pids.get(name_a), name_to_pids.get(name_b)
        if not pids_a or not pids_b:
            # No es un error: el registro de proyectos que llega aqui puede
            # ser un fixture sintetico de test, o el corpus real puede haber
            # cambiado (la revisión corrige nombres, se re-normaliza, etc). No
            # bloquear la construccion del puente por un par manual que ya
            # no aplica -- si el par real deja de aparecer en la cola sin
            # que nadie se entere, eso lo protege un test de regresion
            # separado contra el warehouse real, no esta funcion generica.
            continue
        if len(pids_a) > 1 or len(pids_b) > 1:
            raise ValueError(
                f"MANUAL_EXTRA_REVIEW_PAIRS: nombre ambiguo -- '{name_a}' resuelve a "
                f"{pids_a} y '{name_b}' resuelve a {pids_b}. Un canonical_name debe "
                "mapear a un unico project_id para que este par manual sea seguro; "
                "revisar homonimos antes de continuar."
            )
        pid_a, pid_b = pids_a[0], pids_b[0]
        if frozenset((name_a, name_b)) in existing_pairs:
            continue  # ya cubierto por substring match, no duplicar
        candidates.append({
            "project_id_a": pid_a,
            "canonical_name_a": name_a,
            "project_id_b": pid_b,
            "canonical_name_b": name_b,
            "reason": reason,
        })
    return candidates


def resolve_association(document_id: str, proyecto_asociado_raw: str, doc_project_ids: set[str], mention_lookup: dict[tuple[str, str], str]) -> tuple[str | None, str]:
    proyecto_asociado_raw = (proyecto_asociado_raw or "").strip()
    if proyecto_asociado_raw:
        project_id = mention_lookup.get((document_id, proyecto_asociado_raw))
        if project_id:
            return project_id, "resolved_explicit"
        # proyecto_asociado no vacio pero no matchea ninguna mencion conocida
        # de este documento -- no deberia pasar tras sanitize_project_associations(),
        # pero si pasa, no se adjudica en silencio.
        return None, "unresolved_inconsistent_association"
    if len(doc_project_ids) == 1:
        # [CORRECCION 2026-09-18, hallazgo de la revisión] este estado se llamaba
        # "resolved_single_project", nombre que sugiere certeza equivalente a
        # resolved_explicit. No lo es: solo significa que el documento
        # menciona un unico proyecto con nombre propio, NO que ese
        # actor/institucion/evento pertenezca realmente a el. Caso real
        # encontrado por la revisión y verificado por Claude: un articulo sobre
        # megaedificios de Estacion Central termina asociando la "Direccion
        # de Obras de Estacion Central" al proyecto "Costanera Center"
        # (Providencia) solo porque esa fue la unica mencion de proyecto
        # que la extraccion capturo en ese documento -- la misma familia de
        # error que la validacion humana de la revisión encontro en 24% de una
        # muestra de 50 documentos (documentos panoramicos/comparativos,
        # ejemplos capturados como si fueran el caso focal). Renombrado a
        # "inferred_single_project" para que el nombre no prometa mas
        # certeza de la que el dato realmente tiene -- NO tratar como
        # equivalente a resolved_explicit en un analisis de redes sin pasar
        # antes por el gate documento->unidad_de_caso (pendiente de decision
        # del equipo, ver plan_arcos_analiticos_stage_2.md).
        return next(iter(doc_project_ids)), "inferred_single_project"
    if len(doc_project_ids) == 0:
        return None, "unresolved_no_project"
    return None, "unresolved_ambiguous"


def main() -> int:
    enrichment_records = [
        json.loads(l) for l in ENRICHMENT_PATH.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    actor_second_pass_records = [
        json.loads(l) for l in ACTOR_SECOND_PASS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()
    ] if ACTOR_SECOND_PASS_PATH.exists() else []

    OUTPUT_WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_WAREHOUSE, OUTPUT_WAREHOUSE)
    conn = sqlite3.connect(OUTPUT_WAREHOUSE)

    url_to_document_id = {
        row[1]: row[0] for row in conn.execute("SELECT document_id, url FROM document").fetchall()
    }

    # Adjuntar document_id a cada registro de enrichment (via url -> warehouse.document)
    for r in enrichment_records:
        r["document_id"] = url_to_document_id.get(r["url"])
    enrichment_records = [r for r in enrichment_records if r["document_id"]]

    # [AGREGADO 2026-09-18] gate documento->unidad_de_caso: la revisión reviso los
    # 934/934 documentos y encontro 9 con proyectos_mencionados mal
    # extraidos (comunidades/actores confundidos con proyecto, casos
    # comparativos capturados como focal). Se sobrescribe SOLO
    # proyectos_mencionados donde la revisión dejo una correccion explicita
    # (correccion_proyectos_mencionados_json IS NOT NULL) -- el original
    # nunca se toca en document_unidad_caso_sol, solo se usa aqui una copia
    # en memoria para construir el registro de proyectos. Sin correccion
    # explicita, el documento usa su proyectos_mencionados original tal
    # cual (la ausencia de correccion NO implica que el documento sea
    # caso_unico -- unidad_caso_tipo se propaga aparte, sin filtrar nada
    # aqui, para que el consumidor final decida si excluye documentos
    # documento_comparativo_panoramico/contexto_sin_caso_individualizable/
    # caso_focal_fuera_del_universo de su analisis).
    sol_corrections: dict[str, dict] = {}
    if SOURCE_WAREHOUSE.exists():
        conn_check = sqlite3.connect(SOURCE_WAREHOUSE)
        has_table = conn_check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_unidad_caso_sol'"
        ).fetchone()
        if has_table:
            # [ACTUALIZADO 2026-09-18, hallazgo de la revisión] la consulta anterior
            # NUNCA leia correccion_nombre_proyecto -- este script decia
            # "usa las correcciones de la revisión" sin precisar que solo aplicaba
            # las de proyectos_mencionados. Se agrega aqui para que quede
            # registrada y visible en el summary, aunque -- por diseno, no
            # por descuido -- NO se usa para alterar el registro de
            # proyectos: nombre_proyecto ("caso/proyecto focal del
            # documento") y proyectos_mencionados ("cualquier proyecto
            # realmente mencionado") son dos conceptos distintos (la revisión lo
            # aclaro explicitamente); el registro de proyectos siempre fue
            # mention-based, nunca focal-based, asi que no corresponde
            # sobreescribir una mencion real solo porque el documento no
            # tiene caso focal univoco. Quien necesite el nombre_proyecto
            # corregido (el caso focal) debe leerlo de
            # document_unidad_caso_sol directamente, no de este registry.
            for row in conn_check.execute(
                "SELECT document_id, unidad_caso_tipo, tiene_error, correccion_proyectos_mencionados_json, "
                "correccion_nombre_proyecto "
                "FROM document_unidad_caso_sol"
            ).fetchall():
                document_id, unidad_caso_tipo, tiene_error, corr_menc_json, corr_nombre = row
                sol_corrections[document_id] = {
                    "unidad_caso_tipo": unidad_caso_tipo,
                    "tiene_error": bool(tiene_error),
                    "proyectos_mencionados_corregido": json.loads(corr_menc_json) if corr_menc_json is not None else None,
                    "nombre_proyecto_corregido": corr_nombre,
                }
        conn_check.close()

    n_docs_con_correccion_de_menciones = 0
    n_docs_con_correccion_de_nombre_no_aplicada_al_registry = sum(
        1 for c in sol_corrections.values() if c["nombre_proyecto_corregido"] is not None
    )
    for r in enrichment_records:
        corr = sol_corrections.get(r["document_id"])
        if corr and corr["proyectos_mencionados_corregido"] is not None:
            r["proyectos_mencionados"] = corr["proyectos_mencionados_corregido"]
            n_docs_con_correccion_de_menciones += 1

    projects, mention_lookup = build_project_registry(enrichment_records)
    review_candidates = find_review_candidates(projects)

    conn.executescript("""
        DROP TABLE IF EXISTS project;
        DROP TABLE IF EXISTS project_mention_resolved;
        DROP TABLE IF EXISTS project_review_queue;
        DROP TABLE IF EXISTS actor_event_project_link;

        CREATE TABLE project (
            project_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            n_documents INTEGER NOT NULL,
            n_mentions INTEGER NOT NULL,
            homonym_partition TEXT
        );
        CREATE TABLE project_mention_resolved (
            document_id TEXT NOT NULL REFERENCES document(document_id),
            raw_nombre_proyecto TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES project(project_id)
        );
        CREATE TABLE project_review_queue (
            project_id_a TEXT NOT NULL,
            canonical_name_a TEXT NOT NULL,
            project_id_b TEXT NOT NULL,
            canonical_name_b TEXT NOT NULL,
            reason TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE actor_event_project_link (
            link_id TEXT PRIMARY KEY,
            source_table TEXT NOT NULL,
            source_id TEXT,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            nombre TEXT NOT NULL,
            proyecto_asociado_raw TEXT,
            project_id TEXT REFERENCES project(project_id),
            resolution_status TEXT NOT NULL,
            source_pass TEXT NOT NULL
        );
    """)

    conn.executemany(
        "INSERT INTO project (project_id, canonical_name, normalized_name, aliases_json, n_documents, n_mentions, homonym_partition) VALUES (?,?,?,?,?,?,?)",
        [
            (p["project_id"], p["canonical_name"], p["normalized_name"], json.dumps(p["aliases"], ensure_ascii=False), p["n_documents"], p["n_mentions"], p["homonym_partition"])
            for p in projects.values()
        ],
    )
    conn.executemany(
        "INSERT INTO project_mention_resolved (document_id, raw_nombre_proyecto, project_id) VALUES (?,?,?)",
        [(doc_id, raw, pid) for (doc_id, raw), pid in mention_lookup.items()],
    )
    conn.executemany(
        "INSERT INTO project_review_queue (project_id_a, canonical_name_a, project_id_b, canonical_name_b, reason) VALUES (?,?,?,?,?)",
        [(c["project_id_a"], c["canonical_name_a"], c["project_id_b"], c["canonical_name_b"], c["reason"]) for c in review_candidates],
    )

    doc_project_ids: dict[str, set[str]] = {}
    for (doc_id, _raw), pid in mention_lookup.items():
        doc_project_ids.setdefault(doc_id, set()).add(pid)

    link_rows = []
    status_counts: dict[str, int] = {}

    def _add_link(source_table: str, source_id: str, document_id: str, nombre: str, proyecto_asociado_raw: str, source_pass: str) -> None:
        project_id, status = resolve_association(document_id, proyecto_asociado_raw, doc_project_ids.get(document_id, set()), mention_lookup)
        status_counts[status] = status_counts.get(status, 0) + 1
        link_rows.append((
            _stable_id("link", source_table, source_id or "", nombre, source_pass),
            source_table, source_id, document_id, nombre, proyecto_asociado_raw or "", project_id, status, source_pass,
        ))

    for table, id_col, label_col in (
        ("enrichment_actor_v3_2", "actor_id", "nombre"),
        ("enrichment_institucion_v3_2", "institucion_id", "nombre"),
        ("enrichment_evento_v3_2", "event_id", "descripcion"),
    ):
        for row in conn.execute(f"SELECT {id_col}, document_id, {label_col}, proyecto_asociado FROM {table}").fetchall():
            source_id, document_id, label, proyecto_asociado = row
            _add_link(table, source_id, document_id, label or "", proyecto_asociado or "", "first")

    # [CORRECCION 2026-09-18, hallazgo BLOQUEANTE de la revisión, segunda auditoria]
    # actores_final de actor_second_pass_v2 es POR DISENO la union A∪B de la
    # primera pasada (ya cargada arriba desde enrichment_actor_v3_2, con
    # source_pass="first") y la segunda pasada independiente -- incluye
    # filas con source_pass in {"first","both","second"}. Cargar TODAS esas
    # filas aqui duplicaba en actor_event_project_link cualquier actor que
    # ya existiera en la primera pasada (source_pass "first" o "both"): dos
    # filas para la MISMA relacion actor-documento sustantiva, con dos
    # source_id distintos. Sin filtrar esto, cualquier calculo de grado/peso
    # de aristas para la red de Dario quedaria inflado -- verificado: 3192 de
    # 5491 filas (58%) de actor_second_pass_v2 tenian source_pass in
    # ("first","both") antes de este fix. Correccion elegida (mas simple que
    # una tabla de deduplicacion explicita, sugerida como alternativa por
    # la revisión): incorporar de actores_final SOLO los actores con
    # source_pass=="second" -- los "first"/"both" ya estan representados,
    # con mejor procedencia, via la carga de enrichment_actor_v3_2 de arriba.
    for record in actor_second_pass_records:
        document_id = url_to_document_id.get(record["url"])
        if not document_id:
            continue
        for idx, actor in enumerate(record.get("actores_final") or []):
            if actor.get("source_pass", "second") != "second":
                continue
            source_id = _stable_id("actor_second_pass_v2", document_id, str(idx))
            _add_link("actor_second_pass_v2", source_id, document_id, actor.get("nombre", ""), actor.get("proyecto_asociado", ""), actor.get("source_pass", "second"))

    conn.executemany(
        "INSERT INTO actor_event_project_link (link_id, source_table, source_id, document_id, nombre, proyecto_asociado_raw, project_id, resolution_status, source_pass) VALUES (?,?,?,?,?,?,?,?,?)",
        link_rows,
    )
    conn.commit()

    # [AGREGADO 2026-09-18, pedido por la revisión] Sin esta vista, cualquier
    # consumidor (ej. Dario construyendo la red) que haga SELECT * FROM
    # actor_event_project_link sin JOIN a document_unidad_caso_sol obtiene
    # en silencio links de documentos panoramicos/contextuales/fuera de
    # universo -- el gate esta disponible pero nadie lo aplica salvo que se
    # acuerde de hacerlo a mano. Se materializan aqui 2 vistas con las reglas
    # ya explicitas, para no depender de que cada investigador recuerde el
    # filtro correcto cada vez:
    #   - actor_event_project_link_case_safe: el dataset conservador
    #     (unidad_caso_tipo='caso_unico' AND resolution_status=
    #     'resolved_explicit') -- solo vinculos donde el documento es
    #     inequivocamente un caso unico Y el actor/evento tenia
    #     proyecto_asociado explicito que coincide con la mencion.
    #     Sugerido por la revisión para partir el analisis de redes.
    #   - actor_event_project_link_include_inferred: version ampliada, agrega
    #     tambien inferred_single_project (single-mention, NO explicito --
    #     ver el renombre de esta ronda 3, sigue siendo una inferencia mas
    #     debil, usar con criterio de sensibilidad, no como caso base).
    # Si un documento no tiene fila en document_unidad_caso_sol (no debería
    # ocurrir para los 934, pero por robustez), la vista lo excluye por
    # defecto -- conservador ante datos faltantes, nunca incluye por omision.
    if sol_corrections:
        conn.executescript(
            """
            DROP VIEW IF EXISTS actor_event_project_link_case_safe;
            CREATE VIEW actor_event_project_link_case_safe AS
                SELECT l.*
                FROM actor_event_project_link l
                JOIN document_unidad_caso_sol g ON g.document_id = l.document_id
                WHERE g.unidad_caso_tipo = 'caso_unico'
                  AND l.resolution_status = 'resolved_explicit';

            DROP VIEW IF EXISTS actor_event_project_link_include_inferred;
            CREATE VIEW actor_event_project_link_include_inferred AS
                SELECT l.*
                FROM actor_event_project_link l
                JOIN document_unidad_caso_sol g ON g.document_id = l.document_id
                WHERE g.unidad_caso_tipo = 'caso_unico'
                  AND l.resolution_status IN ('resolved_explicit', 'inferred_single_project');
            """
        )
        conn.commit()
        n_links_case_safe = conn.execute("SELECT COUNT(*) FROM actor_event_project_link_case_safe").fetchone()[0]
        n_links_include_inferred = conn.execute("SELECT COUNT(*) FROM actor_event_project_link_include_inferred").fetchone()[0]
    else:
        n_links_case_safe = None
        n_links_include_inferred = None

    summary = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "output_warehouse": str(OUTPUT_WAREHOUSE.relative_to(PROJECT_ROOT)),
        "n_projects": len(projects),
        "n_project_mentions_resolved": len(mention_lookup),
        "n_review_candidates": len(review_candidates),
        "n_links_total": len(link_rows),
        "resolution_status_counts": status_counts,
        "vistas_analiticas": {
            "actor_event_project_link_case_safe": {
                "n_links": n_links_case_safe,
                "filtro": "unidad_caso_tipo='caso_unico' AND resolution_status='resolved_explicit'",
            },
            "actor_event_project_link_include_inferred": {
                "n_links": n_links_include_inferred,
                "filtro": "unidad_caso_tipo='caso_unico' AND resolution_status IN ('resolved_explicit','inferred_single_project')",
            },
        },
        "gate_documento_unidad_caso_sol": {
            "disponible": bool(sol_corrections),
            "n_documentos_con_gate": len(sol_corrections),
            "n_documentos_con_correccion_de_proyectos_mencionados_aplicada": n_docs_con_correccion_de_menciones,
            "n_documentos_con_correccion_de_nombre_proyecto_preservada_no_aplicada": n_docs_con_correccion_de_nombre_no_aplicada_al_registry,
            "unidad_caso_tipo_counts": (
                dict(Counter(c["unidad_caso_tipo"] for c in sol_corrections.values())) if sol_corrections else {}
            ),
            "nota": (
                "document_unidad_caso_sol (copiada de warehouse_v3_2.sqlite a esta base) trae la "
                "clasificacion de unidad de caso para los 934 documentos. [PRECISION 2026-09-18, "
                "se encontro que la frase anterior era imprecisa] Este script aplico las 9 correcciones "
                "de proyectos_mencionados al construir el registro de proyectos. Las 9 correcciones de "
                "nombre_proyecto NO se aplican aqui -- quedan preservadas y consultables en "
                "document_unidad_caso_sol.correccion_nombre_proyecto, pero el registro de proyectos "
                "siempre fue mention-based (recorre proyectos_mencionados), nunca focal-based, y los 2 "
                "conjuntos de 9 correcciones no son los mismos documentos (ver active-context.md). NO se "
                "excluye ningun documento por su unidad_caso_tipo -- si el analisis de redes quiere "
                "excluir documento_comparativo_panoramico/contexto_sin_caso_individualizable/caso_focal_"
                "fuera_del_universo, debe filtrar explicitamente usando esa tabla via document_id (ver "
                "tambien actor_event_project_link_case_safe, vista conservadora agregada para no "
                "depender de que cada consumidor recuerde el filtro correcto)."
            ),
        },
    }
    conn.close()

    summary_path = OUTPUT_WAREHOUSE.with_suffix(".build_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
