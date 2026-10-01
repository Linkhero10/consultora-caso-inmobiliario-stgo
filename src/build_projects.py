#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Puente documento -> caso/proyecto -> actor/evento/evidencia.

Ningun actor, institucion o evento tiene por si mismo una identidad de PROYECTO estable entre documentos:
`proyecto_asociado` es una cadena cruda que solo tiene sentido DENTRO del mismo documento (comparada contra
`proyectos_mencionados` de ESE documento). Dos articulos que mencionan "el mismo" proyecto con redaccion distinta
("Torre Bellavista" vs "torre Bellavista") no tienen ningun vinculo. Este script construye ese puente sobre las
tablas `enrichment_*`; no intenta reconciliar las otras capas de actor del warehouse (entity / entity_role de la
clasificacion), que tienen otra granularidad.

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
   - `inferred_single_project`: proyecto_asociado vacio,
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

No llama a la API. Copia warehouse_enrichment.sqlite (construido por build_enrichment_tables.py desde la
extraccion, ver src/enrichment_source.py) a data/warehouse.sqlite y agrega las tablas del puente ahi.

Garantia: las tablas de ENRICHMENT (enrichment_document y las demas) permanecen inmutables; se agregan tablas
NUEVAS de gobernanza (append-only a nivel de esquema, nunca se borra ni edita una columna de una tabla de
enrichment). `document_case_unit` (la revision de unidad de caso de cada documento, gate documento -> unidad de
caso) la carga build_enrichment_tables.py desde `config/document_case_unit_review.json`.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrichment_source import load_enrichment_records  # noqa: E402
from release_info import write_release_metadata  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
from paths import ENRICHMENT_DIR, ENRICHMENT_WAREHOUSE_PATH  # noqa: E402
SOURCE_WAREHOUSE = ENRICHMENT_WAREHOUSE_PATH
OUTPUT_WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
ACTOR_SECOND_PASS_PATH = ENRICHMENT_DIR / "actor_second_pass" / "actor_second_pass.jsonl"
DESCRIPTIVE_PROJECT_MENTIONS_CONFIG = PROJECT_ROOT / "config" / "descriptive_project_mentions.json"

STOPWORDS = {"el", "la", "los", "las", "de", "del", "un", "una", "y", "en", "a", "proyecto", "edificio"}


