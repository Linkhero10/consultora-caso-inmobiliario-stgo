import sqlite3
import json
import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import build_geography as target  # noqa: E402
import geocode_locations  # noqa: E402


def _build_fixture_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE case_mention(case_mention_id TEXT, document_id TEXT, mention_index INTEGER, comuna TEXT, codigo_comuna_ine TEXT, tipo_objeto_norm TEXT, decision_final_amplio TEXT, decision_final_residencial TEXT);
        CREATE TABLE evidence(evidence_id TEXT, document_id TEXT, case_mention_id TEXT, quote_role TEXT, quote_index INTEGER, quote_text TEXT, verified INTEGER);
        CREATE TABLE document_conflict(document_id TEXT, conflict_id TEXT, role TEXT, evidence_json TEXT, source TEXT, unidad_caso_tipo TEXT);
        CREATE TABLE enrichment_project_mention(project_mention_id TEXT, document_id TEXT, idx INTEGER, nombre_proyecto TEXT, case_mention_index INTEGER, case_mention_id TEXT);
        CREATE TABLE case_mention_duplicate_link(case_mention_id TEXT, document_id TEXT, duplicate_group_id TEXT, canonical_case_mention_id TEXT, group_size INTEGER, match_method TEXT, decision_mixed_in_group INTEGER);
        """
    )
    # Caso 1: comuna simple ya conocida, resuelve.
    con.execute("INSERT INTO case_mention VALUES ('cm1','doc1',0,'Ñuñoa','','edificio_residencial','include','include')")
    # Caso 2: comuna compuesta con dos comunas del area de estudio -- ambiguo, no se resuelve.
    con.execute("INSERT INTO case_mention VALUES ('cm2','doc2',0,'Ñuñoa y Providencia','','edificio_residencial','include','include')")
    # Caso 3: comuna fuera del area de estudio -- no se resuelve.
    con.execute("INSERT INTO case_mention VALUES ('cm3','doc3',0,'Viña del Mar','','edificio_residencial','include','include')")
    # Caso 4: ya tiene codigo_comuna_ine -- no se toca (no es candidato).
    con.execute("INSERT INTO case_mention VALUES ('cm4','doc4',0,'Santiago','13101','edificio_residencial','include','include')")
    con.executemany(
        "INSERT INTO evidence VALUES (?,?,?,?,?,?,?)",
        [
            ("ev1", "doc1", "cm1", "geografica", 0, "Lo Curro", 1),
            ("ev2", "doc1", "cm1", "geografica", 1, "Ñuñoa", 1),  # comuna pura -> se omite
            ("ev3", "doc1", "cm1", "geografica", 2, "Monterrey, Nuevo León", 0),  # no verificado -> se omite
        ],
    )
    con.execute("INSERT INTO document_conflict VALUES ('doc1','conflict:1','focal','{}','test','caso_unico')")

    # Caso 5: comuna cruda compuesta ("Ñuñoa y Providencia") pero YA resuelta
    # de forma determinista en case_mention_geography a Providencia -- el
    # contexto del geocoder debe usar esa comuna resuelta, nunca el texto
    # crudo compuesto (que ni siquiera calzaria como clave de comuna).
    con.execute("INSERT INTO case_mention VALUES ('cm5','doc5',0,'Ñuñoa y Providencia','','edificio_residencial','include','include')")
    con.execute("INSERT INTO evidence VALUES ('ev5','doc5','cm5','geografica',0,'Lo Curro',1)")
    con.execute("INSERT INTO document_conflict VALUES ('doc5','conflict:2','focal','{}','test','caso_unico')")

    # Caso 6: documento con DOS conflictos distintos -- el geocode debe
    # crearse, pero el bridge a conflicto NO (no hay forma de saber a cual
    # de los dos pertenece la mencion geografica especifica).
    con.execute("INSERT INTO case_mention VALUES ('cm6','doc6',0,'Vitacura','13132','edificio_residencial','include','include')")
    con.execute("INSERT INTO evidence VALUES ('ev6','doc6','cm6','geografica',0,'Lo Curro',1)")
    con.execute("INSERT INTO document_conflict VALUES ('doc6','conflict:3','focal','{}','test','caso_unico')")
    con.execute("INSERT INTO document_conflict VALUES ('doc6','conflict:4','co_focal','{}','test','caso_unico')")

    con.commit()
    con.close()


def _fake_index():
    def row(name, comuna, place_type="Centro Poblado", lat="-33.36", lon="-70.58", source="Toponimos_BCN"):
        return {"name": name, "norm_name": geocode_locations._norm(name), "place_type": place_type, "comuna": comuna, "lat": lat, "lon": lon, "source": source}

    index = {}
    for r in (row("Lo Curro", "VITACURA"), row("Monterrey", "SANTA JUANA", lat="-37.0", lon="-72.0")):
        index.setdefault(r["norm_name"], []).append(r)
    return index


def test_backfill_case_mention_geography_only_resolves_unambiguous_in_area(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    target.ensure_schema(con)
    report = target.backfill_case_mention_geography(con)

    rows = {r["case_mention_id"]: r["codigo_comuna_ine"] for r in con.execute("SELECT * FROM case_mention_geography")}
    assert rows == {"cm1": "13120"}  # solo Ñuñoa se resuelve
    assert "cm2" not in rows  # ambiguo (2 comunas)
    assert "cm3" not in rows  # fuera del area de estudio
    assert "cm4" not in rows  # ya tenia codigo, no era candidato
    assert report["n_resueltos"] == 1


def test_geocode_evidence_locations_skips_bare_comuna_and_unverified(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    target.ensure_schema(con)

    with patch.object(geocode_locations, "load_index", return_value=_fake_index()):
        report = target.geocode_evidence_locations(con)

    located = list(con.execute("SELECT * FROM geocoded_location WHERE document_id = 'doc1'"))
    assert len(located) == 1
    assert located[0]["matched_name"] == "Lo Curro"
    assert located[0]["comuna"] == "VITACURA"
    # el bridge liga el geocode al conflicto del documento (contextual, no focal)
    bridge = list(con.execute("SELECT * FROM geocoded_location_conflict WHERE geocode_id = ?", (located[0]["geocode_id"],)))
    assert bridge[0]["conflict_id"] == "conflict:1"
    assert bridge[0]["relation_type"] == "contextual_location"
    assert report["n_omitidas_por_ser_comuna_pura"] == 1  # "Ñuñoa"
    assert report["n_evidencia_geografica_total"] == 4  # solo evidencia verified=1 (ev1,ev2,ev5,ev6)


def test_geocode_context_uses_resolved_comuna_not_raw_compound_text(tmp_path):
    """Bug real encontrado en revisión externa: el contexto de comuna debe
    venir de una comuna ya resuelta (case_mention_geography), nunca del
    texto crudo del clasificador ("Ñuñoa y Providencia"). cm5 se resuelve a
    Providencia, pero el único "Lo Curro" del gazetteer de prueba está en
    Vitacura -- con el contexto correcto (Providencia) no debe calzar
    ninguno; el bug anterior habría ignorado el contexto (porque el texto
    crudo compuesto no calza como clave de comuna) y habría caído al
    fallback nacional, resolviendo incorrectamente a Vitacura."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    target.ensure_schema(con)
    con.execute(
        "INSERT INTO case_mention_geography VALUES ('cm5','13123','exact_comuna_lookup','comuna','alta_determinista')"
    )
    con.commit()

    with patch.object(geocode_locations, "load_index", return_value=_fake_index()):
        target.geocode_evidence_locations(con)

    doc5_rows = list(con.execute("SELECT * FROM geocoded_location WHERE document_id = 'doc5'"))
    assert doc5_rows == []


