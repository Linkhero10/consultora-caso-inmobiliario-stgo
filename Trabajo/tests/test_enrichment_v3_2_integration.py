"""Pruebas de contrato e integración para enrichment v3.2.

Estas pruebas son intencionalmente pequeñas y no llaman a ninguna API.
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "Trabajo" / "scripts"))

import build_enrichment_tables_v3_2 as etl  # noqa: E402
import enrich_case_v3 as enrich  # noqa: E402


def _record():
    return {
        "url": "https://example.cl/multi",
        "nombre_proyecto": "Proyecto A",
        "proyectos_mencionados": ["Proyecto A", "Proyecto B"],
        "objeto_disputa_norm": "permiso",
        "objeto_disputa_raw": "permiso de edificación",
        "evidencia_objeto_disputa": "permiso de edificación de Proyecto A",
        "evidencia_objeto_disputa_verificada": True,
        "tipo_accion": "recurso_judicial",
        "escala_conflicto": "local",
        "actores": [{
            "nombre": "Vecinos",
            "tipo": "colectivo_vecinal",
            "rol": "demandante",
            "stance": "se_opone",
            "nivel_involucramiento": "central",
            "cita": "Vecinos demandaron a Proyecto A",
            "cita_verificada": True,
            "proyecto_asociado": "Proyecto A",
        }],
        "instituciones_mencionadas": [{
            "nombre": "Municipio",
            "tipo_norm": "municipio_alcaldia",
            "rol_en_texto": "revisó el permiso de Proyecto B",
            "accion_institucional": "revisó el permiso",
            "cita": "Municipio revisó el permiso de Proyecto B",
            "cita_verificada": True,
            "proyecto_asociado": "Proyecto B",
        }],
        "institucion_decisora_segun_fuente": "no_afirmado_por_la_fuente",
        "instrumento_norm": "permiso_edificacion",
        "instrumento_raw": "Permiso N° 1",
        "via_legal_norm": "judicial",
        "resultado_actuacion": "pendiente",
        "tipo_evidencia_fuente": "mixta",
        "triage_consistency_check": False,
        "triage_consistency_note": "",
        "linea_tiempo": [{
            "fecha": "2024",
            "date_precision": "año",
            "descripcion": "Se impugnó el permiso de Proyecto A",
            "tipo_hito": "querella_accion_judicial",
            "evidencia_hito": "En 2024 se impugnó el permiso de Proyecto A",
            "evidencia_hito_verificada": True,
            "fecha_year_grounded": True,
            "proyecto_asociado": "Proyecto A",
        }],
        "ubicacion_especifica": "Calle 1",
        "explicacion_tipo_conflicto": "El texto disputa un permiso.",
        "explicacion_actores": "Los vecinos demandan.",
        "revision": {"nivel": "ninguno", "campos_afectados": [], "motivo": ""},
        "actores_posiblemente_truncados": False,
        "instituciones_posiblemente_truncadas": False,
        "hitos_posiblemente_truncados": False,
        "decision_documento_etapa1": "include",
        "contract_version_etapa1": "v5.2.3",
        "enrichment_schema_version": "v3.2",
        "run_id": "test-run",
    }


def test_project_associations_are_sanitized_not_discarded():
    """Hallazgo real del usuario (2026-09-17, corrida completa de 934):
    proyecto_asociado invalido cuarentenaba el registro ENTERO (68/869,
    todos el mismo patron de basura de generacion en actores[11]).
    sanitize_project_associations() ahora limpia SOLO el campo malo
    (preserva el original, marca verificada=False) en vez de descartar
    todo el documento -- mismo patron que las citas no verificadas."""
    clean = enrich.sanitize_project_associations(_record())
    assert clean["actores"][0]["proyecto_asociado_verificada"] is True

    bad = _record()
    bad["actores"][0]["proyecto_asociado"] = "Proyecto inexistente"
    sanitized = enrich.sanitize_project_associations(bad)
    actor = sanitized["actores"][0]
    assert actor["proyecto_asociado"] == ""
    assert actor["proyecto_asociado_original_modelo"] == "Proyecto inexistente"
    assert actor["proyecto_asociado_verificada"] is False
    # El resto del registro sigue intacto -- no se descarta nada mas.
    assert sanitized["nombre_proyecto"] == bad["nombre_proyecto"]
    assert enrich.validate_record_invariants(sanitized) == []


def test_project_associations_normalize_whitespace_on_match():
    """Hallazgo real (Luna, 2026-09-17, auditoria post-934, 3/934 casos):
    cuando proyecto_asociado coincidia con proyectos_mencionados solo
    despues de strip(), se guardaba el string crudo (con espacios
    sobrantes) en vez del valor normalizado -- podia romper joins exactos
    aunque la verificacion semantica fuera correcta."""
    record = _record()
    record["actores"][0]["proyecto_asociado"] = "Proyecto A  "
    sanitized = enrich.sanitize_project_associations(record)
    actor = sanitized["actores"][0]
    assert actor["proyecto_asociado"] == "Proyecto A"
    assert actor["proyecto_asociado_verificada"] is True


def test_semantic_invariants_reject_inconsistent_verified_fields():
    record = _record()
    assert enrich.validate_record_invariants(record) == []

    bad_revision = _record()
    bad_revision["revision"] = {"nivel": "ninguno", "campos_afectados": ["actores"], "motivo": "duda"}
    assert any("revision.nivel=ninguno" in e for e in enrich.validate_record_invariants(bad_revision))

    bad_quote = _record()
    bad_quote["actores"][0]["cita"] = ""
    assert any("cita_verificada=true" in e for e in enrich.validate_record_invariants(bad_quote))

    bad_hito = _record()
    bad_hito["linea_tiempo"][0]["evidencia_hito"] = ""
    assert any("evidencia_hito_verificada=true" in e for e in enrich.validate_record_invariants(bad_hito))


def test_v3_2_record_contract_requires_its_own_hash():
    schema_path = PROJECT_ROOT / "Trabajo" / "config" / "enrichment_record_schema_v3_2.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "record_schema_sha256" in schema["required"]


def test_v3_2_etl_round_trip_preserves_project_and_analytical_fields(tmp_path):
    source_db = tmp_path / "source.sqlite"
    output_db = tmp_path / "warehouse_v3_2.sqlite"
    enrichment_path = tmp_path / "enrichment.jsonl"
    conn = sqlite3.connect(source_db)
    conn.execute("CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT NOT NULL)")
    conn.execute("INSERT INTO document VALUES (?, ?)", ("doc-1", "https://example.cl/multi"))
    conn.commit()
    conn.close()
    enrichment_path.write_text(json.dumps(_record(), ensure_ascii=False) + "\n", encoding="utf-8")

    counts = etl.build_database(source_db, enrichment_path, output_db)

    assert counts["documents"] == 1
    db = sqlite3.connect(output_db)
    assert db.execute("SELECT proyectos_mencionados_json FROM enrichment_document_v3_2").fetchone()[0] == json.dumps(["Proyecto A", "Proyecto B"], ensure_ascii=False)
    assert db.execute("SELECT proyecto_asociado FROM enrichment_actor_v3_2").fetchone()[0] == "Proyecto A"
    assert db.execute("SELECT proyecto_asociado FROM enrichment_institucion_v3_2").fetchone()[0] == "Proyecto B"
    assert db.execute("SELECT proyecto_asociado FROM enrichment_evento_v3_2").fetchone()[0] == "Proyecto A"
    assert db.execute("SELECT objeto_disputa_raw, instrumento_raw, ubicacion_especifica FROM enrichment_document_v3_2").fetchone() == ("permiso de edificación", "Permiso N° 1", "Calle 1")
    assert db.execute("SELECT COUNT(*) FROM enrichment_project_mention_v3_2").fetchone()[0] == 2
    db.close()