def normalize_project_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    # Un sufijo de letra pegado por guion a un numero ("Lote 18-A") es parte del rotulo: sin esto la
    # puntuacion lo separa y "a" cae como stopword, colapsando "Lote 18-A" con "Lote 18".
    n = re.sub(r"(?<=\d)-([a-z])(?![a-z])", r"\1", n)
    n = re.sub(r"[^\w\s]", " ", n)
    tokens = [t for t in n.split() if t and t not in STOPWORDS]
    return " ".join(tokens)


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def load_descriptive_project_mentions(
    conn: sqlite3.Connection, config_path: Path = DESCRIPTIVE_PROJECT_MENTIONS_CONFIG
) -> list[dict[str, Any]]:
    """Valida menciones descriptivas sustentadas sin resolver PROJECT.

    El contrato prohíbe campos de identidad de proyecto. Cada cita enlaza a
    evidencia verificada de la misma case_mention; las citas breves se
    verificaron contra el fulltext local al preparar el config (el fulltext no
    se versiona en el repositorio público).
    """
    config_path = Path(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if set(payload) != {"schema_version", "mentions"} or payload.get("schema_version") != "descriptive_project_mentions":
        raise ValueError("config de menciones descriptivas: schema_version/keys inválidos")
    if not isinstance(payload["mentions"], list):
        raise ValueError("config de menciones descriptivas: mentions debe ser una lista")

    allowed_fields = {
        "reference_key", "document_id", "case_mention_id", "subject_label",
        "descriptive_label", "identity_status", "source_url", "source_text_sha256",
        "source_file_path", "source_file_sha256", "citations", "linked_evidence_ids",
    }
    seen_keys: set[str] = set()
    prepared: list[dict[str, Any]] = []
    for item in payload["mentions"]:
        if set(item) != allowed_fields:
            raise ValueError(
                "config de mención descriptiva: campos inválidos; "
                f"extra={sorted(set(item) - allowed_fields)}, missing={sorted(allowed_fields - set(item))}"
            )
        key = item["reference_key"]
        if not isinstance(key, str) or not key.strip() or key in seen_keys:
            raise ValueError(f"reference_key vacío o duplicado: {key!r}")
        seen_keys.add(key)
        if item["identity_status"] != "descriptive_only_identity_unresolved":
            raise ValueError(f"identity_status no permitido en {key}: {item['identity_status']!r}")
        if any(not isinstance(item[field], str) or not item[field].strip() for field in (
            "document_id", "case_mention_id", "subject_label", "descriptive_label", "source_url"
        )):
            raise ValueError(f"campos descriptivos requeridos vacíos en {key}")
        if item["case_mention_id"].split(":", 1)[0] != item["document_id"]:
            raise ValueError(f"case_mention_id no pertenece al document_id en {key}")
        for hash_field in ("source_text_sha256", "source_file_sha256"):
            value = item[hash_field]
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"{hash_field} inválido en {key}")

        source_relpath = item["source_file_path"]
        if not isinstance(source_relpath, str) or not source_relpath.strip():
            raise ValueError(f"source_file_path vacío en {key}")
        relative_path = Path(source_relpath)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"source_file_path debe ser relativo y permanecer en el proyecto en {key}")
        project_root = PROJECT_ROOT.resolve()
        source_path = (project_root / relative_path).resolve()
        try:
            source_path.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(f"source_file_path escapa del directorio del proyecto en {key}") from exc
        if not source_path.is_file():
            raise FileNotFoundError(f"fulltext fuente requerido para validar {key}: {source_path}")
        source_bytes = source_path.read_bytes()
        observed_file_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if observed_file_sha256 != item["source_file_sha256"]:
            raise ValueError(f"source_file_sha256 no coincide con el fulltext en {key}")
        try:
            source_payload = json.loads(source_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"fulltext fuente no es JSON UTF-8 válido en {key}") from exc
        source_text = source_payload.get("text") if isinstance(source_payload, dict) else None
        if not isinstance(source_text, str):
            raise ValueError(f"fulltext fuente no contiene un campo text válido en {key}")
        if source_payload.get("url") != item["source_url"]:
            raise ValueError(f"URL del fulltext fuente no coincide con source_url en {key}")
        observed_text_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        if observed_text_sha256 != item["source_text_sha256"] or observed_text_sha256 != item["document_id"]:
            raise ValueError(f"source_text_sha256/document_id no coincide con el texto fuente en {key}")

        source = conn.execute(
            "SELECT url FROM document WHERE document_id = ?", (item["document_id"],)
        ).fetchone()
        if source is None or source[0] != item["source_url"]:
            raise ValueError(f"documento/URL fuente no coincide con el warehouse en {key}")
        case_mention = conn.execute(
            "SELECT document_id, decision_final_amplio FROM case_mention WHERE case_mention_id = ?",
            (item["case_mention_id"],),
        ).fetchone()
        if case_mention is None or case_mention[0] != item["document_id"]:
            raise ValueError(f"case_mention no pertenece al documento en {key}")
        if case_mention[1] != "include":
            raise ValueError(f"case_mention no está en estado include en {key}")

        citations = item["citations"]
        if not isinstance(citations, list) or not citations:
            raise ValueError(f"citas vacías en {key}")
        citation_evidence_ids: list[str] = []
        for citation in citations:
            if set(citation) != {"quote", "quote_sha256", "evidence_ids"}:
                raise ValueError(f"shape de cita inválido en {key}")
            quote = citation["quote"]
            quote_hash = citation["quote_sha256"]
            if not isinstance(quote, str) or not quote.strip():
                raise ValueError(f"cita vacía en {key}")
            if quote_hash != hashlib.sha256(quote.encode("utf-8")).hexdigest():
                raise ValueError(f"quote_sha256 no coincide en {key}")
            if quote not in source_text:
                raise ValueError(f"cita no aparece literalmente en el fulltext fuente en {key}")
            evidence_ids = citation["evidence_ids"]
            if not isinstance(evidence_ids, list) or not evidence_ids:
                raise ValueError(f"cita sin evidence_id en {key}")
            for evidence_id in evidence_ids:
                evidence = conn.execute(
                    "SELECT case_mention_id, verified, quote_text FROM evidence WHERE evidence_id = ?",
                    (evidence_id,),
                ).fetchone()
                if evidence is None or evidence[0] != item["case_mention_id"] or evidence[1] != 1:
                    raise ValueError(f"evidence_id no verificado o de otra case_mention en {key}: {evidence_id}")
                if evidence[2] not in quote:
                    raise ValueError(
                        f"cita no contiene literalmente evidence.quote_text en {key}: {evidence_id}"
                    )
                citation_evidence_ids.append(evidence_id)

        linked = item["linked_evidence_ids"]
        if not isinstance(linked, list) or len(linked) != len(set(linked)):
            raise ValueError(f"linked_evidence_ids inválidos/duplicados en {key}")
        if set(linked) != set(citation_evidence_ids):
            raise ValueError(f"linked_evidence_ids no coincide con las citas en {key}")
        prepared.append(dict(item))
    return prepared


