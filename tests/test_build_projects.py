"""Pruebas del puente documento -> caso/proyecto -> actor/evento.

No llaman a ninguna API ni tocan el warehouse real -- verifican la logica
de resolucion con datos sinteticos, siguiendo el hallazgo real de Luna
(2026-09-17): ningun actor tenia identidad de proyecto estable entre
documentos, y 280/934 documentos reales mencionan 2+ proyectos (ambiguedad
real, no un caso raro).
"""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_projects as bridge  # noqa: E402


def test_apply_verified_project_mention_index_corrections_fills_null_index_with_citation():
    records = [
        {
            "document_id": "doc1",
            "proyectos_mencionados": [{"nombre": "Línea 7 del Metro", "case_mention_index": None}],
        }
    ]
    corrections = {("doc1", "Línea 7 del Metro"): 0}
    n_applied = bridge.apply_verified_project_mention_index_corrections(records, corrections)
    assert n_applied == 1
    assert records[0]["proyectos_mencionados"][0]["case_mention_index"] == 0


def test_apply_verified_project_mention_index_corrections_never_overwrites_existing_index():
    records = [
        {
            "document_id": "doc1",
            "proyectos_mencionados": [{"nombre": "Proyecto X", "case_mention_index": 2}],
        }
    ]
    corrections = {("doc1", "Proyecto X"): 0}
    n_applied = bridge.apply_verified_project_mention_index_corrections(records, corrections)
    assert n_applied == 0
    assert records[0]["proyectos_mencionados"][0]["case_mention_index"] == 2


def test_apply_verified_project_mention_index_corrections_ignores_unrelated_mentions():
    records = [
        {
            "document_id": "doc1",
            "proyectos_mencionados": [{"nombre": "Proyecto sin correccion", "case_mention_index": None}],
        }
    ]
    corrections = {("doc1", "Otro proyecto"): 0}
    n_applied = bridge.apply_verified_project_mention_index_corrections(records, corrections)
    assert n_applied == 0
    assert records[0]["proyectos_mencionados"][0]["case_mention_index"] is None


def test_load_verified_project_mention_index_corrections_returns_empty_dict_when_file_missing(tmp_path):
    corrections = bridge.load_verified_project_mention_index_corrections(tmp_path / "no_existe.json")
    assert corrections == {}


