"""Construye relaciones tipadas entre entidades PROJECT con evidencia explícita."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELATION_CONFIG = PROJECT_ROOT / "config" / "project_relations.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _relation_id(subject_id: str, relation_type: str, object_id: str) -> str:
    key = "::".join((subject_id, relation_type, object_id))
    return "project-rel:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _validate_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != "1.0":
        raise ValueError("schema_version no soportada en project_relations.json")

    relation_types = config.get("relation_types")
    relations = config.get("relations")
    if not isinstance(relation_types, list) or not isinstance(relations, list):
        raise ValueError("relation_types y relations deben ser listas")

    type_names = [item.get("relation_type") for item in relation_types]
    if any(not isinstance(name, str) or not name for name in type_names):
        raise ValueError("cada tipo de relación requiere relation_type")
    if len(type_names) != len(set(type_names)):
        raise ValueError("relation_type duplicado")

    seen_pairs: set[tuple[str, str, str]] = set()
    for relation in relations:
        subject = relation.get("subject_project_id")
        object_ = relation.get("object_project_id")
        relation_type = relation.get("relation_type")
        if not all(isinstance(value, str) and value for value in (subject, object_, relation_type)):
            raise ValueError("cada relación requiere subject_project_id, object_project_id y relation_type")
        if subject == object_:
            raise ValueError("una relación no puede conectar un project_id consigo mismo")
        if relation_type not in type_names:
            raise ValueError(f"relation_type sin definición: {relation_type}")
        key = (subject, relation_type, object_)
        if key in seen_pairs:
            raise ValueError("relación duplicada")
        seen_pairs.add(key)

        for field in ("evidence_url", "source_title", "source_locator", "evidence_quote", "source_accessed_at"):
            if not isinstance(relation.get(field), str) or not relation[field].strip():
                raise ValueError(f"cada relación requiere {field}")
        if not relation["evidence_url"].startswith("https://"):
            raise ValueError("evidence_url debe ser HTTPS")
        if len(relation["evidence_quote"].split()) > 25:
            raise ValueError("evidence_quote supera el máximo de 25 palabras")
        if relation.get("verification_status") != "source_verified":
            raise ValueError("solo se materializan relaciones con fuente verificada")
        source_hash = relation.get("source_sha256")
        if source_hash is not None and not _SHA256_RE.fullmatch(source_hash):
            raise ValueError("source_sha256 debe ser null o un SHA-256 hexadecimal completo")


def rebuild_project_relations(
    conn: sqlite3.Connection,
    config_path: Path = RELATION_CONFIG,
) -> dict[str, int]:
    """Recrea el registro de relaciones verificadas desde el archivo versionado.

    Se valida el archivo y la existencia de ambos project_id antes de borrar
    tablas previas, para que una configuración incompleta falle sin destruir
    el estado anterior.
    """
    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_config(config)

    project_ids = {row[0] for row in conn.execute("SELECT project_id FROM project")}
    required_ids = {
        project_id
        for relation in config["relations"]
        for project_id in (relation["subject_project_id"], relation["object_project_id"])
    }
    missing = sorted(required_ids - project_ids)
    if missing:
        raise ValueError(f"project_id ausente en warehouse: {', '.join(missing)}")

    conn.execute("DROP TABLE IF EXISTS project_relation")
    conn.execute("DROP TABLE IF EXISTS project_relation_type")
    conn.execute(
        """CREATE TABLE project_relation_type (
               relation_type TEXT PRIMARY KEY,
               label_es TEXT NOT NULL,
               description TEXT NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE project_relation (
               relation_id TEXT PRIMARY KEY,
               subject_project_id TEXT NOT NULL REFERENCES project(project_id),
               relation_type TEXT NOT NULL REFERENCES project_relation_type(relation_type),
               object_project_id TEXT NOT NULL REFERENCES project(project_id),
               evidence_url TEXT NOT NULL,
               source_title TEXT NOT NULL,
               source_locator TEXT NOT NULL,
               evidence_quote TEXT NOT NULL,
               source_accessed_at TEXT NOT NULL,
               source_sha256 TEXT,
               verification_status TEXT NOT NULL CHECK (verification_status = 'source_verified'),
               UNIQUE (subject_project_id, relation_type, object_project_id),
               CHECK (subject_project_id <> object_project_id),
               CHECK (source_sha256 IS NULL OR length(source_sha256) = 64)
           )"""
    )
    conn.executemany(
        "INSERT INTO project_relation_type (relation_type, label_es, description) VALUES (?,?,?)",
        [
            (item["relation_type"], item["label_es"], item["description"])
            for item in config["relation_types"]
        ],
    )
    conn.executemany(
        """INSERT INTO project_relation (
               relation_id, subject_project_id, relation_type, object_project_id,
               evidence_url, source_title, source_locator, evidence_quote,
               source_accessed_at, source_sha256, verification_status
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                _relation_id(
                    relation["subject_project_id"],
                    relation["relation_type"],
                    relation["object_project_id"],
                ),
                relation["subject_project_id"],
                relation["relation_type"],
                relation["object_project_id"],
                relation["evidence_url"],
                relation["source_title"],
                relation["source_locator"],
                relation["evidence_quote"],
                relation["source_accessed_at"],
                relation.get("source_sha256"),
                relation["verification_status"],
            )
            for relation in config["relations"]
        ],
    )
    return {
        "relation_types": len(config["relation_types"]),
        "project_relations": len(config["relations"]),
    }