def reject_descriptive_project_identity_collisions(
    enrichment_records: list[dict[str, Any]], descriptive_mentions: list[dict[str, Any]]
) -> None:
    """Exige adjudicación antes de convertir un sujeto descriptivo en PROJECT.

    La guarda opera por documento y etiqueta normalizada. No bloquea otros
    proyectos válidos del artículo ni menciones del mismo sujeto en fuentes
    distintas; solo impide crear una identidad PROJECT a partir del sujeto cuya
    identidad continúa explícitamente sin resolver.
    """
    subjects_by_document: dict[str, set[str]] = defaultdict(set)
    references: dict[tuple[str, str], str] = {}
    for item in descriptive_mentions:
        normalized_subject = normalize_project_name(item["subject_label"])
        if normalized_subject:
            key = (item["document_id"], normalized_subject)
            subjects_by_document[item["document_id"]].add(normalized_subject)
            references[key] = item["reference_key"]

    for record in enrichment_records:
        document_id = record.get("document_id")
        unresolved_subjects = subjects_by_document.get(document_id, set())
        if not unresolved_subjects:
            continue
        for raw_mention in record.get("proyectos_mencionados") or []:
            name = raw_mention.get("nombre") if isinstance(raw_mention, dict) else raw_mention
            normalized_name = normalize_project_name(name if isinstance(name, str) else "")
            name_tokens = set(normalized_name.split())
            for normalized_subject in unresolved_subjects:
                if set(normalized_subject.split()) <= name_tokens:
                    reference_key = references[(document_id, normalized_subject)]
                    raise ValueError(
                        "mención de proyecto coincide con sujeto descriptivo no resuelto; "
                        f"requiere adjudicación antes de crear PROJECT: {reference_key} / {name!r}"
                    )


def persist_descriptive_project_mentions(conn: sqlite3.Connection, mentions: list[dict[str, Any]]) -> int:
    """Reemplaza la tabla derivada descriptiva, sin crear identidad PROJECT."""
    conn.execute("DROP TABLE IF EXISTS descriptive_project_reference_evidence")
    conn.execute("DROP TABLE IF EXISTS descriptive_project_reference")
    conn.execute(
        """
        CREATE TABLE descriptive_project_reference (
            reference_key TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            case_mention_id TEXT NOT NULL REFERENCES case_mention(case_mention_id),
            subject_label TEXT NOT NULL,
            descriptive_label TEXT NOT NULL,
            identity_status TEXT NOT NULL CHECK (identity_status = 'descriptive_only_identity_unresolved'),
            source_url TEXT NOT NULL,
            source_text_sha256 TEXT NOT NULL,
            source_file_sha256 TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source = 'config_descriptive_project_mentions')
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_descriptive_project_reference_document ON descriptive_project_reference(document_id)"
    )
    conn.execute(
        "CREATE INDEX idx_descriptive_project_reference_case_mention ON descriptive_project_reference(case_mention_id)"
    )
    conn.execute(
        """
        CREATE TABLE descriptive_project_reference_evidence (
            reference_key TEXT NOT NULL REFERENCES descriptive_project_reference(reference_key) ON DELETE CASCADE,
            evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
            quote_text TEXT NOT NULL,
            quote_sha256 TEXT NOT NULL,
            PRIMARY KEY (reference_key, evidence_id, quote_sha256)
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_descriptive_project_reference_evidence_id ON descriptive_project_reference_evidence(evidence_id)"
    )
    conn.executemany(
        "INSERT INTO descriptive_project_reference (reference_key, document_id, case_mention_id, subject_label, "
        "descriptive_label, identity_status, source_url, source_text_sha256, source_file_sha256, source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                item["reference_key"], item["document_id"], item["case_mention_id"], item["subject_label"],
                item["descriptive_label"], item["identity_status"], item["source_url"], item["source_text_sha256"],
                item["source_file_sha256"], "config_descriptive_project_mentions",
            )
            for item in mentions
        ],
    )
    evidence_rows = [
        (item["reference_key"], evidence_id, citation["quote"], citation["quote_sha256"])
        for item in mentions
        for citation in item["citations"]
        for evidence_id in citation["evidence_ids"]
    ]
    conn.executemany(
        "INSERT INTO descriptive_project_reference_evidence (reference_key, evidence_id, quote_text, quote_sha256) "
        "VALUES (?,?,?,?)",
        evidence_rows,
    )
    return len(mentions)