def test_bridge_not_created_when_document_has_multiple_conflicts(tmp_path):
    """Bug real encontrado en revisión externa: vincular por document_id a
    TODOS los conflictos del documento reintroduce el mismo producto
    cartesiano ya corregido en dashboard_data.py. El geocode debe existir,
    pero sin bridge cuando hay más de un conflicto candidato."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    target.ensure_schema(con)

    with patch.object(geocode_locations, "load_index", return_value=_fake_index()):
        report = target.geocode_evidence_locations(con)

    doc6_geocode = con.execute("SELECT geocode_id FROM geocoded_location WHERE document_id = 'doc6'").fetchone()
    assert doc6_geocode is not None  # el geocode si se crea
    bridge = con.execute(
        "SELECT * FROM geocoded_location_conflict WHERE geocode_id = ?", (doc6_geocode["geocode_id"],)
    ).fetchall()
    assert bridge == []  # pero sin bridge, por ambigüedad de conflicto
    assert report["n_bridge_omitido_multiconflicto"] == 1


def test_geocode_evidence_locations_discards_out_of_area_homonyms(tmp_path):
    """Caso real encontrado en la revisión manual: 'Monterrey, Nuevo León'
    calza (por unicidad nacional) con un homónimo chileno en Santa Juana,
    fuera del área de estudio -- debe descartarse, no reportarse como
    resuelto."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    target.ensure_schema(con)
    con.execute("UPDATE evidence SET verified = 1 WHERE evidence_id = 'ev3'")
    con.commit()

    with patch.object(geocode_locations, "load_index", return_value=_fake_index()):
        report = target.geocode_evidence_locations(con)

    matched_names = {r["matched_name"] for r in con.execute("SELECT * FROM geocoded_location")}
    assert "Monterrey" not in matched_names
    assert report["n_descartadas_fuera_del_area_de_estudio"] == 1


