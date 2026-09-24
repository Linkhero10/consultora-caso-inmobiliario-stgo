"""Pruebas del puente documento -> caso/proyecto -> actor/evento.

No llaman a ninguna API ni tocan el warehouse real -- verifican la logica
de resolucion con datos sinteticos, siguiendo el hallazgo real de Luna
(2026-09-17): ningun actor tenia identidad de proyecto estable entre
documentos, y 280/934 documentos reales mencionan 2+ proyectos (ambiguedad
real, no un caso raro).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_projects as bridge  # noqa: E402


def test_normalize_merges_real_writing_variants():
    """Casos reales encontrados en el corpus antes de construir el puente."""
    assert bridge.normalize_project_name("Torre Bellavista") == bridge.normalize_project_name("torre Bellavista")
    assert bridge.normalize_project_name("Hijuelas-Quilín") == bridge.normalize_project_name("proyecto Hijuelas Quilín")
    assert bridge.normalize_project_name("Edificio Alameda Urbano") == bridge.normalize_project_name("Alameda Urbano")


def test_normalize_does_not_merge_different_projects():
    """Nunca debe fusionar dos proyectos genuinamente distintos solo porque
    comparten una palabra generica."""
    assert bridge.normalize_project_name("Torre Central Providencia") != bridge.normalize_project_name("Torre Central Ñuñoa")


def test_project_registry_clusters_exact_normalized_matches_only():
    records = [
        {"document_id": "d1", "proyectos_mencionados": ["Torre Bellavista"]},
        {"document_id": "d2", "proyectos_mencionados": ["torre Bellavista"]},
        {"document_id": "d3", "proyectos_mencionados": ["Torre Distinta"]},
    ]
    projects, mention_lookup = bridge.build_project_registry(records)
    assert len(projects) == 2  # Bellavista (fusionado) + Distinta
    pid_d1 = mention_lookup[("d1", "Torre Bellavista")]
    pid_d2 = mention_lookup[("d2", "torre Bellavista")]
    assert pid_d1 == pid_d2
    bellavista = projects[pid_d1]
    assert bellavista["n_documents"] == 2
    assert set(bellavista["aliases"]) == {"Torre Bellavista", "torre Bellavista"}


def test_review_queue_flags_substring_candidates_without_merging():
    records = [
        {"document_id": "d1", "proyectos_mencionados": ["Parque Bicentenario de Cerrillos"]},
        {"document_id": "d2", "proyectos_mencionados": ["Parque Bicentenario Cerrillos"]},
    ]
    projects, _ = bridge.build_project_registry(records)
    # Estos NO normalizan identico (uno tiene "de"+"Cerrillos" con orden distinto de tokens
    # tras remover stopwords ambos deberian dar "parque bicentenario cerrillos" -- verificar
    # que de hecho SI normalizan igual, dado que son la misma frase salvo la preposicion "de".
    assert len(projects) == 1  # "de" es stopword, terminan identicos -- caso ya cubierto arriba

    records_distintos = [
        {"document_id": "d1", "proyectos_mencionados": ["Parque Industrial Norte"]},
        {"document_id": "d2", "proyectos_mencionados": ["Parque Industrial Norte Fase 2"]},
    ]
    projects2, _ = bridge.build_project_registry(records_distintos)
    assert len(projects2) == 2
    candidates = bridge.find_review_candidates(projects2)
    assert len(candidates) == 1
    assert candidates[0]["reason"] == "substring_match_not_auto_merged"


def test_resolve_association_explicit():
    mention_lookup = {("d1", "Torre A"): "pid_a", ("d1", "Torre B"): "pid_b"}
    project_id, status = bridge.resolve_association("d1", "Torre A", {"pid_a", "pid_b"}, mention_lookup)
    assert project_id == "pid_a"
    assert status == "resolved_explicit"


def test_resolve_association_single_project_no_explicit_association():
    """Actor sin proyecto_asociado, pero el documento solo menciona 1 --
    no hay ambiguedad real, se resuelve igual."""
    mention_lookup = {("d1", "Torre A"): "pid_a"}
    project_id, status = bridge.resolve_association("d1", "", {"pid_a"}, mention_lookup)
    assert project_id == "pid_a"
    assert status == "inferred_single_project"


def test_resolve_association_ambiguous_never_guesses():
    """Hallazgo real: 280/934 documentos mencionan 2+ proyectos. Sin
    proyecto_asociado explicito, NUNCA se debe adivinar cual es -- Sol lo
    exigio explicitamente ('las asociaciones no resolubles quedan
    explicitamente sin adjudicar')."""
    mention_lookup = {("d1", "Torre A"): "pid_a", ("d1", "Torre B"): "pid_b"}
    project_id, status = bridge.resolve_association("d1", "", {"pid_a", "pid_b"}, mention_lookup)
    assert project_id is None
    assert status == "unresolved_ambiguous"


def test_resolve_association_no_project_mentioned():
    project_id, status = bridge.resolve_association("d1", "", set(), {})
    assert project_id is None
    assert status == "unresolved_no_project"


def test_actor_second_pass_v2_links_never_duplicate_first_pass():
    """Hallazgo BLOQUEANTE de Sol (segunda auditoria, 2026-09-18): actores_final
    de actor_second_pass_v2 es la union A∪B (source_pass in first/both/second);
    cargar TODAS esas filas en actor_event_project_link duplicaba cualquier
    actor que ya estuviera en enrichment_actor (source_pass=first). Este
    test verifica contra la base real que ya no ocurre: todo link con
    source_table='actor_second_pass_v2' debe tener source_pass='second'."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    rows = conn.execute(
        "SELECT DISTINCT source_pass FROM actor_event_project_link WHERE source_table='actor_second_pass_v2'"
    ).fetchall()
    conn.close()
    assert rows == [("second",)]


def test_known_homonym_split_separates_confirmed_homonyms():
    """Hallazgo real de Claude al verificar el punto 8 de la segunda
    auditoria de Sol (riesgo de homonimos en el cluster exacto): 'San
    Isidro' bare fusionaba, via coincidencia EXACTA de nombre normalizado,
    una planta de tratamiento de aguas en Quilicura con una mencion sin
    relacion en Toro Mazotte/Estacion Central. KNOWN_HOMONYM_SPLITS fuerza
    un project_id distinto para ese documento especifico."""
    doc_toro_mazotte = "e604fe1436ae5fdf514193a9ce8264613c475139ea396b0b4c2964391ddeffed"
    records = [
        {"document_id": doc_toro_mazotte, "proyectos_mencionados": ["San Isidro"]},
        {"document_id": "otro_doc_quilicura", "proyectos_mencionados": ["San Isidro"]},
    ]
    projects, mention_lookup = bridge.build_project_registry(records)
    assert len(projects) == 2
    pid_toro_mazotte = mention_lookup[(doc_toro_mazotte, "San Isidro")]
    pid_quilicura = mention_lookup[("otro_doc_quilicura", "San Isidro")]
    assert pid_toro_mazotte != pid_quilicura


def test_known_homonym_splits_costanera_center_and_plaza_egana():
    """Hallazgo de la auditoria de los 150 clusters exactos multi-documento
    (pedida por Sol tras San Isidro, 2026-09-18): 'Costanera Center' fusionaba
    con un documento sobre el proyecto de Cencosud EN ARGENTINA, y 'Plaza
    Egaña' fusionaba la interseccion real (Ñuñoa/La Reina) con 2 documentos
    que ubican consistentemente un 'Plaza Egaña' distinto en Vitacura."""
    doc_argentina = "894c62ee791c8af113381e6e77c84ac82f79acfb508bf3273172222ae992d7dc"
    records_cc = [
        {"document_id": doc_argentina, "proyectos_mencionados": ["Costanera Center"]},
        {"document_id": "otro_doc_providencia", "proyectos_mencionados": ["Costanera Center"]},
    ]
    projects, mention_lookup = bridge.build_project_registry(records_cc)
    assert len(projects) == 2
    assert mention_lookup[(doc_argentina, "Costanera Center")] != mention_lookup[("otro_doc_providencia", "Costanera Center")]

    doc_vitacura_1 = "7765d45503ecfb4d7ba4722549e1c0f4aa029faaede885bd06a0bb3318cedf00"
    doc_vitacura_2 = "a3fd98f337c6e4ca4b55164cd61f24618a020ad6d0f57ad4e1b58e71abb34160"
    records_pe = [
        {"document_id": doc_vitacura_1, "proyectos_mencionados": ["Plaza Egaña"]},
        {"document_id": doc_vitacura_2, "proyectos_mencionados": ["Plaza Egaña"]},
        {"document_id": "otro_doc_nunoa", "proyectos_mencionados": ["Plaza Egaña"]},
    ]
    projects2, mention_lookup2 = bridge.build_project_registry(records_pe)
    assert len(projects2) == 2  # los 2 de Vitacura juntos, el de Ñuñoa aparte
    pid_v1 = mention_lookup2[(doc_vitacura_1, "Plaza Egaña")]
    pid_v2 = mention_lookup2[(doc_vitacura_2, "Plaza Egaña")]
    pid_nunoa = mention_lookup2[("otro_doc_nunoa", "Plaza Egaña")]
    assert pid_v1 == pid_v2
    assert pid_v1 != pid_nunoa


def test_resolve_association_inconsistent_explicit_association_not_silently_dropped():
    """Si proyecto_asociado no esta vacio pero no coincide con ninguna
    mencion conocida del documento (no deberia pasar tras
    sanitize_project_associations(), pero si pasa, debe quedar marcado, no
    adjudicado en silencio a un proyecto al azar)."""
    mention_lookup = {("d1", "Torre A"): "pid_a"}
    project_id, status = bridge.resolve_association("d1", "Torre Inexistente", {"pid_a"}, mention_lookup)
    assert project_id is None
    assert status == "unresolved_inconsistent_association"


def test_analytical_views_exist_and_are_conservative_subsets():
    """Hallazgo de Sol (2026-09-18): sin una vista materializada, cualquier
    consumidor que consulte actor_event_project_link directo obtiene en
    silencio links de documentos panoramicos/contextuales/fuera de universo.
    Se agregaron 2 vistas SQL con las reglas del gate ya aplicadas."""
    import sqlite3

    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    views = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert "actor_event_project_link_case_safe" in views
    assert "actor_event_project_link_include_inferred" in views

    n_total = conn.execute("SELECT COUNT(*) FROM actor_event_project_link").fetchone()[0]
    n_safe = conn.execute("SELECT COUNT(*) FROM actor_event_project_link_case_safe").fetchone()[0]
    n_inferred = conn.execute("SELECT COUNT(*) FROM actor_event_project_link_include_inferred").fetchone()[0]
    assert 0 < n_safe <= n_inferred <= n_total

    bad = conn.execute(
        "SELECT COUNT(*) FROM actor_event_project_link_case_safe l "
        "JOIN document_case_unit g ON g.document_id = l.document_id "
        "WHERE g.unidad_caso_tipo != 'caso_unico' OR l.resolution_status != 'resolved_explicit'"
    ).fetchone()[0]
    assert bad == 0
    conn.close()


def test_find_review_candidates_includes_manual_extra_pairs_when_names_unambiguous():
    records = [
        {"document_id": "d1", "proyectos_mencionados": ["Villa San Luis"]},
        {"document_id": "d2", "proyectos_mencionados": ["Villa Carlos Cortés"]},
    ]
    projects, _ = bridge.build_project_registry(records)
    candidates = bridge.find_review_candidates(projects)
    names = {frozenset((c["canonical_name_a"], c["canonical_name_b"])) for c in candidates}
    assert frozenset(("Villa San Luis", "Villa Carlos Cortés")) in names


def test_find_review_candidates_skips_manual_pair_missing_from_registry():
    """No debe fallar si un nombre de MANUAL_EXTRA_REVIEW_PAIRS no existe
    en un registro de proyectos (fixture sintetico o corpus que cambio)."""
    records = [{"document_id": "d1", "proyectos_mencionados": ["Proyecto Sin Relacion"]}]
    projects, _ = bridge.build_project_registry(records)
    candidates = bridge.find_review_candidates(projects)  # no debe lanzar
    assert candidates == []


def test_find_review_candidates_raises_on_ambiguous_canonical_name():
    """Hallazgo/fragilidad senalada por Sol (2026-09-18): si 2 project_id
    distintos compartieran el mismo canonical_name de un par manual, el
    setdefault() original elegia el primero en silencio. Ahora debe
    fallar de forma explicita en vez de adivinar."""
    import build_projects as bridge_module

    original_pairs = bridge_module.MANUAL_EXTRA_REVIEW_PAIRS
    bridge_module.MANUAL_EXTRA_REVIEW_PAIRS = [("Villa San Luis", "Otro Proyecto", "test_ambiguedad")]
    try:
        projects = {
            "pid_1": {"canonical_name": "Villa San Luis", "normalized_name": "villa san luis"},
            "pid_2": {"canonical_name": "Villa San Luis", "normalized_name": "villa san luis"},
            "pid_3": {"canonical_name": "Otro Proyecto", "normalized_name": "otro proyecto"},
        }
        try:
            bridge_module.find_review_candidates(projects)
            assert False, "deberia haber lanzado ValueError por nombre ambiguo"
        except ValueError as e:
            assert "ambiguo" in str(e)
    finally:
        bridge_module.MANUAL_EXTRA_REVIEW_PAIRS = original_pairs


# --- Fix 1E: guard de schema de SOURCE_WAREHOUSE (hallazgo real, 2026-09-24) ---


def _make_sqlite(path, tables, n_documents=934):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE document (document_id TEXT PRIMARY KEY)")
    for i in range(n_documents):
        conn.execute("INSERT INTO document VALUES (?)", (f"doc{i}",))
    for t in tables:
        conn.execute(f"CREATE TABLE {t} (id TEXT)")
    conn.commit()
    conn.close()


def test_validate_source_warehouse_passes_with_expected_schema(tmp_path):
    path = tmp_path / "good.sqlite"
    _make_sqlite(path, bridge.SOURCE_WAREHOUSE_EXPECTED_TABLES)
    bridge._validate_source_warehouse(path)  # no debe lanzar


def test_validate_source_warehouse_rejects_wrong_schema_with_suffix(tmp_path):
    """Reproduce exactamente el hallazgo real: tablas con sufijo _v3_2 en
    vez de los nombres esperados -- debe abortar ANTES de copiar sobre
    data/warehouse.sqlite, nunca sobreescribir en silencio."""
    path = tmp_path / "mutated.sqlite"
    _make_sqlite(path, ["enrichment_actor_v3_2", "enrichment_institucion_v3_2"])
    try:
        bridge._validate_source_warehouse(path)
        assert False, "deberia haber abortado por schema incompatible"
    except SystemExit as e:
        assert "schema" in str(e) or "faltan tablas" in str(e)


def test_validate_source_warehouse_rejects_missing_file(tmp_path):
    path = tmp_path / "no_existe.sqlite"
    try:
        bridge._validate_source_warehouse(path)
        assert False, "deberia haber abortado por archivo inexistente"
    except SystemExit:
        pass


def test_validate_source_warehouse_rejects_incomplete_corpus(tmp_path):
    path = tmp_path / "incomplete.sqlite"
    _make_sqlite(path, bridge.SOURCE_WAREHOUSE_EXPECTED_TABLES, n_documents=10)
    try:
        bridge._validate_source_warehouse(path)
        assert False, "deberia haber abortado por corpus incompleto"
    except SystemExit:
        pass


def test_validate_source_warehouse_passes_against_real_current_source():
    """Regresion real: la fuente actual (regenerada con
    build_enrichment_tables.py tras el hallazgo de hoy) debe pasar el guard."""
    if not bridge.SOURCE_WAREHOUSE.exists():
        import pytest

        pytest.skip("Auditoria/integracion_v1/warehouse_v3_2.sqlite no existe en este entorno (gitignorado)")
    bridge._validate_source_warehouse(bridge.SOURCE_WAREHOUSE)  # no debe lanzar