# Homonimos CONFIRMADOS donde el cluster EXACTO por
# nombre normalizado fusiono, sin pasar por project_review_queue (esa cola
# solo se activa entre project_id DISTINTOS con relacion de substring -- un
# match EXACTO nunca llega ahi), dos referencias reales distintas. Hallazgo
# de la revisión al verificar el punto 8 de la segunda auditoría (riesgo
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


VERIFIED_INDEX_CORRECTIONS_PATH = PROJECT_ROOT / "config" / "project_mention_index_corrections.json"


def load_verified_project_mention_index_corrections(path: Path = VERIFIED_INDEX_CORRECTIONS_PATH) -> dict[tuple[str, str], int]:
    """Lee correcciones puntuales de case_mention_index citadas con evidencia real.

    Nunca inventa un indice: cada entrada del archivo debe citar evidence_id
    reales (verificados aparte contra el warehouse). Si el archivo no existe,
    devuelve un dict vacio -- esta correccion es opcional, no requerida."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    corrections: dict[tuple[str, str], int] = {}
    for entry in payload["corrections"]:
        key = (entry["document_id"], entry["nombre_proyecto"])
        if key in corrections:
            raise ValueError(f"verified_project_mention_index_corrections tiene entrada duplicada: {key!r}")
        corrections[key] = entry["case_mention_index"]
    return corrections


def apply_verified_project_mention_index_corrections(
    enrichment_records: list[dict[str, Any]], corrections: dict[tuple[str, str], int]
) -> int:
    """Asigna case_mention_index solo donde hoy es null y hay una correccion citada.

    Nunca sobreescribe un case_mention_index que la extraccion vigente ya establecio -- esta
    correccion es aditiva sobre menciones sin vinculo, no una reinterpretacion."""
    n_aplicadas = 0
    if not corrections:
        return n_aplicadas
    for r in enrichment_records:
        for m in r.get("proyectos_mencionados") or []:
            key = (r["document_id"], m.get("nombre"))
            if key in corrections and m.get("case_mention_index") is None:
                m["case_mention_index"] = corrections[key]
                n_aplicadas += 1
    return n_aplicadas


def apply_index_corrections_to_warehouse(conn: sqlite3.Connection, corrections: dict[tuple[str, str], int]) -> int:
    """Materializa los enlaces adjudicados en enrichment_project_mention (la tabla que consumen CONFLICT y geografia).

    Hasta esta fecha las correcciones solo se aplicaban a los registros en memoria del
    registro de proyectos, que no usa case_mention_index: ninguna llegaba a la tabla, asi que el enlace de Linea 7
    nunca tuvo efecto. Falla cerrado: cada correccion configurada debe encontrar exactamente una mencion sin indice."""
    applied = 0
    for (document_id, nombre_proyecto), index in sorted(corrections.items()):
        cursor = conn.execute(
            "UPDATE enrichment_project_mention SET case_mention_index = ?, case_mention_id = ? "
            "WHERE document_id = ? AND nombre_proyecto = ? AND case_mention_index IS NULL",
            (index, f"{document_id}:{index}", document_id, nombre_proyecto),
        )
        if cursor.rowcount != 1:
            raise ValueError(
                f"correccion de case_mention_index sin exactamente una mencion sin indice: {document_id!r} / {nombre_proyecto!r} ({cursor.rowcount})"
            )
        applied += 1
    return applied


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
        for item in record.get("proyectos_mencionados") or []:
            # la extraccion vigente: cada item es {nombre, case_mention_index, ...} -- antes
            # (la extraccion previa) era un string suelto. Este registro es mention-based por
            # nombre, no usa case_mention_index (ese vinculo vive en
            # enrichment_project_mention, consumido directamente por
            # build_conflicts.py/build_geography.py).
            raw_name = ((item.get("nombre", "") if isinstance(item, dict) else str(item)) or "").strip()
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


# Pares de nombre de proyecto que la auditoria de
# los 63 documentos 'caso_unico' con >1 case_id (conflict_unit) probo con
# citas verificadas que son el mismo proyecto escrito de forma tan
# distinta que NO comparten substring alguno -- find_review_candidates()
# nunca los habria generado (verificado: ninguno de estos 5 pares existia
# antes en la cola de 255). La revisión los marcó project_relation='alias' dentro
# de relaciones_case_groups al clasificar los 63 documentos; ver
# la evidencia y provenance completos viven en la revision de unidades de conflicto
# (config/conflict_unit_review.json). Se agregan aqui como
# candidatos EXTRA (no se fusionan solos -- la decision merged/kept_separate
# vive en resolve_project_review_queue.py::MANUAL_DECISIONS, igual que el
# resto de la cola).
MANUAL_EXTRA_REVIEW_PAIRS: list[tuple[str, str, str]] = [
    ("Villa San Luis", "Villa Carlos Cortés", "conflict_unit_review_alias"),
    (
        "Club de Golf Hacienda Santa Martina Nature - Lo Barnechea",
        "Hacienda Santa Martina, Nature Club & Golf",
        "conflict_unit_review_alias",
    ),
    ("Egaña Eco Sustentable", "Eco Egaña", "conflict_unit_review_alias"),
    (
        "LA PLANTA DE CACA",
        "Solución transitoria para la provisión de los servicios de tratamiento y disposición de Aguas Servidas",
        "conflict_unit_review_alias",
    ),
    ("Alto Las Condes 2", "Alto Norte", "conflict_unit_review_alias"),
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
        # encontrado por la revisión y verificado por la revisión: un articulo sobre
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


SOURCE_WAREHOUSE_EXPECTED_TABLES = ("enrichment_actor", "enrichment_institution", "enrichment_event", "document_case_unit")
SOURCE_WAREHOUSE_MIN_DOCUMENTS = 934


def _validate_source_warehouse(path: Path) -> None:
    """Guardrail: el warehouse de enrichment es un archivo intermedio que otro trabajo puede dejar con un schema
    incompatible. Correr este script sobre uno asi sobreescribiria data/warehouse.sqlite con un schema roto. Aborta
    ANTES de copiar, en vez de fallar a mitad de camino con el dano ya hecho."""
    if not path.exists():
        raise SystemExit(f"No existe {path} -- no se puede reconstruir el registro de proyectos.")
    conn = sqlite3.connect(path)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in SOURCE_WAREHOUSE_EXPECTED_TABLES if t not in tables]
        if missing:
            raise SystemExit(
                f"{path} no tiene el schema esperado (faltan tablas: {missing}). "
                "El archivo puede haber quedado mutado por otro trabajo (ver docstring de "
                "_validate_source_warehouse). Corre `python src/build_enrichment_tables.py` para "
                "regenerarlo correctamente (determinista, sin costo de LLM) antes de reintentar -- "
                "NO se sobreescribe data/warehouse.sqlite con un schema incompatible."
            )
        n_docs = conn.execute("SELECT COUNT(*) FROM document").fetchone()[0]
        if n_docs < SOURCE_WAREHOUSE_MIN_DOCUMENTS:
            raise SystemExit(
                f"{path} tiene solo {n_docs} documentos (se esperaban >= {SOURCE_WAREHOUSE_MIN_DOCUMENTS}). "
                "Posible corpus incompleto -- corre `python src/build_enrichment_tables.py` para regenerarlo."
            )
    finally:
        conn.close()


def main() -> int:
    _validate_source_warehouse(SOURCE_WAREHOUSE)
    source_conn = sqlite3.connect(f"file:{SOURCE_WAREHOUSE.as_posix()}?mode=ro", uri=True)
    try:
        descriptive_project_mentions = load_descriptive_project_mentions(
            source_conn, DESCRIPTIVE_PROJECT_MENTIONS_CONFIG
        )
        url_to_document_id = {
            row[1]: row[0] for row in source_conn.execute("SELECT document_id, url FROM document").fetchall()
        }
        case_unit_corrections: dict[str, dict] = {}
        has_table = source_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_case_unit'"
        ).fetchone()
        if has_table:
            # La revisión humana vive en la fuente; se lee en read-only antes de
            # copiarla. Las correcciones solo se aplican a esta reconstrucción.
            # `correccion_nombre_proyecto` se reporta para trazabilidad, pero no
            # reemplaza `proyectos_mencionados`: son el caso focal y el conjunto
            # de proyectos mencionados, respectivamente, y no son intercambiables.
            for row in source_conn.execute(
                "SELECT document_id, unidad_caso_tipo, tiene_error, correccion_proyectos_mencionados_json, "
                "correccion_nombre_proyecto FROM document_case_unit"
            ).fetchall():
                document_id, unidad_caso_tipo, tiene_error, corr_menc_json, corr_nombre = row
                case_unit_corrections[document_id] = {
                    "unidad_caso_tipo": unidad_caso_tipo,
                    "tiene_error": bool(tiene_error),
                    "proyectos_mencionados_corregido": json.loads(corr_menc_json) if corr_menc_json is not None else None,
                    "nombre_proyecto_corregido": corr_nombre,
                }
    finally:
        source_conn.close()
    # include_excluded=True: el registro de proyectos necesita las
    # 934 filas productivas completas (mismo criterio que build_enrichment_
    # tables.py) -- la exclusion de la revision de respaldo solo aplica al backing de
    # CONFLICT verificado externamente por la revisión, no a la identidad de
    # proyecto en si.
    enrichment_records = list(load_enrichment_records(include_excluded=True).values())
    actor_second_pass_records = [
        json.loads(l) for l in ACTOR_SECOND_PASS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()
    ] if ACTOR_SECOND_PASS_PATH.exists() else []

    # Adjuntar document_id a cada registro de enrichment (via url -> warehouse.document)
    for r in enrichment_records:
        r["document_id"] = url_to_document_id.get(r["url"])
    enrichment_records = [r for r in enrichment_records if r["document_id"]]

    # gate documento->unidad_de_caso: la revisión reviso los
    # 934/934 documentos y encontro 9 con proyectos_mencionados mal
    # extraidos (comunidades/actores confundidos con proyecto, casos
    # comparativos capturados como focal). Se sobrescribe SOLO
    # proyectos_mencionados donde la revisión dejo una correccion explicita
    # (correccion_proyectos_mencionados_json IS NOT NULL) -- el original
    # nunca se toca en document_case_unit, solo se usa aqui una copia
    # en memoria para construir el registro de proyectos. Sin correccion
    # explicita, el documento usa su proyectos_mencionados original tal
    # cual (la ausencia de correccion NO implica que el documento sea
    # caso_unico -- unidad_caso_tipo se propaga aparte, sin filtrar nada
    # aqui, para que el consumidor final decida si excluye documentos
    # documento_comparativo_panoramico/contexto_sin_caso_individualizable/
    # caso_focal_fuera_del_universo de su analisis).
    case_unit_corrections: dict[str, dict] = {}
    if SOURCE_WAREHOUSE.exists():
        conn_check = sqlite3.connect(SOURCE_WAREHOUSE)
        has_table = conn_check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_case_unit'"
        ).fetchone()
        if has_table:
            # la consulta anterior
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
            # document_case_unit directamente, no de este registry.
            for row in conn_check.execute(
                "SELECT document_id, unidad_caso_tipo, tiene_error, correccion_proyectos_mencionados_json, "
                "correccion_nombre_proyecto "
                "FROM document_case_unit"
            ).fetchall():
                document_id, unidad_caso_tipo, tiene_error, corr_menc_json, corr_nombre = row
                case_unit_corrections[document_id] = {
                    "unidad_caso_tipo": unidad_caso_tipo,
                    "tiene_error": bool(tiene_error),
                    "proyectos_mencionados_corregido": json.loads(corr_menc_json) if corr_menc_json is not None else None,
                    "nombre_proyecto_corregido": corr_nombre,
                }
        conn_check.close()

    verified_index_corrections = load_verified_project_mention_index_corrections()
    n_docs_con_correccion_de_menciones = 0
    n_docs_con_correccion_de_nombre_no_aplicada_al_registry = sum(
        1 for c in case_unit_corrections.values() if c["nombre_proyecto_corregido"] is not None
    )
    for r in enrichment_records:
        corr = case_unit_corrections.get(r["document_id"])
        if corr and corr["proyectos_mencionados_corregido"] is not None:
            # correccion_proyectos_mencionados_json se guardo en 2026-09-18
            # (previa) como lista de strings sueltos -- se envuelve al
            # shape la extraccion vigente {nombre, case_mention_index} con indice null (la
            # correccion de la revisión nunca tuvo un case_mention_index verificado,
            # asi que esa mencion simplemente queda sin vinculo verificado,
            # nunca se inventa uno).
            r["proyectos_mencionados"] = [
                {"nombre": nombre, "case_mention_index": None}
                for nombre in corr["proyectos_mencionados_corregido"]
            ]
            n_docs_con_correccion_de_menciones += 1

    reject_descriptive_project_identity_collisions(enrichment_records, descriptive_project_mentions)
    n_menciones_con_indice_verificado_corregido = apply_verified_project_mention_index_corrections(
        enrichment_records, verified_index_corrections
    )

    projects, mention_lookup = build_project_registry(enrichment_records)
    review_candidates = find_review_candidates(projects)

    # Toda validación semántica que puede rechazar la construcción ocurre antes
    # de copiar sobre la salida previa. En particular, una colisión de identidad
    # descriptiva no debe destruir ni reemplazar el warehouse existente.
    OUTPUT_WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE_WAREHOUSE, OUTPUT_WAREHOUSE)
    conn = sqlite3.connect(OUTPUT_WAREHOUSE)
    n_indices_materializados_en_warehouse = apply_index_corrections_to_warehouse(conn, verified_index_corrections)
    write_release_metadata(conn)
    conn.commit()

    conn.executescript("""
        DROP TABLE IF EXISTS project_relation;
        DROP TABLE IF EXISTS project_relation_type;
        DROP TABLE IF EXISTS project;
        DROP TABLE IF EXISTS project_mention_resolved;
        DROP TABLE IF EXISTS project_review_queue;
        DROP TABLE IF EXISTS actor_event_project_link;
        DROP TABLE IF EXISTS descriptive_project_reference;

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
    n_descriptive_project_references = persist_descriptive_project_mentions(conn, descriptive_project_mentions)

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
        ("enrichment_actor", "actor_id", "nombre"),
        ("enrichment_institution", "institucion_id", "nombre"),
        ("enrichment_event", "event_id", "descripcion"),
    ):
        for row in conn.execute(f"SELECT {id_col}, document_id, {label_col}, proyecto_asociado FROM {table}").fetchall():
            source_id, document_id, label, proyecto_asociado = row
            _add_link(table, source_id, document_id, label or "", proyecto_asociado or "", "first")

    # [CORRECCION 2026-09-18, hallazgo BLOQUEANTE de la revisión, segunda auditoria]
    # actores_final de actor_second_pass_v2 es POR DISENO la union A∪B de la
    # primera pasada (ya cargada arriba desde enrichment_actor, con
    # source_pass="first") y la segunda pasada independiente -- incluye
    # filas con source_pass in {"first","both","second"}. Cargar TODAS esas
    # filas aqui duplicaba en actor_event_project_link cualquier actor que
    # ya existiera en la primera pasada (source_pass "first" o "both"): dos
    # filas para la MISMA relacion actor-documento sustantiva, con dos
    # source_id distintos. Sin filtrar esto, cualquier calculo de grado/peso
    # de aristas para la red de actores quedaria inflado -- verificado: 3192 de
    # 5491 filas (58%) de actor_second_pass_v2 tenian source_pass in
    # ("first","both") antes de este fix. Correccion elegida (mas simple que
    # una tabla de deduplicacion explicita, sugerida como alternativa por
    # la revisión): incorporar de actores_final SOLO los actores con
    # source_pass=="second" -- los "first"/"both" ya estan representados,
    # con mejor procedencia, via la carga de enrichment_actor de arriba.
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

    # Sin esta vista, cualquier
    # consumidor (ej. quien construya la red) que haga SELECT * FROM
    # actor_event_project_link sin JOIN a document_case_unit obtiene
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
    # Si un documento no tiene fila en document_case_unit (no debería
    # ocurrir para los 934, pero por robustez), la vista lo excluye por
    # defecto -- conservador ante datos faltantes, nunca incluye por omision.
    if case_unit_corrections:
        conn.executescript(
            """
            DROP VIEW IF EXISTS actor_event_project_link_case_safe;
            CREATE VIEW actor_event_project_link_case_safe AS
                SELECT l.*
                FROM actor_event_project_link l
                JOIN document_case_unit g ON g.document_id = l.document_id
                WHERE g.unidad_caso_tipo = 'caso_unico'
                  AND l.resolution_status = 'resolved_explicit';

            DROP VIEW IF EXISTS actor_event_project_link_include_inferred;
            CREATE VIEW actor_event_project_link_include_inferred AS
                SELECT l.*
                FROM actor_event_project_link l
                JOIN document_case_unit g ON g.document_id = l.document_id
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
        "n_descriptive_project_references_identity_unresolved": n_descriptive_project_references,
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
            "disponible": bool(case_unit_corrections),
            "n_documentos_con_gate": len(case_unit_corrections),
            "n_documentos_con_correccion_de_proyectos_mencionados_aplicada": n_docs_con_correccion_de_menciones,
            "n_documentos_con_correccion_de_nombre_proyecto_preservada_no_aplicada": n_docs_con_correccion_de_nombre_no_aplicada_al_registry,
            "unidad_caso_tipo_counts": (
                dict(Counter(c["unidad_caso_tipo"] for c in case_unit_corrections.values())) if case_unit_corrections else {}
            ),
            "nota": (
                "document_case_unit (copiada de warehouse_enrichment.sqlite a esta base) trae la "
                "clasificacion de unidad de caso para los 934 documentos. [PRECISION 2026-09-18, "
                "se encontro que la frase anterior era imprecisa] Este script aplico las 9 correcciones "
                "de proyectos_mencionados al construir el registro de proyectos. Las 9 correcciones de "
                "nombre_proyecto NO se aplican aqui -- quedan preservadas y consultables en "
                "document_case_unit.correccion_nombre_proyecto, pero el registro de proyectos "
                "siempre fue mention-based (recorre proyectos_mencionados), nunca focal-based, y los 2 "
                "conjuntos de 9 correcciones no son los mismos documentos (ver active-context.md). NO se "
                "excluye ningun documento por su unidad_caso_tipo -- si el analisis de redes quiere "
                "excluir documento_comparativo_panoramico/contexto_sin_caso_individualizable/caso_focal_"
                "fuera_del_universo, debe filtrar explicitamente usando esa tabla via document_id (ver "
                "tambien actor_event_project_link_case_safe, vista conservadora agregada para no "
                "depender de que cada consumidor recuerde el filtro correcto)."
            ),
        },
        "verified_project_mention_index_corrections": {
            "disponible": bool(verified_index_corrections),
            "n_entradas_configuradas": len(verified_index_corrections),
            "n_menciones_corregidas": n_menciones_con_indice_verificado_corregido,
            "n_indices_materializados_en_enrichment_project_mention": n_indices_materializados_en_warehouse,
            "fuente": "config/project_mention_index_corrections.json",
            "nota": (
                "Corrige case_mention_index=null puntual para menciones donde la evidencia "
                "estructurada del warehouse ya identifica sin ambiguedad el case_mention -- nunca "
                "inventa un indice, cada entrada cita evidence_id reales. No reemplaza la lista de "
                "proyectos_mencionados como case_unit_corrections; solo ajusta el indice de una mencion "
                "que la extraccion vigente ya extrajo."
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