# --- Fix 1F (2026-09-26): geografia real de proyectos por case_mention ---


def test_project_mention_geography_direct_match(tmp_path):
    """cm4 ya tiene codigo_comuna_ine directo y decision_final_amplio=include
    -- una mencion de proyecto que apunta a cm4 debe resolver 'direct'."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Torre Santiago',0,'cm4')")
    con.commit()

    report = target.build_project_mention_geography(con)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "direct"
    assert row["case_mention_id"] == "cm4"
    assert row["codigo_comuna_ine"] == "13101"
    assert report["direct"] == 1


def test_project_mention_geography_no_case_mention_index(tmp_path):
    """case_mention_index nulo (v3.3 no vinculo la mencion a ningun
    case_mention) -- nunca se adivina, queda explicito sin comuna."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Proyecto Ambiguo',NULL,NULL)")
    con.commit()

    target.build_project_mention_geography(con)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "no_case_mention_index"
    assert row["case_mention_id"] is None
    assert row["codigo_comuna_ine"] is None


def test_project_mention_geography_case_mention_no_incluido(tmp_path):
    """El indice apunta a un case_mention real, pero su decision_final_amplio
    no es 'include' -- no se usa su comuna, se marca explicito."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("UPDATE case_mention SET decision_final_amplio='exclude' WHERE case_mention_id='cm4'")
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Torre Santiago',0,'cm4')")
    con.commit()

    target.build_project_mention_geography(con)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "case_mention_no_incluido"
    assert row["codigo_comuna_ine"] is None


def test_project_mention_geography_case_mention_sin_comuna(tmp_path):
    """El case_mention esta incluido pero no tiene ninguna comuna resuelta
    (ni codigo_comuna_ine directo ni backfill) -- explicito, no se inventa."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO case_mention VALUES ('cm_sin_comuna','doc7',0,'','','edificio_residencial','include','include')"
    )
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc7:project:0','doc7',0,'Proyecto X',0,'cm_sin_comuna')")
    con.commit()

    target.build_project_mention_geography(con)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc7:project:0'").fetchone()
    assert row["match_method"] == "case_mention_sin_comuna"
    assert row["codigo_comuna_ine"] is None


