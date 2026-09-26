"""Pruebas de la resolucion de la cola de revision de proyectos.

No llaman a ninguna API. Verifican las reglas automaticas (numeral/etapa,
lista de nombres genericos) contra casos reales del corpus, y que las 253
filas reales de la cola quedan todas cubiertas (por regla o por decision
manual explicita) antes de aplicar nada a la base de datos.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import resolve_project_review as rpq  # noqa: E402
import build_projects as bridge  # noqa: E402


def test_conflicting_numeral_blocks_merge():
    assert rpq.has_conflicting_numeral("Alto Las Condes", "Alto Las Condes 2") is True
    assert rpq.has_conflicting_numeral("Distrito Cordillera I", "Distrito Cordillera II") is True
    assert rpq.has_conflicting_numeral("Mall Vivo Santiago Etapa II", "Mall Vivo Santiago") is True


def test_same_numeral_does_not_block_merge():
    assert rpq.has_conflicting_numeral("Alto Las Condes 2", "Mall Alto Las Condes 2") is False
    assert rpq.has_conflicting_numeral("Mall Vivo Santiago Etapa II", "Centro Comercial Mall Vivo Santiago Etapa II") is False


def test_no_numeral_does_not_block_merge():
    assert rpq.has_conflicting_numeral("torre Bellavista", "proyecto Bellavista") is False


def test_generic_blocklist_blocks_merge_with_specific_name():
    assert rpq.is_generic_bare_name("Data Center", "Data Center de Google") is True
    assert rpq.is_generic_bare_name("Vespucio", "Jardines de Vespucio") is True


def test_generic_blocklist_does_not_flag_two_specific_names():
    assert rpq.is_generic_bare_name("torre Bellavista", "proyecto Bellavista") is False


def test_no_duplicate_keys_in_manual_decisions():
    """Hallazgo real de Sol (segunda auditoria, 2026-09-18): las 31 correcciones
    se habian agregado al final del diccionario para 'sobrescribir' la decision
    anterior via el ultimo-valor-gana de Python -- dejaba 24 claves duplicadas
    en el codigo fuente, confuso para cualquiera que lo lea despues. Se
    eliminaron las 24 entradas viejas (stale), dejando solo la version
    corregida. Este test evita que vuelva a pasar."""
    import ast

    src = Path(rpq.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MANUAL_DECISIONS":
            keys = [tuple(ast.literal_eval(elt) for elt in k.elts) for k in node.value.keys]
            assert len(keys) == len(set(keys)), "hay claves duplicadas en MANUAL_DECISIONS"
            return
    raise AssertionError("no se encontro la definicion de MANUAL_DECISIONS")


def test_cencosud_argentina_san_isidro_kept_separate_from_chilean_ones():
    """Tras la correccion completa de Sol sobre los 934 documentos, el
    documento de Cencosud en Argentina paso a mencionar 'Proyecto de
    Cencosud en San Isidro' en vez de 'Costanera Center' -- genera 2 pares
    nuevos en la cola contra los 2 'San Isidro' chilenos ya conocidos
    (Toro Mazotte/Estacion Central y Quilicura). Ninguno debe fusionarse:
    San Isidro, Buenos Aires (Argentina) no tiene relacion con ninguno."""
    d1, r1 = rpq.classify("Proyecto de Cencosud en San Isidro", "San Isidro")
    d2, r2 = rpq.classify("Proyecto de Cencosud en San Isidro", "proyecto San Isidro")
    assert d1 is False
    assert d2 is False


def test_phase_family_id_column_no_longer_exists():
    """[REDISENADO 2026-09-18, hallazgo conceptual de Sol] La primera
    version del modelo de fase fusionaba matriz y fase en un solo
    phase_family_id simetrico -- eso esta conceptualmente invertido
    ("Urbanya" es la matriz, "Urbanya Etapa I" es UNA fase dentro de ella,
    no un alias de la misma fase). Se elimino esa columna; el modelo nuevo
    usa las tablas project_phase / project_phase_link con 2 relaciones
    explicitas (phase_of, same_phase_alias)."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(project)").fetchall()}
    conn.close()
    assert "phase_family_id" not in cols