def test_load_verified_project_mention_index_corrections_rejects_duplicate_entries(tmp_path):
    import json

    path = tmp_path / "corrections.json"
    path.write_text(
        json.dumps(
            {
                "corrections": [
                    {"document_id": "doc1", "nombre_proyecto": "X", "case_mention_index": 0},
                    {"document_id": "doc1", "nombre_proyecto": "X", "case_mention_index": 1},
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        bridge.load_verified_project_mention_index_corrections(path)
        assert False, "debia lanzar ValueError por entrada duplicada"
    except ValueError as e:
        assert "duplicada" in str(e)


def test_load_verified_project_mention_index_corrections_reads_real_linea7_entry():
    """Verifica que la correccion real de Linea 7 versionada en config/ tiene la
    forma esperada -- no un valor sintetico, el mismo archivo que usa build_projects.py."""
    corrections = bridge.load_verified_project_mention_index_corrections()
    key = (
        "7ede9b8944ed9ac225b1160290a7c0ac95026096808db706b5e6e0142abe53c8",
        "Línea 7 del Metro",
    )
    assert corrections.get(key) == 0


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


def test_descriptive_ukamau_reference_keeps_evidence_but_never_creates_project_id(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)
    quote_texts = [
        "UKAMAU y su candidata a Alcaldesa de Estación Central, exhiben una obra colectiva que da sustento a la campaña electoral. Hechos tras la organización: Proyecto inmobiliario comunitario",
        "Que la vivienda social sea un conjunto habitacional distinto del estándar que se otorga mediante el subsidio que otorga el Estado.",
        "sector aledaño a la Maestranza de San Eugenio (Estación Central)",
    ]
    source_text = " ".join(quote_texts)
    document_id = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    case_mention_id = f"{document_id}:0"
    object_evidence_id = f"{case_mention_id}:objeto:2"
    social_housing_evidence_id = f"{case_mention_id}:objeto:1"
    geography_evidence_id = f"{case_mention_id}:geografica:0"
    citations = [
        {
            "quote": quote_texts[0],
            "evidence_ids": [object_evidence_id],
        },
        {
            "quote": quote_texts[1],
            "evidence_ids": [social_housing_evidence_id],
        },
        {
            "quote": quote_texts[2],
            "evidence_ids": [geography_evidence_id],
        },
    ]
    for citation in citations:
        citation["quote_sha256"] = hashlib.sha256(citation["quote"].encode("utf-8")).hexdigest()
    source_relpath = Path("Fuentes/fulltext/content/ukamau.json")
    source_path = tmp_path / source_relpath
    source_path.parent.mkdir(parents=True)
    source_bytes = json.dumps(
        {"text": source_text, "url": "https://example.invalid/article"}, ensure_ascii=False
    ).encode("utf-8")
    source_path.write_bytes(source_bytes)
    payload = {
        "schema_version": "descriptive_project_mentions_v1",
        "mentions": [
            {
                "reference_key": "ukamau_housing_initiative_2016",
                "document_id": document_id,
                "case_mention_id": case_mention_id,
                "subject_label": "UKAMAU",
                "descriptive_label": "Mención de iniciativa comunitaria de vivienda social asociada a UKAMAU, sin identidad de proyecto resuelta",
                "identity_status": "descriptive_only_identity_unresolved",
                "source_url": "https://example.invalid/article",
                "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_file_path": source_relpath.as_posix(),
                "citations": citations,
                "linked_evidence_ids": [object_evidence_id, social_housing_evidence_id, geography_evidence_id],
            }
        ],
    }
    config_path = tmp_path / "descriptive_project_mentions.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT NOT NULL);
        CREATE TABLE case_mention (
            case_mention_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            decision_final_amplio TEXT NOT NULL
        );
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            case_mention_id TEXT NOT NULL,
            verified INTEGER NOT NULL,
            quote_text TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO document VALUES (?, ?)", (document_id, "https://example.invalid/article"))
    conn.execute("INSERT INTO case_mention VALUES (?, ?, 'include')", (case_mention_id, document_id))
    conn.executemany(
        "INSERT INTO evidence VALUES (?, ?, 1, ?)",
        [
                (object_evidence_id, case_mention_id, citations[0]["quote"]),
                (social_housing_evidence_id, case_mention_id, citations[1]["quote"]),
            (geography_evidence_id, case_mention_id, citations[2]["quote"]),
        ],
    )

    rows = bridge.load_descriptive_project_mentions(conn, config_path)

    payload["mentions"][0]["source_url"] = "https://example.invalid/another-article"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="URL del fulltext fuente no coincide"):
        bridge.load_descriptive_project_mentions(conn, config_path)
    payload["mentions"][0]["source_url"] = "https://example.invalid/article"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert len(rows) == 1
    assert rows[0]["identity_status"] == "descriptive_only_identity_unresolved"
    assert rows[0]["case_mention_id"] == case_mention_id
    assert rows[0]["linked_evidence_ids"] == [object_evidence_id, social_housing_evidence_id, geography_evidence_id]
    assert "project_id" not in rows[0]
    assert "canonical_project_id" not in rows[0]
    assert all(citation["quote_sha256"] == hashlib.sha256(citation["quote"].encode("utf-8")).hexdigest() for citation in rows[0]["citations"])
    assert bridge.persist_descriptive_project_mentions(conn, rows) == 1
    persisted_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(descriptive_project_reference)")
    }
    assert "project_id" not in persisted_columns
    assert "canonical_project_id" not in persisted_columns
    persisted = conn.execute(
        "SELECT case_mention_id, identity_status "
        "FROM descriptive_project_reference WHERE reference_key = ?",
        ("ukamau_housing_initiative_2016",),
    ).fetchone()
    assert persisted == (
        case_mention_id,
        "descriptive_only_identity_unresolved",
    )
    persisted_evidence_ids = [
        row[0]
        for row in conn.execute(
        "SELECT evidence_id FROM descriptive_project_reference_evidence "
            "WHERE reference_key = ? ORDER BY evidence_id",
            ("ukamau_housing_initiative_2016",),
        )
    ]
    assert persisted_evidence_ids == sorted([object_evidence_id, social_housing_evidence_id, geography_evidence_id])
    evidence_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(descriptive_project_reference_evidence)")
    }
    assert {"reference_key", "evidence_id", "quote_text", "quote_sha256"} <= evidence_columns
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_descriptive_project_reference_rejects_quote_not_equal_to_verified_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)
    quote = "Texto alterado pero con hash recalculado"
    source_text = quote
    document_id = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    case_mention_id = f"{document_id}:0"
    evidence_id = f"{case_mention_id}:objeto:1"
    source_relpath = Path("Fuentes/fulltext/content/tampered.json")
    source_path = tmp_path / source_relpath
    source_path.parent.mkdir(parents=True)
    source_bytes = json.dumps(
        {"text": source_text, "url": "https://example.invalid/article"}, ensure_ascii=False
    ).encode("utf-8")
    source_path.write_bytes(source_bytes)
    payload = {
        "schema_version": "descriptive_project_mentions_v1",
        "mentions": [
            {
                "reference_key": "tampered-quote",
                "document_id": document_id,
                "case_mention_id": case_mention_id,
                "subject_label": "UKAMAU",
                "descriptive_label": "Iniciativa descriptiva sin identidad resuelta",
                "identity_status": "descriptive_only_identity_unresolved",
                "source_url": "https://example.invalid/article",
                "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_file_path": source_relpath.as_posix(),
                "citations": [
                    {
                        "quote": quote,
                        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                        "evidence_ids": [evidence_id],
                    }
                ],
                "linked_evidence_ids": [evidence_id],
            }
        ],
    }
    config_path = tmp_path / "descriptive_project_mentions.json"
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT NOT NULL);
        CREATE TABLE case_mention (
            case_mention_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            decision_final_amplio TEXT NOT NULL
        );
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY,
            case_mention_id TEXT NOT NULL,
            verified INTEGER NOT NULL,
            quote_text TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO document VALUES (?, ?)", (document_id, "https://example.invalid/article"))
    conn.execute("INSERT INTO case_mention VALUES (?, ?, 'include')", (case_mention_id, document_id))
    conn.execute(
        "INSERT INTO evidence VALUES (?, ?, 1, ?)",
        (evidence_id, case_mention_id, "Cita verdadera distinta almacenada en evidence"),
    )

    with pytest.raises(ValueError, match="no contiene literalmente evidence.quote_text"):
        bridge.load_descriptive_project_mentions(conn, config_path)
    conn.close()