def test_project_mention_geography_via_duplicate_group_sibling(tmp_path):
    """Fix 1E: el case_mention que v3.3 indico no esta incluido, pero un
    hermano de su grupo de duplicados si y tiene comuna resuelta -- se usa
    el hermano, marcado explicito como via_duplicate_group."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO case_mention VALUES ('cm4b','doc4',1,'','','edificio_residencial','exclude','exclude')"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4','doc4','g1','cm4',2,'quote_substring',0)"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4b','doc4','g1','cm4',2,'quote_substring',0)"
    )
    # v3.3 apunto a cm4b (excluido); su hermano cm4 SI esta incluido y tiene comuna.
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Torre Santiago',1,'cm4b')")
    con.commit()

    target.build_project_mention_geography(con)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "via_duplicate_group"
    assert row["case_mention_id"] == "cm4"
    assert row["codigo_comuna_ine"] == "13101"


def test_project_mention_geography_mixed_duplicate_group_requires_review(tmp_path):
    """Un grupo con decisiones include/exclude no puede transferir comuna
    automaticamente desde un hermano incluido al indice excluido."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO case_mention VALUES ('cm4b','doc4',1,'','','edificio_residencial','exclude','exclude')"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4','doc4','g1','cm4',2,'quote_substring',1)"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4b','doc4','g1','cm4',2,'quote_substring',1)"
    )
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Villa X',1,'cm4b')")
    con.commit()

    report = target.build_project_mention_geography(con)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "ambiguous_duplicate_group"
    assert row["case_mention_id"] == "cm4b"
    assert row["codigo_comuna_ine"] is None
    assert report["ambiguous_duplicate_group"] == 1
    assert report["ambiguous_duplicate_group_rows"] == [
        {
            "document_id": "doc4",
            "project_mention_id": "doc4:project:0",
            "nombre_proyecto": "Villa X",
            "source_case_mention_id": "cm4b",
            "duplicate_group_id": "g1",
        }
    ]


