import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import dashboard_data as target  # noqa: E402

LABELS_PATH = Path(__file__).parents[1] / "config" / "dashboard_labels.json"


def _build_fixture_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE document(document_id TEXT, url TEXT, fecha_publicacion TEXT, fetched_at TEXT, title TEXT, lineage_json TEXT, corpus_scope TEXT, contract_version TEXT, decision_documento TEXT);
        CREATE TABLE case_mention(case_mention_id TEXT, document_id TEXT, mention_index INTEGER, comuna TEXT, codigo_comuna_ine TEXT, tipo_objeto_norm TEXT, decision_final_amplio TEXT, decision_final_residencial TEXT);
        CREATE TABLE evidence(evidence_id TEXT, document_id TEXT, case_mention_id TEXT, quote_role TEXT, quote_index INTEGER, quote_text TEXT, verified INTEGER);
        CREATE TABLE territory(codigo_comuna_ine TEXT, comuna TEXT, poblacion INTEGER, inmigrantes INTEGER, hogares INTEGER, viviendas_hacinadas INTEGER, viviendas_irrecuperables INTEGER, geometry_json TEXT);
        CREATE TABLE event(event_id TEXT, document_id TEXT, url TEXT, fecha TEXT, descripcion TEXT, tipo_hito TEXT, fecha_year_grounded INTEGER, nombre_proyecto TEXT);
        CREATE TABLE project(project_id TEXT, canonical_name TEXT, normalized_name TEXT, aliases_json TEXT, n_documents INTEGER, n_mentions INTEGER, homonym_partition TEXT, case_id TEXT);
        CREATE TABLE project_mention_resolved(document_id TEXT, raw_nombre_proyecto TEXT, project_id TEXT);
        CREATE TABLE conflict(conflict_id TEXT, label TEXT, n_case_ids INTEGER, origen TEXT, confidence TEXT);
        CREATE TABLE conflict_project(conflict_id TEXT, project_id TEXT, case_id TEXT);
        CREATE TABLE document_conflict(document_id TEXT, conflict_id TEXT, role TEXT, evidence_json TEXT, source TEXT, unidad_caso_tipo TEXT);
        CREATE TABLE enrichment_actor(actor_id TEXT, document_id TEXT, idx INTEGER, nombre TEXT, tipo TEXT, rol TEXT, stance TEXT, nivel_involucramiento TEXT, proyecto_asociado TEXT, cita TEXT, cita_original_modelo TEXT, cita_verificada INTEGER, evidence_id TEXT);
        """
    )
    con.execute(
        "INSERT INTO territory VALUES ('13101','SANTIAGO',400000,100000,150000,10000,500,'{\"type\":\"Polygon\",\"coordinates\":[[[0,0],[0,1],[1,1],[1,0],[0,0]]]}')"
    )
    con.execute(
        "INSERT INTO territory VALUES ('13102','PROVIDENCIA',100000,20000,40000,500,100,'{\"type\":\"Polygon\",\"coordinates\":[[[2,2],[2,3],[3,3],[3,2],[2,2]]]}')"
    )
    con.execute("INSERT INTO document VALUES ('doc1','https://a.cl','2026-01-01','2026-01-02','Titulo A','{}','include','v1','include')")
    con.execute("INSERT INTO case_mention VALUES ('doc1:0','doc1',0,'Santiago','13101','edificio_residencial','include','include')")
    con.execute("INSERT INTO evidence VALUES ('doc1:0:0','doc1','doc1:0','accion',0,'Cita de prueba verificada.',1)")
    con.execute("INSERT INTO event VALUES ('event:doc1:0','doc1','https://a.cl','2026-01-01','Descripcion de hito','permiso_autorizacion',1,'Proyecto A')")
    con.execute("INSERT INTO project VALUES ('proj1','Proyecto A','proyecto a','[]',1,1,NULL,'case1')")
    con.execute("INSERT INTO project_mention_resolved VALUES ('doc1','Proyecto A','proj1')")
    con.execute("INSERT INTO conflict VALUES ('conflict:1','Proyecto A',1,'trivial_single_case','baja_derivado_mecanicamente')")
    con.execute("INSERT INTO conflict_project VALUES ('conflict:1','proj1','case1')")
    con.execute("INSERT INTO document_conflict VALUES ('doc1','conflict:1','focal','{}','test','caso_unico')")
    con.execute("INSERT INTO enrichment_actor VALUES ('a1','doc1',0,'Vecino X','ciudadano_individual','mencionado','se_opone','central','','cita','',1,'e1')")
    con.commit()
    con.close()


def test_build_dashboard_dataset_end_to_end(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    data = target.build_dashboard_dataset(db_path)

    assert data["summary"]["n_documents"] == 1
    assert data["summary"]["n_conflicts"] == 1

    santiago = next(t for t in data["territories"] if t["codigo_comuna_ine"] == "13101")
    assert santiago["n_conflicts"] == 1
    assert santiago["n_projects"] == 1
    assert santiago["n_conflicts_per_100k"] == round(1 / 400000 * 100_000, 2)

    providencia = next(t for t in data["territories"] if t["codigo_comuna_ine"] == "13102")
    assert providencia["n_conflicts"] == 0

    conflict = data["conflicts"][0]
    assert conflict["label"] == "Proyecto A"
    assert conflict["comunas"] == [{"codigo_comuna_ine": "13101", "comuna": "Santiago"}]
    assert conflict["projects"] == [{"project_id": "proj1", "nombre": "Proyecto A", "n_documents": 1}]
    assert conflict["actors"][0]["nombre"] == "Vecino X"
    assert conflict["evidence_quotes_sample"] == ["Cita de prueba verificada."]
    assert conflict["events"][0]["tipo_hito"] == "permiso_autorizacion"


def test_evidence_only_counts_verified_quotes(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.execute("INSERT INTO evidence VALUES ('doc1:0:1','doc1','doc1:0','objeto',0,'Cita no verificada.',0)")
    con.commit()
    con.close()

    data = target.build_dashboard_dataset(db_path)
    quotes = data["conflicts"][0]["evidence_quotes_sample"]
    assert "Cita no verificada." not in quotes


def test_all_enum_values_have_labels_in_real_warehouse():
    """Contra el warehouse real: ningún valor debe llegar al dashboard sin
    entrada humanizada en config/dashboard_labels.json."""
    if not target.WAREHOUSE_PATH.exists():
        import pytest

        pytest.skip("data/warehouse.sqlite no disponible")
    data = target.build_dashboard_dataset()
    found = target.enum_values_present(data)
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    missing = {}
    for category, values in found.items():
        gap = values - set(labels.get(category, {}).keys())
        if gap:
            missing[category] = gap
    assert not missing, f"Valores sin etiqueta humana: {missing}"