def test_descriptive_project_reference_rejects_stale_source_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)
    source_text = "fulltext estable"
    document_id = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    source_relpath = Path("Fuentes/fulltext/content/source.json")
    source_path = tmp_path / source_relpath
    source_path.parent.mkdir(parents=True)
    source_bytes = json.dumps(
        {"text": source_text, "url": "https://example.invalid/article"}, ensure_ascii=False
    ).encode("utf-8")
    source_path.write_bytes(source_bytes)
    mention = {
        "reference_key": "stale-source-test",
        "document_id": document_id,
        "case_mention_id": f"{document_id}:0",
        "subject_label": "X",
        "descriptive_label": "Descriptive test",
        "identity_status": "descriptive_only_identity_unresolved",
        "source_url": "https://example.invalid/article",
        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "source_file_path": source_relpath.as_posix(),
        "source_file_sha256": "0" * 64,
        "citations": [],
        "linked_evidence_ids": [],
    }
    config_path = tmp_path / "descriptive_project_mentions.json"
    conn = sqlite3.connect(":memory:")

    config_path.write_text(json.dumps({"schema_version": "descriptive_project_mentions_v1", "mentions": [mention]}), encoding="utf-8")
    with pytest.raises(ValueError, match="source_file_sha256 no coincide"):
        bridge.load_descriptive_project_mentions(conn, config_path)

    mention["source_file_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    mention["source_text_sha256"] = "1" * 64
    config_path.write_text(json.dumps({"schema_version": "descriptive_project_mentions_v1", "mentions": [mention]}), encoding="utf-8")
    with pytest.raises(ValueError, match="source_text_sha256/document_id no coincide"):
        bridge.load_descriptive_project_mentions(conn, config_path)
    conn.close()


def test_descriptive_project_reference_rejects_non_included_case_mention(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)
    source_text = "Artículo fuente sin citas, usado solo para probar elegibilidad."
    document_id = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    source_relpath = Path("Fuentes/fulltext/content/nonincluded.json")
    source_path = tmp_path / source_relpath
    source_path.parent.mkdir(parents=True)
    source_bytes = json.dumps(
        {"text": source_text, "url": "https://example.invalid/article"}, ensure_ascii=False
    ).encode("utf-8")
    source_path.write_bytes(source_bytes)
    payload = {
        "schema_version": "descriptive_project_mentions_v1",
        "mentions": [
            {
                "reference_key": "not-eligible",
                "document_id": document_id,
                "case_mention_id": f"{document_id}:0",
                "subject_label": "X",
                "descriptive_label": "descriptive only",
                "identity_status": "descriptive_only_identity_unresolved",
                "source_url": "https://example.invalid/article",
                "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                "source_file_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_file_path": source_relpath.as_posix(),
                "citations": [],
                "linked_evidence_ids": [],
            }
        ],
    }
    config_path = tmp_path / "descriptive_project_mentions.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT NOT NULL);
        CREATE TABLE case_mention (case_mention_id TEXT PRIMARY KEY, document_id TEXT, decision_final_amplio TEXT);
        CREATE TABLE evidence (evidence_id TEXT PRIMARY KEY, case_mention_id TEXT, verified INTEGER);
        """
    )
    conn.execute("INSERT INTO document VALUES (?, ?)", (document_id, "https://example.invalid/article"))
    conn.execute("INSERT INTO case_mention VALUES (?, ?, 'exclude')", (f"{document_id}:0", document_id))

    with pytest.raises(ValueError, match="no está en estado include"):
        bridge.load_descriptive_project_mentions(conn, config_path)
    conn.close()


def test_descriptive_subject_cannot_become_project_from_same_document():
    descriptive_mentions = [
        {
            "reference_key": "ukamau_descriptive",
            "document_id": "doc-1",
            "subject_label": "UKAMAU",
        }
    ]
    records = [
        {
            "document_id": "doc-1",
            "proyectos_mencionados": [{"nombre": "Proyecto inmobiliario comunitario UKAMAU"}],
        }
    ]

    with pytest.raises(ValueError, match="requiere adjudicación antes de crear PROJECT"):
        bridge.reject_descriptive_project_identity_collisions(records, descriptive_mentions)

    # La guarda no bloquea proyectos diferentes en el mismo artículo ni una
    # mención UKAMAU perteneciente a otro documento/caso.
    bridge.reject_descriptive_project_identity_collisions(
        [
            {"document_id": "doc-1", "proyectos_mencionados": ["Proyecto Las Rejas"]},
            {"document_id": "doc-2", "proyectos_mencionados": ["UKAMAU"]},
        ],
        descriptive_mentions,
    )


def test_project_build_rejects_identity_collision_before_overwriting_output(tmp_path, monkeypatch):
    source_path = tmp_path / "source.sqlite"
    output_path = tmp_path / "output.sqlite"
    output_path.write_bytes(b"existing-output-must-survive")
    source_conn = sqlite3.connect(source_path)
    source_conn.executescript(
        """
        CREATE TABLE document (document_id TEXT PRIMARY KEY, url TEXT NOT NULL);
        CREATE TABLE document_case_unit (
            document_id TEXT PRIMARY KEY,
            unidad_caso_tipo TEXT,
            tiene_error INTEGER,
            correccion_proyectos_mencionados_json TEXT,
            correccion_nombre_proyecto TEXT
        );
        """
    )
    source_conn.execute("INSERT INTO document VALUES ('doc-ukamau', 'https://example.invalid/article')")
    source_conn.commit()
    source_conn.close()

    monkeypatch.setattr(bridge, "SOURCE_WAREHOUSE", source_path)
    monkeypatch.setattr(bridge, "OUTPUT_WAREHOUSE", output_path)
    monkeypatch.setattr(bridge, "ACTOR_SECOND_PASS_PATH", tmp_path / "missing-second-pass.jsonl")
    monkeypatch.setattr(bridge, "_validate_source_warehouse", lambda _path: None)
    monkeypatch.setattr(
        bridge,
        "load_descriptive_project_mentions",
        lambda _conn, _path: [
            {
                "reference_key": "ukamau_descriptive",
                "document_id": "doc-ukamau",
                "subject_label": "UKAMAU",
            }
        ],
    )
    monkeypatch.setattr(
        bridge,
        "load_v3_3_records",
        lambda **_kwargs: {
            "record-1": {
                "url": "https://example.invalid/article",
                "proyectos_mencionados": [{"nombre": "Proyecto inmobiliario comunitario UKAMAU"}],
            }
        },
    )

    with pytest.raises(ValueError, match="requiere adjudicación antes de crear PROJECT"):
        bridge.main()

    assert output_path.read_bytes() == b"existing-output-must-survive"


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


def test_normalize_keeps_alphanumeric_lot_suffix_so_lote_18a_does_not_collapse_with_lote_18():
    """[2026-09-29] La puntuacion separaba 'Lote 18-A' en 'lote 18 a' y 'a' cae como stopword: colapsaba con
    'Lote 18' aunque las fuentes distinguen el lote completo de una parte. Un sufijo de letra pegado por
    guion a un numero es parte del rotulo."""
    n = bridge.normalize_project_name
    assert n("Lote 18") == "lote 18"
    assert n("Lote 18-A") == "lote 18a"
    assert n("Lote 18-A") != n("Lote 18")
    assert n("Lote 18-A1") == "lote 18a1"
    assert n("Lote 18-A") != n("Lote 18-A1")


def test_normalize_does_not_glue_hyphenated_ranges_or_spaced_letters():
    n = bridge.normalize_project_name
    assert n("Torres 15-20") == "torres 15 20"
    assert n("calle Vital Apoquindo 1.400-1.450-1.500") == "calle vital apoquindo 1 400 1 450 1 500"
    assert n("Villa Panamericana - Lote B") == "villa panamericana lote b"
    assert n("Proyecto de Ley 2020 - a partir de hoy") == n("Ley 2020 a partir de hoy")


def test_adjudicated_index_corrections_are_consistent_with_the_warehouse_and_the_fulltext():
    """[2026-09-29] Cada enlace adjudicado apunta a una case_mention include de su propio documento, cita evidencia
    de objeto verificada que existe tal cual en el warehouse, y la cita aparece en el fulltext."""
    import json as _json
    import re as _re

    path = bridge.VERIFIED_INDEX_CORRECTIONS_PATH
    corrections = _json.loads(path.read_text(encoding="utf-8"))["corrections"]
    assert len(corrections) == 18
    warehouse = PROJECT_ROOT / "data" / "warehouse.sqlite"
    if not warehouse.exists():
        pytest.skip("warehouse.sqlite no existe en este entorno")
    conn = sqlite3.connect(warehouse)
    keys = set()
    for c in corrections:
        key = (c["document_id"], c["nombre_proyecto"])
        assert key not in keys
        keys.add(key)
        assert c["case_mention_id"] == f"{c['document_id']}:{c['case_mention_index']}"
        decision = conn.execute(
            "SELECT decision_final_amplio FROM case_mention WHERE case_mention_id = ?", (c["case_mention_id"],)
        ).fetchone()
        assert decision is not None and decision[0] == "include", c["reference_key"]
        for ev_id in c["linked_evidence_ids"]:
            row = conn.execute(
                "SELECT case_mention_id, verified FROM evidence WHERE evidence_id = ?", (ev_id,)
            ).fetchone()
            assert row == (c["case_mention_id"], 1), (c["reference_key"], ev_id)
        assert conn.execute(
            "SELECT 1 FROM enrichment_project_mention WHERE document_id = ? AND nombre_proyecto = ?",
            (c["document_id"], c["nombre_proyecto"]),
        ).fetchone(), c["reference_key"]
    conn.close()
    content_root = PROJECT_ROOT / "Fuentes" / "fulltext" / "content"
    if not content_root.exists():
        pytest.skip("fulltext local no disponible en este entorno")
    squash = lambda s: _re.sub(r"\s+", " ", s)
    for c in corrections:
        text = _json.loads((PROJECT_ROOT / c["source_file_path"]).read_text(encoding="utf-8"))["text"]
        for citation in c["citations"]:
            assert squash(citation["quote"]) in squash(text), (c["reference_key"], citation["quote"][:60])