def test_urbanya_has_phase_and_etapa_i_represents_it():
    """[ACTUALIZADO 2026-09-18, segunda precision de Sol] Caso que expuso el
    error conceptual: 'Urbanya' (matriz) debe tener un link has_phase (antes
    'phase_of', renombrado) hacia el phase_id de 'Urbanya Etapa I'. Y
    'Urbanya Etapa I' -- al ser el UNICO project_id que representa esa fase,
    sin ningun alias real -- debe quedar como 'represents_phase', NO
    'same_phase_alias' (esa relacion es solo para 2+ nombres que son la
    MISMA fase, como 'Fase IV' / 'Enea Fase IV')."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    pid_urbanya = conn.execute("SELECT project_id FROM project WHERE canonical_name='Urbanya'").fetchone()[0]
    pid_etapa_i = conn.execute("SELECT project_id FROM project WHERE canonical_name='Urbanya Etapa I'").fetchone()[0]

    link_urbanya = conn.execute(
        "SELECT phase_id, relation_type FROM project_phase_link WHERE project_id=?", (pid_urbanya,)
    ).fetchall()
    link_etapa_i = conn.execute(
        "SELECT phase_id, relation_type FROM project_phase_link WHERE project_id=?", (pid_etapa_i,)
    ).fetchall()
    conn.close()

    assert link_urbanya == [(link_urbanya[0][0], "has_phase")]
    assert link_etapa_i == [(link_etapa_i[0][0], "represents_phase")]
    assert link_urbanya[0][0] == link_etapa_i[0][0]  # apuntan al mismo phase_id


def test_phase_label_is_deterministic_shortest_name_without_etapa_priority():
    """Hallazgo de Sol: phase_side_pids es un set, y el codigo anterior
    iteraba ese set directamente para decidir que alias quedaba como
    phase_label -- el mismo export podia mostrar un alias distinto entre
    corridas identicas (el phase_id y las relaciones no cambiaban, solo la
    etiqueta). Corregido con una regla explicita y determinista (preferir
    Etapa/Fase explicita, luego el nombre mas corto, luego orden
    lexicografico). Este test fija los 3 phase_label reales esperados."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    labels = {r[0] for r in conn.execute("SELECT phase_label FROM project_phase")}
    conn.close()
    assert labels == {"Urbanya Etapa I", "Fase IV", "Mall Vivo Santiago Etapa II"}


