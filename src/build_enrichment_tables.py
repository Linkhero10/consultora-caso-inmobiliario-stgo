#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materializa enrichment v3.3 en un warehouse intermedio (2026-09-26).

El ETL es determinista y no llama a ninguna API. Copia ``warehouse_v1`` a un
archivo nuevo y agrega tablas de enrichment sin modificar el warehouse
historico. Fuente: los 3 archivos de enrichment v3.3 (piloto/calibracion/
escalamiento, ver src/v3_3_enrichment_source.py) que juntos cubren el 100%
(934/934) del corpus productivo desde 2026-09-26 -- v3.2
(``Auditoria/enriquecimiento_v3_2_934/enrichment.jsonl``) queda retirado
como fuente productiva (se conserva en disco como dato historico, nunca se
borra, pero ya no es el default de este script).

v3.3 difiere de v3.2 en un solo campo de shape: ``proyectos_mencionados`` es
una lista de objetos ``{nombre, case_mention_index, ...}`` en vez de una
lista de strings -- el resto de los campos del registro (actores,
instituciones, linea_tiempo, objeto_disputa, etc.) son identicos entre
versiones. Este ETL persiste ``case_mention_index``/``case_mention_id`` en
``enrichment_project_mention`` -- antes esa informacion solo existia
releyendo los JSONL crudos en cada corrida de build_conflicts.py (Fix 1D).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v3_3_enrichment_source import load_v3_3_records  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v1.sqlite"
DEFAULT_OUTPUT_DB = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_enrichment.sqlite"
# document_case_unit son correcciones MANUALES de Sol (revision humana de
# unidad de caso), no derivables del enrichment JSONL -- no existen en
# warehouse_v1.sqlite. Historicamente se agregaban a warehouse_v3_2.sqlite
# con un script de un solo uso en Trabajo/scripts DESPUES de correr este
# ETL, un paso tribal no documentado en el pipeline reproducible. Se copian
# aqui desde el warehouse productivo (fuente actual de esas correcciones)
# para que este script sea reproducible sin ese paso manual oculto.
PRODUCTIVE_WAREHOUSE_FOR_CASE_UNIT = PROJECT_ROOT / "data" / "warehouse.sqlite"


