"""Huellas de CONTENIDO del warehouse (no de bytes de archivo).

El hash de los bytes de un archivo SQLite no es reproducible: cambia con el orden fisico de las paginas, con un
UPDATE posterior a un INSERT, con VACUUM o con la version de SQLite. Un pin sobre esos bytes se rompe sin que
cambie ningun dato (y obliga a "repinnear" a mano). Estas funciones hashean las FILAS de las tablas, ordenadas, de
modo que dos construcciones con los mismos datos dan la misma huella en cualquier maquina.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3


def table_content_sha256(conn: sqlite3.Connection, table: str) -> str:
    """SHA-256 del contenido de una tabla: filas serializadas en JSON, ordenadas como texto."""
    cursor = conn.execute(f"SELECT * FROM {table}")
    columns = [d[0] for d in cursor.description]
    lines = sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in cursor)
    digest = hashlib.sha256()
    digest.update(json.dumps(columns).encode("utf-8"))
    for line in lines:
        digest.update(b"\n")
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def project_source_content_sha256(conn: sqlite3.Connection) -> str:
    """Huella del estado previo a la primera resolucion de identidad: los proyectos y sus menciones."""
    combined = {table: table_content_sha256(conn, table) for table in ("project", "project_mention_resolved")}
    return hashlib.sha256(json.dumps(combined, sort_keys=True).encode("utf-8")).hexdigest()
