#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Materializa la extraccion por LLM (enrichment) en un warehouse intermedio.

El ETL es determinista y no llama a ninguna API. Copia el warehouse base a un archivo nuevo y agrega las
tablas `enrichment_*` sin modificar el original. Fuente: las corridas de extraccion
(`intermediate/enrichment/*/enrichment.jsonl`, ver `src/enrichment_source.py`).

`proyectos_mencionados` es una lista de objetos `{nombre, case_mention_index, ...}`: el modelo ancla cada
proyecto a la `case_mention` que lo tiene como objeto. Este ETL persiste `case_mention_index` y
`case_mention_id` en la MISMA fila de `enrichment_project_mention`, asi que el vinculo mencion -> case_mention
nace en la extraccion y viaja hasta el conflicto sin ser reconstruido por similitud de texto.

`document_case_unit` (la revision de la unidad de caso de cada documento) es una decision humana, no derivable
de la extraccion: vive en `config/document_case_unit_review.json` y se carga desde ahi en cada reconstruccion,
de modo que ninguna corrida depende de una construccion previa.
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
from enrichment_source import load_enrichment_records  # noqa: E402
from paths import BASE_WAREHOUSE_PATH, ENRICHMENT_WAREHOUSE_PATH  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = BASE_WAREHOUSE_PATH
DEFAULT_OUTPUT_DB = ENRICHMENT_WAREHOUSE_PATH
DOCUMENT_CASE_UNIT_REVIEW_PATH = PROJECT_ROOT / "config" / "document_case_unit_review.json"
ALLOWED_UNIDAD_CASO_TIPO = frozenset(
    {
        "caso_unico",
        "multiples_casos_documentados",
        "caso_focal_fuera_del_universo",
        "documento_comparativo_panoramico",
        "contexto_sin_caso_individualizable",
    }
)
DOCUMENT_CASE_UNIT_COLUMNS = (
    "document_id", "unidad_caso_tipo", "tiene_error", "correccion_nombre_proyecto",
    "correccion_proyectos_mencionados_json", "correccion_ubicacion_especifica", "nota_revision", "revisado_por",
)


def load_document_case_unit_review(path: Path) -> list[dict]:
    """Lee la revision de unidad de caso; falla cerrado ante datos incompletos o inconsistentes."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "document_case_unit_review":
        raise ValueError("schema_version de document_case_unit_review no reconocido")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("document_case_unit_review.rows debe ser una lista no vacia")
    seen: set[str] = set()
    for item in rows:
        document_id = item.get("document_id")
        if not document_id or document_id in seen:
            raise ValueError(f"document_case_unit_review con document_id vacio o duplicado: {document_id!r}")
        seen.add(document_id)
        if item.get("unidad_caso_tipo") not in ALLOWED_UNIDAD_CASO_TIPO:
            raise ValueError(f"unidad_caso_tipo no permitido: {item.get('unidad_caso_tipo')!r}")
        if item.get("tiene_error") not in (0, 1):
            raise ValueError(f"tiene_error debe ser 0 o 1: {document_id!r}")
        if not item.get("revisado_por"):
            raise ValueError(f"document_case_unit_review sin revisado_por: {document_id!r}")
        evidence = item.get("evidence")
        if evidence is not None and not (evidence.get("source_url") and evidence.get("quote")):
            raise ValueError(f"evidencia incompleta en document_case_unit_review: {document_id!r}")
    return rows


def _load_document_case_unit(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Crea `document_case_unit` desde la revision versionada. Devuelve el numero de filas."""
    known = {row[0] for row in conn.execute("SELECT document_id FROM document")}
    unknown = [row["document_id"] for row in rows if row["document_id"] not in known]
    if unknown:
        raise ValueError(f"document_case_unit_review referencia documentos inexistentes: {unknown[:5]!r}")
    conn.execute("DROP TABLE IF EXISTS document_case_unit")
    conn.execute(
        "CREATE TABLE document_case_unit (document_id TEXT PRIMARY KEY, unidad_caso_tipo TEXT, tiene_error INTEGER, "
        "correccion_nombre_proyecto TEXT, correccion_proyectos_mencionados_json TEXT, "
        "correccion_ubicacion_especifica TEXT, nota_revision TEXT, revisado_por TEXT)"
    )
    conn.executemany(
        f"INSERT INTO document_case_unit ({','.join(DOCUMENT_CASE_UNIT_COLUMNS)}) VALUES ({','.join('?' for _ in DOCUMENT_CASE_UNIT_COLUMNS)})",
        [tuple(row.get(column) for column in DOCUMENT_CASE_UNIT_COLUMNS) for row in rows],
    )
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


def build_database(
    source_db: Path,
    output_db: Path,
    records: dict[str, dict[str, Any]] | None = None,
    case_unit_rows: list[dict] | None = None,
) -> dict[str, int]:
    """Construye el warehouse de enrichment y devuelve conteos auditables.

    ``records`` es dict[url] -> registro ya cargado (ver `enrichment_source.load_enrichment_records`); si se omite
    se carga con include_excluded=True porque este ETL necesita todas las filas, no solo el universo auditado de
    forma independiente (esa distincion solo importa para el respaldo de CONFLICT en build_conflicts.py: el
    documento excluido paso las mismas verificaciones automaticas de schema y citas que el resto).
    ``case_unit_rows`` son las filas de la revision de unidad de caso; si se omite se leen de
    `config/document_case_unit_review.json`.
    """
    source_db = Path(source_db)
    output_db = Path(output_db)
    if source_db.resolve() == output_db.resolve():
        raise ValueError("output_db debe ser distinto de source_db; no se sobreescribe el warehouse base")
    if not source_db.exists():
        raise FileNotFoundError(source_db)

    if records is None:
        records = load_enrichment_records(include_excluded=True)
    if not records:
        raise ValueError("No hay registros de enrichment para procesar (records vacio).")

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

    if case_unit_rows is None:
        case_unit_rows = load_document_case_unit_review(DOCUMENT_CASE_UNIT_REVIEW_PATH)
    counts["document_case_unit_rows"] = _load_document_case_unit(conn, case_unit_rows)

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
        print(f"ERROR ETL enrichment: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output_db": str(args.output_db), **counts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
