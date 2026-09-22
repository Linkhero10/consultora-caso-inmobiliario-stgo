import json
import re
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
        CREATE TABLE conflict(conflict_id TEXT, label TEXT, n_case_ids INTEGER, origen TEXT, confidence TEXT, respaldo_evidencia TEXT);
        CREATE TABLE conflict_project(conflict_id TEXT, project_id TEXT, case_id TEXT);
        CREATE TABLE document_conflict(document_id TEXT, conflict_id TEXT, role TEXT, evidence_json TEXT, source TEXT, unidad_caso_tipo TEXT);
        CREATE TABLE document_case_unit(document_id TEXT, unidad_caso_tipo TEXT, tiene_error INTEGER, correccion_nombre_proyecto TEXT, correccion_proyectos_mencionados_json TEXT, correccion_ubicacion_especifica TEXT, nota_sol TEXT, revisado_por TEXT);
        CREATE TABLE enrichment_actor(actor_id TEXT, document_id TEXT, idx INTEGER, nombre TEXT, tipo TEXT, rol TEXT, stance TEXT, nivel_involucramiento TEXT, proyecto_asociado TEXT, cita TEXT, cita_original_modelo TEXT, cita_verificada INTEGER, evidence_id TEXT);
        CREATE TABLE enrichment_institution(institucion_id TEXT, document_id TEXT, idx INTEGER, nombre TEXT, tipo_norm TEXT, rol_en_texto TEXT, accion_institucional TEXT, proyecto_asociado TEXT, cita TEXT, cita_original_modelo TEXT, cita_verificada INTEGER, evidence_id TEXT);
        CREATE TABLE enrichment_event(event_id TEXT, document_id TEXT, idx INTEGER, fecha TEXT, date_precision TEXT, descripcion TEXT, tipo_hito TEXT, proyecto_asociado TEXT, fecha_year_grounded INTEGER, evidencia_hito TEXT, evidencia_hito_original_modelo TEXT, evidencia_hito_verificada INTEGER, evidence_id TEXT, nombre_proyecto_documento TEXT, revision_nivel_documento TEXT);
        CREATE TABLE actor_event_project_link(link_id TEXT, source_table TEXT, source_id TEXT, document_id TEXT, nombre TEXT, proyecto_asociado_raw TEXT, project_id TEXT, resolution_status TEXT, source_pass TEXT);
        CREATE TABLE actor_registry(entity_id TEXT, entity_key TEXT, canonical_label TEXT, n_alias INTEGER, tipo TEXT);
        CREATE TABLE actor_alias(nombre_norm TEXT, entity_id TEXT, fuente TEXT, razon TEXT);

        CREATE VIEW document_conflict_case_safe AS
            SELECT * FROM document_conflict
            WHERE unidad_caso_tipo = 'caso_unico' AND role IN ('focal', 'co_focal');

        CREATE VIEW actor_event_project_link_conflict_safe AS
            SELECT l.*, cp.conflict_id AS conflict_id
            FROM actor_event_project_link l
            JOIN conflict_project cp ON cp.project_id = l.project_id
            JOIN document_conflict_case_safe dcs ON dcs.document_id = l.document_id AND dcs.conflict_id = cp.conflict_id
            WHERE l.resolution_status = 'resolved_explicit';
        """
    )
    con.execute(
        "INSERT INTO territory VALUES ('13101','SANTIAGO',400000,100000,150000,10000,500,'{\"type\":\"Polygon\",\"coordinates\":[[[0,0],[0,1],[1,1],[1,0],[0,0]]]}')"
    )
    con.execute(
        "INSERT INTO territory VALUES ('13102','PROVIDENCIA',100000,20000,40000,500,100,'{\"type\":\"Polygon\",\"coordinates\":[[[2,2],[2,3],[3,3],[3,2],[2,2]]]}')"
    )

    # doc1: caso_unico, focal, comuna unica (Santiago) -- caso "limpio" de referencia.
    con.execute("INSERT INTO document VALUES ('doc1','https://a.cl','2026-01-01','2026-01-02','Titulo A','{}','include','v1','include')")
    con.execute("INSERT INTO case_mention VALUES ('doc1:0','doc1',0,'Santiago','13101','edificio_residencial','include','include')")
    con.execute("INSERT INTO evidence VALUES ('doc1:0:0','doc1','doc1:0','accion',0,'Cita de prueba verificada.',1)")
    con.execute("INSERT INTO event VALUES ('event:doc1:0','doc1','https://a.cl','2026-01-01','Descripcion de hito','permiso_autorizacion',1,'Proyecto A')")
    con.execute("INSERT INTO project VALUES ('proj1','Proyecto A','proyecto a','[]',1,1,NULL,'case1')")
    con.execute("INSERT INTO project_mention_resolved VALUES ('doc1','Proyecto A','proj1')")
    con.execute("INSERT INTO conflict VALUES ('conflict:1','Proyecto A',1,'trivial_single_case','baja_derivado_mecanicamente','respaldo_exact_quote_detectado')")
    con.execute("INSERT INTO conflict_project VALUES ('conflict:1','proj1','case1')")
    con.execute("INSERT INTO document_conflict VALUES ('doc1','conflict:1','focal','{}','test','caso_unico')")
    con.execute("INSERT INTO document_case_unit VALUES ('doc1','caso_unico',0,NULL,NULL,NULL,NULL,NULL)")
    con.execute("INSERT INTO enrichment_actor VALUES ('a1','doc1',0,'Vecino X','ciudadano_individual','mencionado','se_opone','central','','cita','',1,'e1')")
    con.execute("INSERT INTO enrichment_event VALUES ('ev1','doc1',0,'2026-01-01','dia','Descripcion de hito enrich','permiso_autorizacion','',1,'cita evento','',1,'e2','Proyecto A','ninguno')")
    con.execute(
        "INSERT INTO actor_event_project_link VALUES ('l1','enrichment_actor','a1','doc1','Vecino X','Proyecto A','proj1','resolved_explicit','first')"
    )
    con.execute(
        "INSERT INTO actor_event_project_link VALUES ('l2','enrichment_event','ev1','doc1','','Proyecto A','proj1','resolved_explicit','first')"
    )

    # doc2: mismo conflict:1, pero MEZCLA dos comunas distintas -- no debe
    # aportar comuna a ningun lado (blocker 1: no inventar precision).
    con.execute("INSERT INTO document VALUES ('doc2','https://b.cl','2026-01-01','2026-01-02','Titulo B','{}','include','v1','include')")
    con.execute("INSERT INTO case_mention VALUES ('doc2:0','doc2',0,'Santiago','13101','edificio_residencial','include','include')")
    con.execute("INSERT INTO case_mention VALUES ('doc2:1','doc2',1,'Providencia','13102','edificio_residencial','include','include')")
    con.execute("INSERT INTO document_conflict VALUES ('doc2','conflict:1','co_focal','{}','test','caso_unico')")
    con.execute("INSERT INTO document_case_unit VALUES ('doc2','caso_unico',0,NULL,NULL,NULL,NULL,NULL)")

    # doc3: mencion NO focal (mentioned_unreviewed) del mismo conflict:1 --
    # su actor (Vecino Y) NO debe filtrarse al detalle principal (blocker 2).
    con.execute("INSERT INTO document VALUES ('doc3','https://c.cl','2026-01-01','2026-01-02','Titulo C','{}','include','v1','include')")
    con.execute("INSERT INTO case_mention VALUES ('doc3:0','doc3',0,'Ñuñoa','13120','edificio_residencial','include','include')")
    con.execute("INSERT INTO document_conflict VALUES ('doc3','conflict:1','mentioned_unreviewed','{}','test','caso_unico')")
    con.execute("INSERT INTO document_case_unit VALUES ('doc3','caso_unico',0,NULL,NULL,NULL,NULL,NULL)")
    con.execute("INSERT INTO enrichment_actor VALUES ('a2','doc3',0,'Vecino Y','ciudadano_individual','mencionado','se_opone','central','','cita','',1,'e3')")

    con.execute("INSERT INTO territory VALUES ('13120','ÑUÑOA',150000,20000,50000,2000,100,'{\"type\":\"Polygon\",\"coordinates\":[[[4,4],[4,5],[5,5],[5,4],[4,4]]]}')")

    con.commit()
    con.close()


def test_build_dashboard_dataset_end_to_end(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    data = target.build_dashboard_dataset(db_path)

    assert data["summary"]["n_documents"] == 3
    assert data["summary"]["n_conflicts_total"] == 1
    assert data["summary"]["n_conflicts_evidence_backed"] == 1
    assert data["summary"]["n_conflicts_without_exact_backing"] == 0

    conflict = data["conflicts"][0]
    assert conflict["label"] == "Proyecto A"
    # Solo doc1 (focal, comuna unica) aporta comuna -- doc2 esta descartado
    # por ambiguo y doc3 no es focal/co_focal.
    assert conflict["comunas"] == [{"codigo_comuna_ine": "13101", "comuna": "Santiago"}]
    assert conflict["projects"] == [{"project_id": "proj1", "nombre": "Proyecto A", "n_documents": 1}]
    assert conflict["respaldo_evidencia"] == "respaldo_exact_quote_detectado"
    assert conflict["coverage_backing"] == "total"
    assert conflict["n_projects_backed"] == 1
    assert conflict["n_projects_unbacked"] == 0
    assert conflict["evidence_quotes_sample"] == ["Cita de prueba verificada."]

    # Actor resuelto via actor_event_project_link_conflict_safe (doc1, focal).
    actor_names = {a["nombre"] for a in conflict["actors"]}
    assert actor_names == {"Vecino X"}
    assert "Vecino Y" not in actor_names  # doc3 no es focal/co_focal

    # doc1 y doc2 son las menciones focales/co-focales; doc3 queda aparte.
    doc_ids = {d["document_id"] for d in conflict["documents"]}
    assert doc_ids == {"doc1", "doc2"}
    other_ids = {d["document_id"] for d in conflict["other_mentions"]}
    assert other_ids == {"doc3"}
    assert conflict["other_mentions"][0]["role"] == "mentioned_unreviewed"


def test_ambiguous_comuna_document_contributes_to_no_territory(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    data = target.build_dashboard_dataset(db_path)

    santiago = next(t for t in data["territories"] if t["codigo_comuna_ine"] == "13101")
    providencia = next(t for t in data["territories"] if t["codigo_comuna_ine"] == "13102")
    # conflict:1 tiene comuna resuelta via doc1 (Santiago) -- doc2 (ambiguo)
    # no debe sumar el mismo conflicto tambien a Providencia.
    assert santiago["n_conflicts_total"] == 1
    assert santiago["n_conflicts_backed"] == 1
    assert providencia["n_conflicts_total"] == 0
    assert providencia["n_conflicts_backed"] == 0


def test_non_focal_mentions_never_contribute_actors_or_events(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    data = target.build_dashboard_dataset(db_path)
    conflict = data["conflicts"][0]
    assert all(a["nombre"] != "Vecino Y" for a in conflict["actors"])


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


def test_no_sol_mentions_in_labels():
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    flat = json.dumps(labels, ensure_ascii=False).lower()
    assert not re.search(r"\bsol\b", flat)
