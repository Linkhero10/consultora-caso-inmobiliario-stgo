import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

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