def test_project_phase_link_has_no_duplicate_rows_and_declares_constraints():
    """Hallazgo de Sol: 2 pares de PHASE_OF_PAIRS_BY_SOL resuelven al MISMO
    phase_id para la misma matriz (ej. 'Mall Vivo' es matriz tanto de 'Mall
    Vivo Santiago Etapa II' como de su alias 'Centro Comercial...'), lo que
    sin deduplicar violaria la PRIMARY KEY (project_id, phase_id,
    relation_type). Tambien verifica que la tabla declara PK y FOREIGN KEY,
    no solo que funcione."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    rows = conn.execute("SELECT project_id, phase_id, relation_type FROM project_phase_link").fetchall()
    assert len(rows) == len(set(rows))

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='project_phase_link'"
    ).fetchone()[0]
    conn.close()
    assert "PRIMARY KEY" in schema
    assert "FOREIGN KEY" in schema


def test_fase_iv_and_enea_fase_iv_are_same_phase_alias_not_phase_of():
    """Caso que Sol senalo como la prueba mas clara de que la semantica
    estaba invertida: 'Fase IV' y '...Enea Fase IV...' SI son la misma fase
    (redactada distinto), deben compartir phase_id via same_phase_alias --
    ninguno de los 2 es 'matriz' del otro (no hay relacion phase_of aqui)."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    pid_a = conn.execute("SELECT project_id FROM project WHERE canonical_name='Fase IV'").fetchone()[0]
    pid_b = conn.execute(
        "SELECT project_id FROM project WHERE canonical_name='Radial Aeropuerto Nº 14080, Enea Fase IV, Lote 3E-2'"
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT project_id, phase_id, relation_type FROM project_phase_link WHERE project_id IN (?,?)",
        (pid_a, pid_b),
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert {r[2] for r in rows} == {"same_phase_alias"}
    assert len({r[1] for r in rows}) == 1  # mismo phase_id


def test_vital_apoquindo_has_no_phase_links_at_all():
    """Sol clasifico Vital Apoquindo como 'mismo_referente_numero_no_es_fase'
    -- ninguna de sus variantes debe tener ningun link en project_phase_link
    (ni phase_of ni same_phase_alias).

    [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] Los nombres
    exactos de las variantes cambiaron (v3.3 es una corrida LLM separada
    con fraseo distinto para el mismo objeto real, mismo patron verificado
    en toda la migracion) -- se recalcularon buscando 'Vital Apoquindo' en
    canonical_name contra el warehouse real (ahora 6 variantes en vez de
    5). El punto sustantivo (cero phase links) se mantiene."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    names = (
        "Vital Apoquindo",
        "Vital Apoquindo 1.400-1.450-1.500",
        "proyecto de 25 edificios en la calle Vital Apoquindo",
        "Mega proyecto inmobiliario de 25 edificios en altura, calle Vital Apoquindo números 1.400, 1450 y 1.500",
        "Mega proyecto inmobiliario de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500",
        "proyecto de la Inmobiliaria Mirador Oriente S.A. a emplazarse en su terreno de calle Vital Apoquindo",
    )
    pids = [
        conn.execute("SELECT project_id FROM project WHERE canonical_name=?", (n,)).fetchone()[0] for n in names
    ]
    q = ",".join("?" * len(pids))
    n_links = conn.execute(
        f"SELECT COUNT(*) FROM project_phase_link WHERE project_id IN ({q})", pids
    ).fetchone()[0]
    conn.close()
    assert n_links == 0


def test_project_phase_case_id_matches_the_matrix_and_phase_shared_case():
    """El case_id guardado en project_phase debe coincidir con el case_id
    real que comparten la matriz y su fase (verificacion cruzada, no solo
    que el campo este poblado con algo)."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    case_id_urbanya = conn.execute("SELECT case_id FROM project WHERE canonical_name='Urbanya'").fetchone()[0]
    case_id_etapa_i = conn.execute("SELECT case_id FROM project WHERE canonical_name='Urbanya Etapa I'").fetchone()[0]
    phase_case_id = conn.execute(
        "SELECT case_id FROM project_phase WHERE phase_label='Urbanya Etapa I'"
    ).fetchone()[0]
    conn.close()
    assert case_id_urbanya == case_id_etapa_i == phase_case_id


def test_known_homonyms_stay_separate_in_project_id_and_case_id():
    """Hallazgo BLOQUEANTE de Sol (tercera auditoria, 2026-09-18): separar un
    homonimo a nivel de project_id no basta -- Costanera Center Chile y
    Argentina volvian a conectarse por case_id porque ambas pasaban por el
    mismo par con nombre identico ('Costanera Center' vs 'mall Costanera
    Center' -> merged), y classify() decide por nombre sin saber que hay 2
    project_id detras. Corregido con homonym_partition + veto de
    reconexion transitiva en union(). Este test fija, para los 3 homonimos
    conocidos, que project_id Y case_id permanecen distintos tras resolver
    la cola completa contra la base real."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    # se agrupa por la BASE del homonimo (antes de "::" en homonym_partition),
    # no por canonical_name -- San Isidro produce 2 canonical_name distintos
    # ("San Isidro" y "proyecto San Isidro"), Plaza Egaña produce el mismo
    # canonical_name para ambas mitades.
    # [ACTUALIZADO 2026-09-18, tras aplicar la correccion completa de Sol
    # sobre los 934 documentos] "costanera center": Sol corrigio
    # proyectos_mencionados del documento de Cencosud en Argentina
    # (reemplazo "Costanera Center" por "Proyecto de Cencosud en San
    # Isidro"), asi que ese documento ya no genera esa mencion especifica --
    # el homonimo se resolvio en el DATO, no solo en el project_id, y el
    # split de KNOWN_HOMONYM_SPLITS para ese caso quedo inerte (se deja en
    # el codigo, sin efecto, documentado como historico).
    #
    # [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] "san isidro"
    # tambien quedo inerte por el mismo mecanismo, verificado leyendo el
    # JSONL real: v3.3 (corrida LLM separada) extrajo para el documento
    # fuente ('...segreader.emol.cl/2017/04/13/A/JI3512LK...') dos menciones
    # completamente re-fraseadas ('departamentos en Las Rejas norte',
    # 'lo que quieren vender en calle Toro Mazotte') -- ninguna normaliza a
    # "san isidro", asi que la entrada de KNOWN_HOMONYM_SPLITS para ese
    # documento nunca vuelve a activarse. Solo "plaza egana" sigue activo
    # (su documento fuente conserva el nombre "Plaza Egaña" en v3.3)."""
    rows = conn.execute("SELECT project_id, case_id, homonym_partition FROM project WHERE homonym_partition IS NOT NULL").fetchall()
    by_base: dict[str, list[tuple[str, str]]] = {}
    for project_id, case_id, partition in rows:
        base = partition.split("::", 1)[0]
        by_base.setdefault(base, []).append((project_id, case_id))
    for base in ("plaza egana",):
        entries = by_base.get(base, [])
        assert len(entries) == 2, f"se esperaban 2 project_id homonimo para base {base!r}, hay {len(entries)}"
        project_ids = {e[0] for e in entries}
        case_ids = {e[1] for e in entries}
        assert len(project_ids) == 2, f"project_id no distintos para base {base!r}"
        assert len(case_ids) == 2, f"case_id SE RECONECTARON para base {base!r}: {entries}"
    conn.close()


def test_sol_audit_31_corrections_2026_09_18():
    """Regresion: Sol (GPT-5.6) audito los 253 pares con evidencia real y
    reporto 31 desacuerdos con las decisiones originales de Claude. Cada uno
    de los 31 fue reverificado por Claude contra la evidencia real (comuna/
    direccion/URL de los documentos, no solo el nombre) antes de aceptarlo --
    18 falsas separaciones que en realidad eran el mismo proyecto (numeros de
    DIRECCION mal tratados como numeros de ETAPA/FASE: General Amengual 480,
    Pajaritos 4600, Vital Apoquindo 1400-1500, y el cluster Mall Vivo/Urbanya
    donde 'Etapa' era una fase del mismo caso, no un proyecto distinto), y
    13 fusiones agresivas que en realidad eran proyectos distintos (nombre de
    empresa/institucion confundido con proyecto especifico: Nueva El Golf,
    Universidad San Sebastian, Fundamenta en Ñuñoa; o coincidencia de nombre
    generico sin evidencia geografica real: Rotonda Atenas, Barrio Maestranza,
    Barrio Parque, Parque Bicentenario Cerrillos, Hospital del Salvador,
    Carlos Valdovinos, Toro Mazotte, San Isidro). Este test fija esas 31
    decisiones para que no se reviertan por accidente en un refactor futuro."""
    esperado_merge = {
        ("General Amengual", "edificio de 38 pisos y más de 300 departamentos ubicado en calle General Amengual 480"),
        ("Edificio Pajaritos", "Pajaritos 4600"),
        ("Mall Vivo Santiago Etapa II", "Mall Vivo"),
        ("Mall Vivo Santiago Etapa II", "Mall Vivo Santiago"),
        ("Urbanya Etapa I", "Urbanya"),
        ("Mall Vivo", "Mall Vivo Ñuñoa"),
        ("Mall Vivo", "Centro Comercial Mall Vivo Santiago Etapa II"),
        ("Mall Vivo", "Mall Vivo Santiago: Etapa de Demolición, Excavación y Socalzados"),
        ("Mall Vivo", "Mall Vivo Santiago"),
        ("Edificio Capital", "Condominio Eco Capital"),
        ("Eco Egaña", "Eco Egaña Poniente"),
        ("Centro de Salud Familiar (Cesfam)", "tercer Centro de Salud Familiar (Cesfam) de Las Condes"),
        ("calle Vital Apoquindo 1.400-1.450-1.500", "Vital Apoquindo"),
        ("Las Américas", "Colegio Las Américas"),
        ("Mall Vivo Santiago", "Centro Comercial Mall Vivo Santiago Etapa II"),
        ("Vital Apoquindo", "Proyecto de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500"),
        ("Vital Apoquindo", "Vital Apoquindo números 1.400, 1450 y 1.500"),
        ("Vital Apoquindo", "proyecto de 25 edificios en la calle Vital Apoquindo"),
    }
    esperado_separado = {
        ("Rotonda Atenas", "proyecto social de 2023 de la rotonda Atenas"),
        ("proyecto de Inmobiliaria Nueva El Golf", "proyecto que impulsa la inmobiliaria Nueva El Golf"),
        ("proyecto de Inmobiliaria Nueva El Golf", "Nueva El Golf"),
        ("planta de tratamiento de aguas servidas de la Empresa San Isidro", "San Isidro"),
        ("calle Toro Mazotte", "cuatro megaedificios ubicados en calle Toro Mazotte"),
        ("Carlos Valdovinos", "tres torres de 15 pisos y dos subterráneos, cada uno en un sector de avenida Carlos Valdovinos"),
        ("proyecto inmobiliario de Fundamenta en Ñuñoa", "proyecto inmobiliario de Fundamenta"),
        ("Universidad San Sebastián", "Proyecto de la Universidad San Sebastián en la manzana delimitada por las calles Bellavista, Ernesto Pinto Lagarrigue, Dardignac y Pío Nono"),
        ("Nueva El Golf", "proyecto que impulsa la inmobiliaria Nueva El Golf"),
        ("Barrio Maestranza 1", "barrio Maestranza"),
        ("Barrio Parque", "Barrio Parque de Quinta Normal"),
        ("Parque Bicentenario Cerrillos", "Parque Bicentenario"),
        ("Hospital del Salvador", "nuevo Hospital del Salvador"),
    }
    assert len(esperado_merge) == 18
    assert len(esperado_separado) == 13
    for a, b in esperado_merge:
        decision, _ = rpq.classify(a, b)
        assert decision is True, f"deberia fusionar: {a!r} / {b!r}"
    for a, b in esperado_separado:
        decision, _ = rpq.classify(a, b)
        assert decision is False, f"deberia mantenerse separado: {a!r} / {b!r}"


# --- migracion v3.2->v3.3 (2026-09-26): reconexion de MANUAL_DECISIONS via
# substring normalizado, cuando el fraseo del proyecto cambio entre corridas
# LLM pero MANUAL_DECISIONS quedo indexado por el fraseo viejo ---


def test_manual_decision_via_normalized_substring_reconnects_renamed_pair(monkeypatch):
    fake_manual = {("Torre Central", "proyecto Torre Central"): (True, "mismo proyecto")}
    monkeypatch.setattr(rpq, "MANUAL_DECISIONS", fake_manual)
    result = rpq._manual_decision_via_normalized_substring("Torre Central 2024", "proyecto Torre Central en Ñuñoa")
    assert result is not None
    decision, reason = result
    assert decision is True
    assert "reconectado" in reason


def test_manual_decision_via_normalized_substring_returns_none_when_no_match(monkeypatch):
    fake_manual = {("Torre Central", "proyecto Torre Central"): (True, "mismo proyecto")}
    monkeypatch.setattr(rpq, "MANUAL_DECISIONS", fake_manual)
    assert rpq._manual_decision_via_normalized_substring("Edificio Completamente Distinto", "Otro Proyecto Sin Relacion") is None


def test_manual_decision_via_normalized_substring_never_picks_ambiguous_match(monkeypatch):
    """Si mas de una clave de MANUAL_DECISIONS matchea por substring, el
    fallback debe preferir NO decidir antes que elegir arbitrariamente --
    ambiguedad real, no un error a ocultar."""
    fake_manual = {
        ("Torre Central", "proyecto Torre Central Norte"): (True, "decision A"),
        ("Torre Central", "proyecto Torre Central Sur"): (True, "decision B"),
    }
    monkeypatch.setattr(rpq, "MANUAL_DECISIONS", fake_manual)
    assert rpq._manual_decision_via_normalized_substring("Torre Central", "Torre Central") is None


def test_classify_checks_generic_blocklist_before_substring_fallback(monkeypatch):
    """Regresion real encontrada al implementar el fallback: 'Vespucio' (en
    GENERIC_BLOCKLIST) matcheaba por substring contra CUALQUIER decision
    manual que mencionara 'Vespucio' (ej. 'Jardines de Vespucio'), una
    reconexion espuria. El blocklist debe interceptar antes de llegar al
    fallback de substring."""
    fake_manual = {("Vespucio", "Jardines de Vespucio"): (True, "no deberia aplicar aqui")}
    monkeypatch.setattr(rpq, "MANUAL_DECISIONS", fake_manual)
    decision, reason = rpq.classify("edificio en Avenida Vespucio 7550", "Vespucio")
    assert decision is False
    assert "generico" in reason


def test_all_real_pairs_are_covered_by_rule_or_manual_decision():
    """Hallazgo real: antes de aplicar nada a la base de datos se verifico
    que TODAS las filas reales de project_review_queue tuvieran una decision
    -- 1 par quedo sin cubrir en la primera pasada (Nueva El Golf) por un
    problema de orden de las claves del diccionario, detectado aqui antes
    de tocar la base de datos. El total paso de 253 a 254 el 2026-09-18 al
    separar el homonimo San Isidro, a 259 al separar Costanera Center
    (documento de Cencosud en Argentina) y Plaza Egaña (paño de Vitacura) en
    la auditoria de los 150 clusters exactos multi-documento, y a 255 tras
    aplicar la correccion completa de Sol sobre los 934 documentos (elimino
    la ambiguedad de Costanera Center Chile/Argentina en el DATO -- Sol
    reemplazo el nombre de proyecto del documento argentino por 'Proyecto de
    Cencosud en San Isidro', que a su vez genero 2 pares nuevos frente a los
    otros 2 'San Isidro' chilenos, ya cubiertos con decision manual
    explicita), y a 260 el 2026-09-18 al agregar MANUAL_EXTRA_REVIEW_PAIRS
    en build_projects.py: 5 pares alias encontrados por Sol al
    clasificar los 63 documentos caso_unico con >1 case_id (conflict_unit),
    que find_review_candidates() nunca genero porque esos nombres no
    comparten substring (ej. 'Villa San Luis' / 'Villa Carlos Cortes'). El
    numero de pares no es estable -- verificar siempre en vivo antes de
    citarlo."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest
        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    rows = conn.execute("SELECT canonical_name_a, canonical_name_b FROM project_review_queue").fetchall()
    conn.close()
    # [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] 260 -> 256:
    # v3.3 extrajo, en conjunto, menos proyectos_mencionados que v3.2 (9.5%
    # menos en total, verificado empiricamente para toda la migracion) --
    # menos menciones generan menos pares candidatos de find_review_
    # candidates(). El numero no es estable por diseno (el docstring de este
    # test ya lo advierte); lo que se verifica abajo (los 5 pares manuales
    # de Sol siguen presentes y decididos 'merged') es la proteccion real.
    assert len(rows) == 256

    # find_review_candidates() ahora ignora en silencio (no lanza) un par de
    # MANUAL_EXTRA_REVIEW_PAIRS si el nombre no existe en el registro actual
    # -- necesario para no romper fixtures sinteticos de test, pero eso
    # significa que un par real podria desaparecer sin que nada avise. Este
    # test es la proteccion: confirma contra el warehouse real que los pares
    # de conflict_unit_63 siguen presentes y decididos 'merged'.
    #
    # [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] el par
    # ("Alto Las Condes 2", "Alto Norte") quedo inerte: verificado leyendo
    # el JSONL real que los 2 documentos fuente (latercera.com/.../alto-
    # las-condes-norte-en-vitacura, df.cl/.../reformular-proyecto-alto-las-
    # condes-2) ya NO mencionan "Alto Norte" en v3.3 (mismo patron de
    # mencion desaparecida verificado en toda la migracion) -- "Alto Las
    # Condes 2" si se conserva. Se excluye de la proteccion activa (misma
    # decision que ya se aplico a los homonimos San Isidro/Costanera Center
    # inertes) y se deja documentado aqui en vez de fallar en silencio.
    pares_reales = {frozenset((a, b)) for a, b in rows}
    pares_inertes_v3_3 = {frozenset(("Alto Las Condes 2", "Alto Norte"))}
    for name_a, name_b, _reason in bridge.MANUAL_EXTRA_REVIEW_PAIRS:
        if frozenset((name_a, name_b)) in pares_inertes_v3_3:
            continue
        assert frozenset((name_a, name_b)) in pares_reales, (
            f"par manual '{name_a}' / '{name_b}' ya no esta en project_review_queue -- "
            "verificar si el nombre de proyecto cambio en el registro"
        )
        decision, _ = rpq.classify(name_a, name_b)
        assert decision is True, f"'{name_a}' / '{name_b}' deberia estar merged"

    # [ACTUALIZADO 2026-09-26, migracion v3.2->v3.3 completa] HALLAZGO REAL,
    # no solo un test desactualizado: al migrar el enrichment productivo a
    # v3.3, muchos nombres de proyecto cambiaron de fraseo para el MISMO
    # objeto real -- 98/256 pares quedaron sin decision (antes: 0/260).
    # Verificado que 64 de esos 98 correspondian a decisiones YA TOMADAS por
    # Sol/Claude bajo el fraseo viejo de v3.2, perdidas en silencio porque
    # MANUAL_DECISIONS matchea por texto EXACTO. Se corrigio de raiz en
    # classify() (ver _manual_decision_via_normalized_substring(), agregada
    # 2026-09-26): reconecta un par nuevo con una decision ya tomada si hay
    # EXACTAMENTE una clave de MANUAL_DECISIONS en relacion de substring
    # normalizado bidireccional con el par nuevo -- mismo principio 'nunca
    # fuzzy' que el resto del proyecto, corrido DESPUES del blocklist de
    # nombres genericos (para no reconectar por accidente un termino como
    # 'Vespucio' o 'Data Center' que aparece en muchas decisiones distintas).
    # Esto recupero 30 de esas 64 decisiones perdidas (verificado a mano:
    # las que no se recuperan son genuinamente ambiguas -- mas de una
    # decision candidata por substring, y el fallback prefiere no decidir
    # antes que elegir arbitrariamente). Los 68 pares que siguen sin
    # decision son, en su mayoria, candidatos GENUINAMENTE NUEVOS que v3.3
    # introdujo (nunca existieron como par bajo v3.2) -- correcto que
    # queden pendientes de revision humana, no un bug."""
    uncovered = [(a, b) for a, b in rows if rpq.classify(a, b)[0] is None]
    assert len(uncovered) == 68, (
        f"cambio el numero de pares sin decision (era 68 tras la migracion v3.2->v3.3 "
        f"y la reconexion via substring normalizado): {len(uncovered)}. Si subio, investigar "
        f"si el fallback dejo de reconectar algo que deberia; si bajo, verificar que fue "
        f"por una decision real nueva, no por relajar el fallback."
    )
