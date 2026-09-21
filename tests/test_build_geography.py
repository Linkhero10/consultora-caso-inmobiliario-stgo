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

    located = list(con.execute("SELECT * FROM geocoded_location"))
    assert len(located) == 1
    assert located[0]["matched_name"] == "Lo Curro"
    assert located[0]["comuna"] == "VITACURA"
    # el bridge liga el geocode al conflicto del documento (contextual, no focal)
    bridge = list(con.execute("SELECT * FROM geocoded_location_conflict"))
    assert bridge[0]["conflict_id"] == "conflict:1"
    assert bridge[0]["relation_type"] == "contextual_location"
    assert report["n_omitidas_por_ser_comuna_pura"] == 1  # "Ñuñoa"
    assert report["n_evidencia_geografica_total"] == 2  # solo evidencia verified=1


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