def test_project_mention_geography_mixed_duplicate_group_uses_reviewed_mapping(tmp_path):
    """Solo una adjudicacion explicita y acotada puede permitir el fallback
    desde una mention excluida a su hermano incluido dentro de un grupo mixto."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO case_mention VALUES ('cm4b','doc4',1,'','','edificio_residencial','exclude','exclude')"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4','doc4','g1','cm4',2,'quote_substring',1)"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4b','doc4','g1','cm4',2,'quote_substring',1)"
    )
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Villa X',1,'cm4b')")
    con.commit()

    reviewed_links = {
        "doc4:project:0": {
            "document_id": "doc4",
            "source_case_mention_id": "cm4b",
            "duplicate_group_id": "g1",
            "resolved_case_mention_id": "cm4",
            "status": "reviewed_geography_only",
        }
    }
    report = target.build_project_mention_geography(con, reviewed_duplicate_links=reviewed_links)

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "via_reviewed_duplicate_group"
    assert row["case_mention_id"] == "cm4"
    assert row["codigo_comuna_ine"] == "13101"
    assert report["via_reviewed_duplicate_group"] == 1


def test_project_mention_geography_rejects_unreviewed_override_for_mixed_group(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO case_mention VALUES ('cm4b','doc4',1,'','','edificio_residencial','exclude','exclude')"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4','doc4','g1','cm4',2,'quote_substring',1)"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4b','doc4','g1','cm4',2,'quote_substring',1)"
    )
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Villa X',1,'cm4b')")
    con.commit()

    unreviewed_links = {
        "doc4:project:0": {
            "document_id": "doc4",
            "source_case_mention_id": "cm4b",
            "duplicate_group_id": "g1",
            "resolved_case_mention_id": "cm4",
            "status": "proposed",
        }
    }
    with pytest.raises(ValueError, match="sin estado reviewed_geography_only"):
        target.build_project_mention_geography(con, reviewed_duplicate_links=unreviewed_links)


def test_project_mention_geography_clean_duplicate_group_keeps_existing_fallback(tmp_path):
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute(
        "INSERT INTO case_mention VALUES ('cm4b','doc4',1,'','','edificio_residencial','exclude','exclude')"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4','doc4','g1','cm4',2,'quote_substring',0)"
    )
    con.execute(
        "INSERT INTO case_mention_duplicate_link VALUES ('cm4b','doc4','g1','cm4',2,'quote_substring',0)"
    )
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Villa X',1,'cm4b')")
    con.commit()

    target.build_project_mention_geography(con, reviewed_duplicate_links={})

    row = con.execute("SELECT * FROM project_mention_geography WHERE project_mention_id='doc4:project:0'").fetchone()
    assert row["match_method"] == "via_duplicate_group"
    assert row["case_mention_id"] == "cm4"
    assert row["codigo_comuna_ine"] == "13101"


def test_project_mention_geography_report_counts_match_persisted_rows(tmp_path):
    """El reporte devuelto nunca debe estar hardcodeado -- se recalcula
    desde las filas realmente insertadas."""
    db_path = tmp_path / "warehouse.sqlite"
    _build_fixture_db(db_path)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:0','doc4',0,'Torre Santiago',0,'cm4')")
    con.execute("INSERT INTO enrichment_project_mention VALUES ('doc4:project:1','doc4',1,'Proyecto Ambiguo',NULL,NULL)")
    con.commit()

    report = target.build_project_mention_geography(con)

    total_persisted = con.execute("SELECT COUNT(*) FROM project_mention_geography").fetchone()[0]
    assert report["n_menciones_total"] == total_persisted == 2
    assert report["direct"] == 1
    assert report["ambiguous_duplicate_group_rows"] == []
    assert report["no_case_mention_index"] == 1


def test_main_writes_hash_pinned_geography_report(tmp_path, monkeypatch):
    db_path = tmp_path / "warehouse.sqlite"
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE case_mention(case_mention_id TEXT, document_id TEXT, mention_index INTEGER, comuna TEXT, codigo_comuna_ine TEXT, tipo_objeto_norm TEXT, decision_final_amplio TEXT, decision_final_residencial TEXT);
        CREATE TABLE enrichment_project_mention(project_mention_id TEXT, document_id TEXT, idx INTEGER, nombre_proyecto TEXT, case_mention_index INTEGER, case_mention_id TEXT);
        CREATE TABLE evidence(evidence_id TEXT, document_id TEXT, case_mention_id TEXT, quote_role TEXT, quote_index INTEGER, quote_text TEXT, verified INTEGER);
        CREATE TABLE document_conflict(document_id TEXT, conflict_id TEXT, role TEXT, evidence_json TEXT, source TEXT, unidad_caso_tipo TEXT);
        INSERT INTO case_mention VALUES ('cm1','doc1',0,'Santiago','13101','edificio_residencial','include','include');
        INSERT INTO enrichment_project_mention VALUES ('doc1:project:0','doc1',0,'Proyecto A',0,'cm1');
        """
    )
    con.commit()
    con.close()
    report_path = tmp_path / "project_mention_geography_report.json"
    review_config_path = tmp_path / "reviewed_links.json"
    review_config_path.write_text(json.dumps({"schema_version": "1.0", "links": []}), encoding="utf-8")
    monkeypatch.setattr(target, "PROJECT_MENTION_GEOGRAPHY_REPORT_PATH", report_path)
    monkeypatch.setattr(target, "REVIEWED_DUPLICATE_GROUP_GEOGRAPHY_PATH", review_config_path)

    assert target.main(db_path) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run_id"]
    assert report["build_commit"] == target._git_head()
    assert report["review_config_sha256"] == hashlib.sha256(review_config_path.read_bytes()).hexdigest()
    assert report["input_warehouse_sha256"]
    assert report["output_warehouse_sha256"] == hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert report["direct"] == 1
    assert report["case_mention_geography"]["n_resueltos"] == 0
    assert report["geocoded_location"]["n_resueltas"] == 0