def _copy_document_case_unit(conn: sqlite3.Connection, source_path: Path) -> int:
    """Copia document_case_unit (correcciones de Sol) desde el warehouse
    productivo, si existe. Devuelve el numero de filas copiadas (0 si la
    fuente no existe o no tiene la tabla -- nunca aborta, esta tabla es
    opcional para build_database() en si, pero build_projects.py la exige)."""
    if not source_path.exists():
        return 0
    src_conn = sqlite3.connect(source_path)
    try:
        tables = {row[0] for row in src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "document_case_unit" not in tables:
            return 0
        cols_info = src_conn.execute("PRAGMA table_info(document_case_unit)").fetchall()
        columns = [c[1] for c in cols_info]
        rows = src_conn.execute(f"SELECT {','.join(columns)} FROM document_case_unit").fetchall()
    finally:
        src_conn.close()
    if not rows:
        return 0
    conn.execute(f"DROP TABLE IF EXISTS document_case_unit")
    col_defs = ", ".join(f"{c[1]} {c[2]}" + (" PRIMARY KEY" if c[5] else "") for c in cols_info)
    conn.execute(f"CREATE TABLE document_case_unit ({col_defs})")
    placeholders = ",".join("?" for _ in columns)
    conn.executemany(f"INSERT INTO document_case_unit ({','.join(columns)}) VALUES ({placeholders})", rows)
    return len(rows)


def _make_evidence_id(document_id: str, campo: str, idx: int) -> str:
    return f"{document_id}:enrichment:{campo}:{idx}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _validate_project_associations(record: dict[str, Any]) -> list[str]:
    projects = {
        (item.get("nombre", "") or "").strip()
        for item in (record.get("proyectos_mencionados", []) or [])
        if isinstance(item, dict) and (item.get("nombre", "") or "").strip()
    }
    errors: list[str] = []
    for collection in ("actores", "instituciones_mencionadas", "linea_tiempo"):
        for index, item in enumerate(record.get(collection, []) or []):
            association = (item.get("proyecto_asociado", "") or "") if isinstance(item, dict) else ""
            if association and association not in projects:
                errors.append(f"{collection}[{index}].proyecto_asociado={association!r} no aparece en proyectos_mencionados")
    return errors


def _create_tables(conn: sqlite3.Connection) -> None:
    for table in (
        "enrichment_document",
        "enrichment_project_mention",
        "enrichment_actor",
        "enrichment_institution",
        "enrichment_event",
        "enrichment_evidence",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table}")

    conn.executescript(
        """
        CREATE TABLE enrichment_document (
            document_id TEXT PRIMARY KEY REFERENCES document(document_id),
            url TEXT NOT NULL,
            nombre_proyecto TEXT,
            proyectos_mencionados_json TEXT NOT NULL,
            objeto_disputa_norm TEXT,
            objeto_disputa_raw TEXT,
            evidencia_objeto_disputa TEXT,
            evidencia_objeto_disputa_verificada INTEGER,
            tipo_accion TEXT,
            escala_conflicto TEXT,
            institucion_decisora_segun_fuente TEXT,
            instrumento_norm TEXT,
            instrumento_raw TEXT,
            via_legal_norm TEXT,
            resultado_actuacion TEXT,
            tipo_evidencia_fuente TEXT,
            ubicacion_especifica TEXT,
            explicacion_tipo_conflicto TEXT,
            explicacion_actores TEXT,
            revision_nivel TEXT,
            revision_campos_afectados_json TEXT NOT NULL,
            revision_motivo TEXT,
            triage_consistency_check INTEGER,
            triage_consistency_note TEXT,
            actores_posiblemente_truncados INTEGER,
            instituciones_posiblemente_truncadas INTEGER,
            hitos_posiblemente_truncados INTEGER,
            decision_documento_etapa1 TEXT,
            contract_version_etapa1 TEXT,
            content_sha256 TEXT,
            content_char_count INTEGER,
            input_truncated INTEGER,
            enrichment_schema_version TEXT,
            prompt_sha256 TEXT,
            schema_sha256 TEXT,
            record_schema_sha256 TEXT,
            record_schema_sha256_at_generation TEXT,
            script_sha256 TEXT,
            runner_script_sha256 TEXT,
            core_enrichment_script_sha256 TEXT,
            run_id TEXT
        );
        CREATE TABLE enrichment_project_mention (
            project_mention_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            idx INTEGER NOT NULL,
            nombre_proyecto TEXT NOT NULL,
            case_mention_index INTEGER,
            case_mention_id TEXT
        );
        CREATE TABLE enrichment_actor (
            actor_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            idx INTEGER NOT NULL,
            nombre TEXT,
            tipo TEXT,
            rol TEXT,
            stance TEXT,
            nivel_involucramiento TEXT,
            proyecto_asociado TEXT,
            cita TEXT,
            cita_original_modelo TEXT,
            cita_verificada INTEGER,
            evidence_id TEXT
        );
        CREATE TABLE enrichment_institution (
            institucion_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            idx INTEGER NOT NULL,
            nombre TEXT,
            tipo_norm TEXT,
            rol_en_texto TEXT,
            accion_institucional TEXT,
            proyecto_asociado TEXT,
            cita TEXT,
            cita_original_modelo TEXT,
            cita_verificada INTEGER,
            evidence_id TEXT
        );
        CREATE TABLE enrichment_event (
            event_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            idx INTEGER NOT NULL,
            fecha TEXT,
            date_precision TEXT,
            descripcion TEXT,
            tipo_hito TEXT,
            proyecto_asociado TEXT,
            fecha_year_grounded INTEGER,
            evidencia_hito TEXT,
            evidencia_hito_original_modelo TEXT,
            evidencia_hito_verificada INTEGER,
            evidence_id TEXT,
            nombre_proyecto_documento TEXT,
            revision_nivel_documento TEXT
        );
        CREATE TABLE enrichment_evidence (
            evidence_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            campo TEXT NOT NULL,
            quote_index INTEGER NOT NULL,
            quote_text TEXT,
            quote_original_modelo TEXT,
            verified INTEGER
        );
        CREATE INDEX idx_enrichment_project_mention_document
            ON enrichment_project_mention(document_id);
        CREATE INDEX idx_enrichment_actor_document
            ON enrichment_actor(document_id);
        CREATE INDEX idx_enrichment_institucion_document
            ON enrichment_institution(document_id);
        CREATE INDEX idx_enrichment_evento_document
            ON enrichment_event(document_id);
        CREATE INDEX idx_enrichment_evidence_document
            ON enrichment_evidence(document_id);
        """
    )


def build_database(source_db: Path, output_db: Path, records: dict[str, dict[str, Any]] | None = None) -> dict[str, int]:
    """Construye el warehouse de enrichment (fuente v3.3) y devuelve conteos auditables.

    ``records`` es dict[url] -> record ya cargado (ver
    v3_3_enrichment_source.load_v3_3_records()); si se omite, se carga con
    include_fuera_de_universo=True porque este ETL necesita las 934 filas
    productivas completas, no solo el subconjunto auditado externamente por
    Sol (esa distincion solo importa para el backing de CONFLICT en
    build_conflicts.py, no para materializar el registro de enrichment en si
    -- el unico documento excluido por defecto en otros consumidores paso
    las mismas verificaciones automaticas de schema/citas que los otros 933).
    """
    source_db = Path(source_db)
    output_db = Path(output_db)
    if source_db.resolve() == output_db.resolve():
        raise ValueError("output_db debe ser distinto de source_db; no se sobreescribe warehouse_v1")
    if not source_db.exists():
        raise FileNotFoundError(source_db)

    if records is None:
        records = load_v3_3_records(include_fuera_de_universo=True)
    if not records:
        raise ValueError("No hay registros de enrichment v3.3 para procesar (records vacio).")

    output_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_db, output_db)
    conn = sqlite3.connect(output_db)
    conn.execute("PRAGMA foreign_keys = ON")
    _create_tables(conn)

    doc_ids_by_url = {url: doc_id for url, doc_id in conn.execute("SELECT url, document_id FROM document")}
    rows = list(records.values())
    counts = {
        "documents": 0,
        "projects": 0,
        "actors": 0,
        "institutions": 0,
        "events": 0,
        "evidence": 0,
        "unmatched_documents": 0,
        "duplicate_documents": 0,
        "invalid_project_associations": 0,
        "document_case_unit_rows": 0,
    }
    seen_documents: set[str] = set()

    for record in rows:
        url = record.get("url", "")
        document_id = doc_ids_by_url.get(url)
        if document_id is None:
            counts["unmatched_documents"] += 1
            continue
        if document_id in seen_documents:
            counts["duplicate_documents"] += 1
            continue
        seen_documents.add(document_id)
        association_errors = _validate_project_associations(record)
        counts["invalid_project_associations"] += len(association_errors)

        revision = record.get("revision", {}) or {}
        conn.execute(
            """INSERT INTO enrichment_document (
                document_id,url,nombre_proyecto,proyectos_mencionados_json,
                objeto_disputa_norm,objeto_disputa_raw,evidencia_objeto_disputa,
                evidencia_objeto_disputa_verificada,tipo_accion,escala_conflicto,
                institucion_decisora_segun_fuente,instrumento_norm,instrumento_raw,
                via_legal_norm,resultado_actuacion,tipo_evidencia_fuente,
                ubicacion_especifica,explicacion_tipo_conflicto,explicacion_actores,
                revision_nivel,revision_campos_afectados_json,revision_motivo,
                triage_consistency_check,triage_consistency_note,
                actores_posiblemente_truncados,instituciones_posiblemente_truncadas,
                hitos_posiblemente_truncados,decision_documento_etapa1,
                contract_version_etapa1,content_sha256,content_char_count,input_truncated,
                enrichment_schema_version,prompt_sha256,schema_sha256,record_schema_sha256,
                record_schema_sha256_at_generation,
                script_sha256,runner_script_sha256,core_enrichment_script_sha256,run_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                document_id, url, record.get("nombre_proyecto", ""), _json(record.get("proyectos_mencionados", [])),
                record.get("objeto_disputa_norm", ""), record.get("objeto_disputa_raw", ""),
                record.get("evidencia_objeto_disputa", ""), int(bool(record.get("evidencia_objeto_disputa_verificada"))),
                record.get("tipo_accion", ""), record.get("escala_conflicto", ""),
                record.get("institucion_decisora_segun_fuente", ""), record.get("instrumento_norm", ""),
                record.get("instrumento_raw", ""), record.get("via_legal_norm", ""), record.get("resultado_actuacion", ""),
                record.get("tipo_evidencia_fuente", ""), record.get("ubicacion_especifica", ""),
                record.get("explicacion_tipo_conflicto", ""), record.get("explicacion_actores", ""),
                revision.get("nivel", "ninguno"), _json(revision.get("campos_afectados", [])), revision.get("motivo", ""),
                int(bool(record.get("triage_consistency_check"))), record.get("triage_consistency_note", ""),
                int(bool(record.get("actores_posiblemente_truncados"))), int(bool(record.get("instituciones_posiblemente_truncadas"))),
                int(bool(record.get("hitos_posiblemente_truncados"))), record.get("decision_documento_etapa1", ""),
                record.get("contract_version_etapa1"), record.get("content_sha256", ""), record.get("content_char_count", 0),
                int(bool(record.get("input_truncated"))), record.get("enrichment_schema_version", ""), record.get("prompt_sha256", ""),
                record.get("schema_sha256", ""), record.get("record_schema_sha256", ""),
                record.get("record_schema_sha256_at_generation", ""),
                record.get("script_sha256", ""),
                record.get("runner_script_sha256", ""), record.get("core_enrichment_script_sha256", ""), record.get("run_id", ""),
            ),
        )
        counts["documents"] += 1

        projects = record.get("proyectos_mencionados", []) or []
        for idx, project in enumerate(projects):
            nombre_proyecto = (project.get("nombre", "") or "") if isinstance(project, dict) else str(project)
            case_mention_index = project.get("case_mention_index") if isinstance(project, dict) else None
            case_mention_id = f"{document_id}:{case_mention_index}" if case_mention_index is not None else None
            conn.execute(
                "INSERT INTO enrichment_project_mention VALUES (?,?,?,?,?,?)",
                (f"{document_id}:project:{idx}", document_id, idx, nombre_proyecto, case_mention_index, case_mention_id),
            )
            counts["projects"] += 1

        def add_evidence(campo: str, idx: int, quote: str, original: str, verified: bool) -> str | None:
            if not quote:
                return None
            evidence_id = _make_evidence_id(document_id, campo, idx)
            conn.execute(
                "INSERT INTO enrichment_evidence VALUES (?,?,?,?,?,?,?)",
                (evidence_id, document_id, campo, idx, quote, original, int(bool(verified))),
            )
            counts["evidence"] += 1
            return evidence_id

        for idx, actor in enumerate(record.get("actores", []) or []):
            quote = actor.get("cita", "") or ""
            evidence_id = add_evidence("actor", idx, quote, actor.get("cita_original_modelo", "") or "", bool(actor.get("cita_verificada")))
            conn.execute(
                "INSERT INTO enrichment_actor VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{document_id}:actor:{idx}", document_id, idx, actor.get("nombre", ""), actor.get("tipo", ""),
                 actor.get("rol", ""), actor.get("stance", ""), actor.get("nivel_involucramiento", ""),
                 actor.get("proyecto_asociado", ""), quote, actor.get("cita_original_modelo", "") or "",
                 int(bool(actor.get("cita_verificada"))), evidence_id),
            )
            counts["actors"] += 1

        for idx, institution in enumerate(record.get("instituciones_mencionadas", []) or []):
            quote = institution.get("cita", "") or ""
            evidence_id = add_evidence("institucion", idx, quote, institution.get("cita_original_modelo", "") or "", bool(institution.get("cita_verificada")))
            conn.execute(
                "INSERT INTO enrichment_institution VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{document_id}:institucion:{idx}", document_id, idx, institution.get("nombre", ""), institution.get("tipo_norm", ""),
                 institution.get("rol_en_texto", ""), institution.get("accion_institucional", ""), institution.get("proyecto_asociado", ""),
                 quote, institution.get("cita_original_modelo", "") or "", int(bool(institution.get("cita_verificada"))), evidence_id),
            )
            counts["institutions"] += 1

        revision_nivel = revision.get("nivel", "ninguno")
        for idx, event in enumerate(record.get("linea_tiempo", []) or []):
            quote = event.get("evidencia_hito", "") or ""
            evidence_id = add_evidence("hito", idx, quote, event.get("evidencia_hito_original_modelo", "") or "", bool(event.get("evidencia_hito_verificada")))
            conn.execute(
                "INSERT INTO enrichment_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{document_id}:evento:{idx}", document_id, idx, event.get("fecha", ""), event.get("date_precision", ""),
                 event.get("descripcion", ""), event.get("tipo_hito", ""), event.get("proyecto_asociado", ""),
                 int(bool(event.get("fecha_year_grounded"))), quote, event.get("evidencia_hito_original_modelo", "") or "",
                 int(bool(event.get("evidencia_hito_verificada"))), evidence_id, record.get("nombre_proyecto", ""), revision_nivel),
            )
            counts["events"] += 1

        quote = record.get("evidencia_objeto_disputa", "") or ""
        add_evidence("objeto_disputa", 0, quote, record.get("evidencia_objeto_disputa_original_modelo", "") or "", bool(record.get("evidencia_objeto_disputa_verificada")))

    counts["document_case_unit_rows"] = _copy_document_case_unit(conn, PRODUCTIVE_WAREHOUSE_FOR_CASE_UNIT)

    conn.commit()
    conn.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--output-db", type=Path, default=DEFAULT_OUTPUT_DB)
    args = parser.parse_args()
    try:
        counts = build_database(args.source_db, args.output_db)
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(f"ERROR ETL enrichment v3.3: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_db": str(args.output_db), **counts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
