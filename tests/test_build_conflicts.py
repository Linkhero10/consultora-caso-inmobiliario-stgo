"""Pruebas de la capa CONFLICT (conflict / conflict_case / conflict_project
/ document_conflict / conflict_relation), separada de PROJECT/PROJECT_PHASE/
CASE. No llama a ninguna API; usa datos sinteticos para la logica de
agrupacion y verifica contra el warehouse real los 2 casos de prueba
adversarial que motivaron el diseno (Sol, 2026-09-18):

1. Cementerio Parque Santiago / Teleferico Bicentenario -- 2 project.case_id
   distintos y correctos, 1 solo conflicto (deben terminar en el MISMO
   conflict_id).
2. Poblacion La Victoria / Rancagua Express -- posible trayectoria
   territorial longitudinal vs. conflictos distintos; el esquema debe
   representarlo como 2 conflict_id SEPARADOS, vinculados por una
   conflict_relation pendiente de decision humana, NUNCA fusionados.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import build_conflicts as reg  # noqa: E402


def test_stable_conflict_id_is_deterministic_and_order_independent():
    a = reg._stable_conflict_id(["case_b", "case_a"])
    b = reg._stable_conflict_id(["case_a", "case_b"])
    assert a == b
    assert a.startswith("conflict:")


def test_union_find_unions_only_via_transitive_closure():
    uf = reg.UnionFind(["a", "b", "c", "d"])
    uf.union("a", "b")
    uf.union("b", "c")
    assert uf.find("a") == uf.find("c")
    assert uf.find("a") != uf.find("d")


def _doc(document_id, relaciones, justificacion="x", title="t"):
    return {"document_id": document_id, "title": title, "justificacion_sol": justificacion, "relaciones_case_groups_sol": relaciones}


def test_build_case_groups_unions_mismo_conflicto_but_not_focal_or_contextual():
    all_case_ids = ["case_1", "case_2", "case_3"]
    documentos = [
        _doc("d1", [{"case_ids": ["case_1", "case_2"], "relacion": "mismo_conflicto", "project_relation": "distinct_conflict_objects"}]),
        _doc("d2", [
            {"case_ids": ["case_3"], "relacion": "focal"},
            {"case_ids": ["case_1"], "relacion": "contextual", "project_relation": "contextual"},
        ]),
    ]
    groups = reg.build_case_groups(all_case_ids, documentos)
    grouped_members = sorted(groups.values())
    assert ["case_1", "case_2"] in grouped_members
    assert ["case_3"] in grouped_members  # 'focal' no une case_3 con case_1


def test_build_case_groups_does_not_union_conflictos_distintos():
    all_case_ids = ["case_a", "case_b"]
    documentos = [_doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos", "project_relation": "distinct_conflict_objects"}])]
    groups = reg.build_case_groups(all_case_ids, documentos)
    assert sorted(groups.values()) == [["case_a"], ["case_b"]]


def test_build_conflict_relations_flags_conflictos_distintos_as_pending_when_gate_still_caso_unico():
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:BBB"}
    documentos = [_doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}], justificacion="territorio compartido")]
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, {"d1": "caso_unico"})
    assert len(relations) == 1
    rel = relations[0]
    assert {rel["conflict_id_a"], rel["conflict_id_b"]} == {"conflict:AAA", "conflict:BBB"}
    assert rel["review_status"] == "pending_human_decision"


def test_build_conflict_relations_marks_resolved_keep_separate_when_gate_already_reclassified():
    """Hallazgo real de Sol: la v1 marcaba TODAS las relaciones
    'conflictos_distintos' como pendientes, incluso cuando el documento ya
    habia sido reclasificado (UPC, Recuperacion de barrios -- ya NO son
    'caso_unico'). Solo debe quedar pendiente si el gate sigue en
    caso_unico."""
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:BBB"}
    documentos = [_doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}])]
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, {"d1": "documento_comparativo_panoramico"})
    assert len(relations) == 1
    assert relations[0]["review_status"] == "resolved_keep_separate"


def test_build_conflict_relations_stays_pending_if_any_evidence_document_still_pending():
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:BBB"}
    documentos = [
        _doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}]),
        _doc("d2", [{"case_ids": ["case_a", "case_b"], "relacion": "conflictos_distintos"}]),
    ]
    gate = {"d1": "documento_comparativo_panoramico", "d2": "caso_unico"}
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, gate)
    assert len(relations) == 1
    assert relations[0]["review_status"] == "pending_human_decision"


def test_build_conflict_relations_ignores_focal_and_mismo_conflicto():
    case_id_to_conflict = {"case_a": "conflict:AAA", "case_b": "conflict:AAA"}
    documentos = [
        _doc("d1", [{"case_ids": ["case_a", "case_b"], "relacion": "mismo_conflicto"}]),
        _doc("d2", [{"case_ids": ["case_a"], "relacion": "focal"}]),
    ]
    relations = reg.build_conflict_relations(documentos, case_id_to_conflict, {"d1": "caso_unico", "d2": "caso_unico"})
    assert relations == []


# --- Fix 1A: respaldo de evidencia (unitarias, datos sinteticos) ---


def test_norm_strips_accents_case_and_extra_whitespace():
    assert reg._norm("  Torre  Central  ") == "torre central"
    assert reg._norm("Línea 7") == "linea 7"


def test_mention_has_case_backing_matches_raw_inside_quote():
    assert reg._mention_has_case_backing("Torre Central", ["se aprobo la torre central en 2024"]) is True


def test_mention_has_case_backing_matches_quote_inside_raw():
    assert reg._mention_has_case_backing("Proyecto Línea 7 Metro de Santiago", ["linea 7 metro"]) is True


def test_mention_has_case_backing_no_match_returns_false():
    assert reg._mention_has_case_backing("Museo de la Memoria en Punta Arenas", ["guetos verticales en estacion central"]) is False


def test_mention_has_case_backing_never_fuzzy():
    """Palabras parecidas pero no en relacion de substring nunca deben
    calzar -- el detector esta congelado a exact_substring_v1."""
    assert reg._mention_has_case_backing("Edificio Central Park", ["torre parque central"]) is False


def test_project_backing_evidence_finds_matching_quote_across_documents():
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["cm1"]}
    objeto_by_cm = {"cm1": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, {})
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "cm1"
    assert rows[0]["evidence_id"] == "e1"
    assert rows[0]["detector_version"] == reg.DETECTOR_VERSION


def test_project_backing_evidence_empty_when_case_mention_is_excluded():
    """El documento tiene una mencion, pero su unico case_mention NO esta
    incluido (decision_final_amplio != include) -- included_by_doc no lo
    lista, asi que no puede haber respaldo."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc: dict = {}  # d1 no tiene ningun case_mention incluido
    objeto_by_cm = {"cm1": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, {})
    assert rows == []


def test_project_backing_evidence_empty_when_no_objeto_evidence_for_that_mention():
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["cm1"]}
    objeto_by_cm: dict = {}  # sin evidencia de objeto verificada para cm1
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, {})
    assert rows == []


def test_project_backing_evidence_marks_document_level_multi_case_ambiguity():
    """El esquema actual no vincula proyecto y case_mention dentro del
    mismo documento. La fila debe conservar esa limitación explícitamente,
    especialmente cuando hay más de una mención incluida con objeto."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["cm1", "cm2"]}
    objeto_by_cm = {
        "cm1": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}],
        "cm2": [{"evidence_id": "e2", "quote_text": "la Torre Central tambien", "quote_norm": "la torre central tambien"}],
    }
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, {})
    assert len(rows) == 2
    assert {row["backing_scope"] for row in rows} == {"document_level_case_mention_without_project_link"}
    assert {row["document_case_mention_count"] for row in rows} == {2}
    assert {row["document_object_case_mention_count"] for row in rows} == {2}
    assert {row["ambiguous_multi_case_document"] for row in rows} == {1}


def test_build_conflict_backing_uniform_no_multi_case_exception():
    """Bug real que la validacion N=150 encontro: 'n_case_ids > 1 -> siempre
    respaldado' es incorrecto (Aeropuerto Los Cerrillos, Aldea del
    Encuentro). El detector debe aplicarse igual sin importar cuantos
    case_id tenga el conflicto."""
    projects = [("p1", "Proyecto Sin Evidencia Real")]
    case_id_by_project = {"p1": "case1"}
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Proyecto Sin Evidencia Real"}]}
    included_by_doc = {"d1": ["cm1"]}
    objeto_by_cm = {"cm1": [{"evidence_id": "e1", "quote_text": "algo completamente distinto", "quote_norm": "algo completamente distinto"}]}
    label, respaldo, rows = reg._build_conflict_backing(
        "conflict:x", projects, case_id_by_project, mentions_by_project, included_by_doc, objeto_by_cm, {}
    )
    assert respaldo == "sin_respaldo_exact_quote_detectado"
    assert rows == []


def test_build_conflict_backing_label_prefers_backed_project_over_incidental_mention():
    """Caso real verificado (Museo de la Memoria / guetos verticales
    Estacion Central): el conflicto tiene 2 proyectos, solo 1 respaldado --
    el label debe salir del respaldado, no del primero alfabetico entre
    todos (que era exactamente el bug encontrado)."""
    projects = [("p_incidental", "Aaa Proyecto Incidental Sin Evidencia"), ("p_real", "Zzz Proyecto Real Respaldado")]
    case_id_by_project = {"p_incidental": "case1", "p_real": "case1"}
    mentions_by_project = {
        "p_incidental": [{"document_id": "d1", "raw_nombre_proyecto": "Aaa Proyecto Incidental Sin Evidencia"}],
        "p_real": [{"document_id": "d1", "raw_nombre_proyecto": "Zzz Proyecto Real Respaldado"}],
    }
    included_by_doc = {"d1": ["cm1"]}
    objeto_by_cm = {"cm1": [{"evidence_id": "e1", "quote_text": "zzz proyecto real respaldado", "quote_norm": "zzz proyecto real respaldado"}]}
    label, respaldo, rows = reg._build_conflict_backing(
        "conflict:x", projects, case_id_by_project, mentions_by_project, included_by_doc, objeto_by_cm, {}
    )
    assert label == "Zzz Proyecto Real Respaldado"
    assert respaldo == "respaldo_exact_quote_detectado"
    assert len(rows) == 1
    assert rows[0]["backing_scope"] == "document_level_case_mention_without_project_link"
    assert rows[0]["ambiguous_multi_case_document"] == 0


def test_build_conflict_backing_fallback_label_when_none_backed():
    projects = [("p2", "Bbb Segundo"), ("p1", "Aaa Primero")]
    case_id_by_project = {"p1": "case1", "p2": "case1"}
    label, respaldo, rows = reg._build_conflict_backing("conflict:x", projects, case_id_by_project, {}, {}, {}, {})
    assert label == "Aaa Primero"  # fallback: primero alfabetico entre TODOS
    assert respaldo == "sin_respaldo_exact_quote_detectado"
    assert rows == []


# --- Fix 1D: integracion de v3.3 (case_mention_index verificado) al backing ---


def test_project_backing_evidence_uses_v3_3_index_directly_when_covered():
    """Cuando la mencion esta cubierta por v3.3 con un indice valido que pasa
    el filtro de decision/evidencia, se usa DIRECTAMENTE ese case_mention_id
    -- no se ejecuta ninguna comparacion de substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0", "d1:1"]}
    objeto_by_cm = {
        "d1:1": [{"evidence_id": "e1", "quote_text": "una cita que no menciona el proyecto", "quote_norm": "una cita que no menciona el proyecto"}],
    }
    v3_3_links = {("d1", "torre central"): 1}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "d1:1"
    assert rows[0]["detector_version"] == reg.DETECTOR_VERSION_V3_3
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3
    assert rows[0]["ambiguous_multi_case_document"] == 0


def test_project_backing_evidence_v3_3_null_suppresses_substring_fallback():
    """Si v3.3 dice explicitamente que ninguna case_mention es el objeto
    (indice null), NO debe caer al substring -- v3.3 es una fuente mas
    confiable que la heuristica para esa mencion puntual, aunque el
    substring hubiera encontrado un match."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la torre central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): None}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert rows == []


def test_project_backing_evidence_v3_3_index_excluded_gives_no_backing_no_fallback():
    """Si v3.3 apunta a un case_mention que NO paso el filtro (no esta en
    included_by_doc, ej. decision_final_amplio != include), no hay backing
    por esa via -- tampoco cae al substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc: dict = {}  # d1:0 no esta incluido
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la torre central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 0}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert rows == []


def test_project_backing_evidence_falls_back_to_substring_when_not_covered_by_v3_3():
    """Documento fuera del universo v3.3 (no aparece en el dict): el
    comportamiento debe ser IDENTICO al detector exact_substring_v1
    original -- regresion cero para el resto del corpus."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["cm1"]}
    objeto_by_cm = {"cm1": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    rows_without_v3_3_dict = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, {})
    rows_with_unrelated_v3_3_dict = reg._project_backing_evidence(
        "p1", mentions_by_project, included_by_doc, objeto_by_cm, {("otro_doc", "otro proyecto"): 0}
    )
    assert rows_without_v3_3_dict == rows_with_unrelated_v3_3_dict
    assert len(rows_without_v3_3_dict) == 1
    assert rows_without_v3_3_dict[0]["detector_version"] == reg.DETECTOR_VERSION


def test_project_backing_evidence_v3_3_index_excluded_falls_back_to_duplicate_group_sibling():
    """Fix 1E: classify.py a veces fragmenta el MISMO objeto real en 2+
    case_mentions (ej. Bellavista: idx1 include, idx2 casi-duplicado
    exclude). Si v3.3 apunto al miembro que NO paso el filtro
    (decision/evidencia), pero un hermano de su grupo de duplicados SI lo
    pasa, se usa ese hermano -- nunca se pierde el backing solo porque
    classify.py duplico el objeto."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    # d1:1 es el indice que v3.3 eligio, pero NO esta incluido (exclude).
    # d1:0 SI esta incluido y tiene evidencia -- es su hermano de duplicado.
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 1}
    duplicate_group_members = {"d1:0": ["d1:0", "d1:1"], "d1:1": ["d1:0", "d1:1"]}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links, duplicate_group_members)
    assert len(rows) == 1
    assert rows[0]["case_mention_id"] == "d1:0"
    assert rows[0]["detector_version"] == reg.DETECTOR_VERSION_V3_3
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP


def test_project_backing_evidence_v3_3_duplicate_group_fallback_tags_mixed_decision_explicitly():
    """[Fix 1E hardening, hallazgo de revision externa] El fallback via grupo
    duplicado no distinguia si el grupo tenia decision mixta (include +
    exclude/uncertain entre sus miembros) -- una senal real de que el match
    pudo ser mas arriesgado (el propio clasificador no fue consistente sobre
    el objeto). Ahora debe quedar marcado con un match_method distinto,
    nunca mezclado silenciosamente con el caso no-mixto, para que sea
    auditable por separado."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 1}
    duplicate_group_members = {"d1:0": ["d1:0", "d1:1"], "d1:1": ["d1:0", "d1:1"]}
    decision_mixed_by_cm = {"d1:0": True, "d1:1": True}
    rows = reg._project_backing_evidence(
        "p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links, duplicate_group_members, decision_mixed_by_cm
    )
    assert len(rows) == 1
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP_MIXED_DECISION
    assert rows[0]["match_method"] != reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP


def test_project_backing_evidence_v3_3_duplicate_group_fallback_non_mixed_uses_plain_match_method():
    """Contraparte del test anterior: un grupo sin decision mixta debe seguir
    usando el match_method original, no el marcado como mixto."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc = {"d1": ["d1:0"]}
    objeto_by_cm = {"d1:0": [{"evidence_id": "e1", "quote_text": "la Torre Central", "quote_norm": "la torre central"}]}
    v3_3_links = {("d1", "torre central"): 1}
    duplicate_group_members = {"d1:0": ["d1:0", "d1:1"], "d1:1": ["d1:0", "d1:1"]}
    decision_mixed_by_cm = {"d1:0": False, "d1:1": False}
    rows = reg._project_backing_evidence(
        "p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links, duplicate_group_members, decision_mixed_by_cm
    )
    assert len(rows) == 1
    assert rows[0]["match_method"] == reg.MATCH_METHOD_V3_3_VIA_DUPLICATE_GROUP


def test_project_backing_evidence_v3_3_no_duplicate_group_sibling_still_empty():
    """Sin duplicate_group_members (o sin hermano valido), el comportamiento
    debe seguir siendo el mismo de antes de Fix 1E: sin backing, sin caer al
    substring."""
    mentions_by_project = {"p1": [{"document_id": "d1", "raw_nombre_proyecto": "Torre Central"}]}
    included_by_doc: dict = {}
    objeto_by_cm: dict = {}
    v3_3_links = {("d1", "torre central"): 0}
    rows = reg._project_backing_evidence("p1", mentions_by_project, included_by_doc, objeto_by_cm, v3_3_links)
    assert rows == []


def test_backing_summary_exposes_partial_coverage_and_label_source():
    projects = [("p1", "A Proyecto"), ("p2", "B Proyecto")]
    rows = [{"project_id": "p1", "ambiguous_multi_case_document": 0}]
    summary = reg._backing_summary(projects, rows)
    assert summary == {
        "n_projects_backed": 1,
        "n_projects_unbacked": 1,
        "coverage_backing": "parcial",
        "label_source_project_id": "p1",
        "n_documents_ambiguous_backing": 0,
    }


# --- Pruebas de prueba adversarial contra el warehouse real ---

CEMENTERIO_CASE = "92ddfd13158c1f43afb3e7c9"
TELEFERICO_CASE = "bfccc2aaade8650742980e81"
LA_VICTORIA_CASE = "c86e9f143c9c10888f579a49"
RANCAGUA_EXPRESS_CASE = "51e44358f119f13da08889fb"


def _connect_or_skip():
    import sqlite3

    if not reg.WAREHOUSE.exists():
        import pytest

        pytest.skip("warehouse.sqlite no existe en este entorno")
    return sqlite3.connect(reg.WAREHOUSE)


def test_cementerio_y_teleferico_terminan_en_el_mismo_conflict_id():
    conn = _connect_or_skip()
    rows = conn.execute(
        "SELECT case_id, conflict_id FROM conflict_case WHERE case_id IN (?, ?)",
        (CEMENTERIO_CASE, TELEFERICO_CASE),
    ).fetchall()
    conn.close()
    by_case = dict(rows)
    assert len(by_case) == 2
    assert by_case[CEMENTERIO_CASE] == by_case[TELEFERICO_CASE]


def test_la_victoria_y_rancagua_express_quedan_en_conflictos_distintos_con_relacion_pendiente():
    conn = _connect_or_skip()
    rows = dict(
        conn.execute(
            "SELECT case_id, conflict_id FROM conflict_case WHERE case_id IN (?, ?)",
            (LA_VICTORIA_CASE, RANCAGUA_EXPRESS_CASE),
        ).fetchall()
    )
    assert rows[LA_VICTORIA_CASE] != rows[RANCAGUA_EXPRESS_CASE]

    pending = conn.execute(
        "SELECT relation_type, review_status FROM conflict_relation "
        "WHERE (conflict_id_a = ? AND conflict_id_b = ?) OR (conflict_id_a = ? AND conflict_id_b = ?)",
        (rows[LA_VICTORIA_CASE], rows[RANCAGUA_EXPRESS_CASE], rows[RANCAGUA_EXPRESS_CASE], rows[LA_VICTORIA_CASE]),
    ).fetchone()
    assert pending is not None
    assert pending[1] == "pending_human_decision"
    conn.close()


def test_document_conflict_case_safe_never_includes_mentioned_unreviewed_or_panoramic_mention():
    """Hallazgo real de Sol: filtrar solo por unidad_caso_tipo='caso_unico'
    no bastaba -- dentro de un documento caso_unico siguen existiendo
    document_conflict con role='mentioned_unreviewed' (mencion mecanica
    sin revisar) o 'panoramic_mention' (el propio caso La Victoria, cuyo
    gate sigue pendiente). La vista 'safe' debe exigir ademas
    role IN ('focal','co_focal')."""
    conn = _connect_or_skip()
    bad = conn.execute(
        "SELECT COUNT(*) FROM document_conflict_case_safe WHERE role NOT IN ('focal', 'co_focal')"
    ).fetchone()[0]
    conn.close()
    assert bad == 0


def test_la_victoria_excluded_from_document_conflict_case_safe_while_pending():
    """Prueba adversarial directa: La Victoria/Rancagua Express es
    unidad_caso_tipo='caso_unico' (el gate sigue pendiente) pero sus 2
    conflictos son 'conflictos_distintos' -> role='panoramic_mention'.
    Con el filtro viejo (solo unidad_caso_tipo) ambos habrian entrado a
    la vista safe. Deben quedar fuera hasta que se resuelva el gate."""
    conn = _connect_or_skip()
    la_victoria_doc = "34c26e5aaf4f48a74d16ad587a7b0384cb459c157714e592725284560dea1ce9"
    rows = conn.execute(
        "SELECT COUNT(*) FROM document_conflict_case_safe WHERE document_id = ?", (la_victoria_doc,)
    ).fetchone()[0]
    conn.close()
    assert rows == 0


def test_document_conflict_case_extended_allows_contextual_but_not_unreviewed_or_panoramic():
    conn = _connect_or_skip()
    roles = {r[0] for r in conn.execute("SELECT DISTINCT role FROM document_conflict_case_extended")}
    conn.close()
    assert roles <= {"focal", "co_focal", "contextual_mention"}
    assert "mentioned_unreviewed" not in roles
    assert "panoramic_mention" not in roles


def test_case_safe_is_subset_of_case_extended_which_is_subset_of_full_table():
    conn = _connect_or_skip()
    n_safe = conn.execute("SELECT COUNT(*) FROM document_conflict_case_safe").fetchone()[0]
    n_extended = conn.execute("SELECT COUNT(*) FROM document_conflict_case_extended").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM document_conflict").fetchone()[0]
    conn.close()
    assert 0 < n_safe <= n_extended <= n_total


def test_conflict_tables_have_no_foreign_key_violations():
    conn = _connect_or_skip()
    conn.execute("PRAGMA foreign_keys = ON")
    issues = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
    assert issues == []


def test_every_case_id_belongs_to_exactly_one_conflict():
    conn = _connect_or_skip()
    dup = conn.execute(
        "SELECT case_id, COUNT(DISTINCT conflict_id) c FROM conflict_case GROUP BY case_id HAVING c > 1"
    ).fetchall()
    conn.close()
    assert dup == []


def test_document_conflict_from_sol_evidence_never_overlaps_trivial_source_for_same_document():
    """Los 63 documentos evidenciados no deben tener tambien filas
    'trivial_from_project_mention' -- serian una fuente mecanica mas
    debil pisando (o duplicando) la revision humana."""
    conn = _connect_or_skip()
    rows = conn.execute(
        """
        SELECT document_id FROM document_conflict WHERE source = 'trivial_from_project_mention'
        INTERSECT
        SELECT document_id FROM document_conflict WHERE source = 'conflict_unit_63_sol'
        """
    ).fetchall()
    conn.close()
    assert rows == []


def test_trivial_conflicts_have_low_confidence_label_and_multi_case_have_high():
    conn = _connect_or_skip()
    bad = conn.execute(
        "SELECT COUNT(*) FROM conflict WHERE (n_case_ids = 1 AND confidence != 'baja_derivado_mecanicamente') "
        "OR (n_case_ids > 1 AND confidence != 'alta_revisado_por_sol')"
    ).fetchone()[0]
    conn.close()
    assert bad == 0


def test_quilicura_conflict_role_is_co_focal_not_mentioned_unreviewed():
    """Hallazgo real de Sol: la relacion 'mismo_proyecto' (alias, sin rol
    en ROLE_BY_RELACION) caia al default 'mentioned_unreviewed' y ganaba
    el dedupe por orden de aparicion, aunque el mismo documento tambien
    aportara 'mismo_conflicto' (co_focal) para el mismo conflict_id."""
    conn = _connect_or_skip()
    quilicura_doc = "046f59be624a98cec6b4d3d0823f5bd665ec2345cc84e5693c85690f7fb7bd74"
    row = conn.execute(
        "SELECT role, source FROM document_conflict WHERE document_id = ? AND source = 'conflict_unit_63_sol'",
        (quilicura_doc,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "co_focal"


def test_upc_and_recuperacion_de_barrios_relations_are_resolved_not_pending():
    """Hallazgo real de Sol: UPC y Recuperacion de barrios ya fueron
    adjudicados (reclasificados a documento_comparativo_panoramico via
    apply_conflict_unit_gate_decisions.py) -- su conflict_relation no
    deberia seguir marcada pending_human_decision."""
    conn = _connect_or_skip()
    upc_doc = "1b00c0136d4b855eed855b1a5f48ceb7f01e4c9b0d96c8d9666fafd292e043cb"
    barrios_doc = "2f8d68a763424a1a260b77244ff266655c36acb93e926b1f6bf2d68b3cfdb2a8"
    for doc_id in (upc_doc, barrios_doc):
        note_rows = conn.execute("SELECT note, review_status FROM conflict_relation").fetchall()
        matching = [row for row in note_rows if doc_id in row[0]]
        assert matching, f"no se encontro conflict_relation para {doc_id}"
        assert matching[0][1] == "resolved_keep_separate"
    conn.close()


def test_la_victoria_relation_stays_pending_human_decision():
    conn = _connect_or_skip()
    la_victoria_doc = "34c26e5aaf4f48a74d16ad587a7b0384cb459c157714e592725284560dea1ce9"
    note_rows = conn.execute("SELECT note, review_status FROM conflict_relation").fetchall()
    matching = [row for row in note_rows if la_victoria_doc in row[0]]
    conn.close()
    assert matching
    assert matching[0][1] == "pending_human_decision"


# --- Fix 1A: regresion real contra el warehouse ---


def test_respaldo_evidencia_equivalence_with_conflict_evidence_backing():
    """Invariante: conflict.respaldo_evidencia = 'respaldo_exact_quote_detectado'
    SSI existe >=1 fila en conflict_evidence_backing para ese conflict_id."""
    conn = _connect_or_skip()
    mismatch = conn.execute(
        """
        SELECT c.conflict_id FROM conflict c
        LEFT JOIN (SELECT DISTINCT conflict_id FROM conflict_evidence_backing) b
          ON b.conflict_id = c.conflict_id
        WHERE (c.respaldo_evidencia = 'respaldo_exact_quote_detectado') != (b.conflict_id IS NOT NULL)
        """
    ).fetchall()
    conn.close()
    assert mismatch == []


def test_museo_de_la_memoria_conflict_has_no_backing():
    """Caso real verificado a mano en la validacion N=150: el documento
    (biografia de Miguel Lawner) menciona 'Museo de la Memoria y Derechos
    Humanos en Punta Arenas' de pasada; la evidencia real del documento es
    sobre los guetos verticales de Estacion Central. Sin case_mention
    incluido que respalde ese nombre -- debe quedar sin respaldo."""
    conn = _connect_or_skip()
    row = conn.execute(
        "SELECT respaldo_evidencia FROM conflict WHERE conflict_id = 'conflict:322c7c3d88d4ff08de440c56'"
    ).fetchone()
    conn.close()
    assert row is not None, "el caso Museo debe estar presente en el warehouse de Fix 1A"
    assert row[0] == "sin_respaldo_exact_quote_detectado"


def test_aeropuerto_los_cerrillos_current_fix1a_state():
    """Bug real que la validacion N=150 encontro: n_case_ids>1 (revision
    humana de los 63) NO garantiza que el conflicto este bien construido.
    Este test no afirma que la fusion quedo corregida (eso es Fix 1B) --
    solo que la regla de respaldo se aplico sin excepcion automatica. El
    resultado empírico publicado de Fix 1A se fija explícitamente aquí para
    que una reconstrucción silenciosa del warehouse no pueda cambiarlo sin
    hacer fallar la regresión.

    [ACTUALIZADO Fix 1D, 2026-09-24] n_backing subio de 1 a 4: la mencion
    'Ciudad Portal Bicentenario' de este conflicto ahora esta cubierta por
    v3.3 (detector_version='v3_3_verified_index'), que la ancla a UN
    case_mention_id real -- pero ese case_mention tiene 4 citas 'objeto'
    verificadas distintas (evidence_id ...:objeto:0 a ...:objeto:3), y el
    diseno registra 1 fila de provenance por cada (case_mention, evidencia)
    -- mismo grano que ya usaba el detector exact_substring_v1 original.
    Verificado a mano contra el warehouse real, no es una regresion."""
    conn = _connect_or_skip()
    row = conn.execute(
        "SELECT n_case_ids, respaldo_evidencia, "
        "(SELECT COUNT(*) FROM conflict_evidence_backing b "
        "WHERE b.conflict_id = c.conflict_id) AS n_backing "
        "FROM conflict c WHERE c.conflict_id = 'conflict:4f725d7265297513738bf370'"
    ).fetchone()
    conn.close()
    assert row is not None, "el caso Aeropuerto debe estar presente en el warehouse de Fix 1A"
    n_case_ids, respaldo, n_backing = row
    assert n_case_ids == 2  # sigue siendo multi-case (Fix 1B no aplicado todavía)
    assert respaldo == "respaldo_exact_quote_detectado"
    assert n_backing == 4


def test_hospital_ochagavia_pac_document_no_longer_focal():
    """Fix 1B (2026-09-22): adjudicacion de uno de los 4 desacuerdos reales
    de conflictos_distintos_fusionados. El documento 'Pedro Aguirre Cerda
    toma medidas...' estaba clasificado con nombre_proyecto='Nucleo
    Ochagavia' pero su contenido real es sobre anteproyectos genericos de
    altura, sin vinculo con la reconversion especifica del sitio -- eso lo
    hacia aparecer como evidencia focal (verificada) del conflicto Hospital
    Ochagavia/Nucleo Ochagavia. Se corrigio con correccion_nombre_proyecto=''
    (document_case_unit), protegido con tiene_error=1 explicito.

    La union de case_id en CONFLICT se mantiene intacta a proposito (no se
    convirtio en Fix 1B una separacion automatica): su documento fundador
    ('El espacio y la memoria...') es coherente por si solo -- un mismo
    inmueble, una sola trayectoria (hospital -> reconversion comercial).
    Separar los case_id no habria resuelto el problema real, solo lo habria
    desplazado a la etiqueta 'Nucleo Ochagavia'. La correccion real de
    nombre_proyecto pertenece a Fix 1C (clasificador aguas arriba), no a
    esta capa."""
    conn = _connect_or_skip()
    doc_role = conn.execute(
        "SELECT role, unidad_caso_tipo FROM document_conflict "
        "WHERE document_id = 'ad078a77f1ebd1d1938316d5103acadf10d9455f2799a414ba8af2d190df0342'"
    ).fetchone()
    conflict_row = conn.execute(
        "SELECT n_case_ids, label FROM conflict WHERE conflict_id = 'conflict:df81347c6c222b0f5a06c44c'"
    ).fetchone()
    conn.close()
    assert doc_role is not None, "el documento debe seguir presente en el warehouse"
    assert doc_role[0] == "mentioned_unreviewed", "ya no debe contar como evidencia focal/verificada"
    assert conflict_row is not None, "el conflicto Hospital Ochagavia debe seguir existiendo"
    assert conflict_row[0] == 2  # la union de case_id se mantiene intacta a proposito
    assert conflict_row[1] == "Hospital Ochagavía"


def test_fix_1c_audit_completo_documentos_ya_no_focal():
    """Fix 1C (2026-09-23): auditoria completa de los 128 candidatos de mayor
    riesgo (cero solapamiento de palabras clave entre nombre_proyecto y las
    citas de evidencia) que quedaron sin revisar tras el cierre inicial de
    Fix 1C. Se revisaron los 128 (antes solo ~30) via 3 subagentes en
    paralelo + verificacion manual propia de cada 'posible_error'. De los
    128, 123 resultaron bien fundados (el nombre si corresponde al objeto
    real, solo que la confirmacion vive en el titulo, en un documento
    hermano, o en una cita no capturada por el filtro automatico), 1 quedo
    no_concluyente (documento unico, ambiguo, no accionable), y 4 resultaron
    ser el mismo patron que Hospital Ochagavia: el nombre_proyecto viene de
    una case_mention EXCLUIDA o de una referencia retorica/periferica,
    mientras la case_mention realmente INCLUIDA describe un objeto distinto.
    Los 4 se corrigieron igual que Ochagavia: correccion_nombre_proyecto=''
    protegido con tiene_error=1."""
    conn = _connect_or_skip()
    docs = [
        "5d2f0680d21e1061790de468589132de52ff9cffd576ecee2fb4c0ad6b070f47",  # "Templo votivo"
        "2cb01a7a9e863f52c401b8f98df2af848a01c9b2d3354ee8dcc3a22554714db2",  # "Liceo Reino de Dinamarca"
        "b243ca1d3dd9948c4e15a7f8c41da3b3f10730236af8714d62cf942a16712523",  # "Hotel Sheraton San Cristóbal"
        "fb31947ee71b5386e1bcde4fa1b37570a867232120537d317dfdf5ad52249b76",  # "casona de calle Huérfanos"
    ]
    for doc_id in docs:
        row = conn.execute(
            "SELECT role FROM document_conflict WHERE document_id = ?", (doc_id,)
        ).fetchone()
        assert row is not None, f"el documento {doc_id} debe seguir presente en el warehouse"
        assert row[0] == "mentioned_unreviewed", f"{doc_id} ya no debe contar como evidencia focal/verificada"
    conn.close()


def test_fix_1c_project_case_mention_cross_check_documentos_ya_no_focal():
    """Fix 1C, cross-check con project_case_mention.py (2026-09-23): el metodo
    de solapamiento de palabras clave (patron 2 de Fix 1C) audito los 204
    candidatos completos (Tier A 128/128 + Tier B 76/76) sin encontrar casos
    nuevos en el Tier B. Un segundo metodo, complementario, usa el modulo
    experimental src/project_case_mention.py para vincular cada mencion de
    proyecto con la case_mention especifica (no solo el documento) que
    respalda su nombre. Aplicado a los 552 documentos focales, encontro 6
    casos reales mas donde el nombre_proyecto viene de una case_mention
    EXCLUIDA mientras la case_mention INCLUIDA describe un objeto distinto --
    exactamente el patron de Hospital Ochagavia, pero invisibles al metodo de
    solapamiento de palabras clave porque comparten alguna palabra con la
    evidencia real (ej. 'edificio', 'proyecto').

    Uno de estos 6 ('edificio de 17 pisos... Americo Vespucio 7550') habia
    sido marcado bien_fundado en una revision manual rapida previa -- este
    cross-check mas preciso revirtio ese veredicto. Corregidos igual que los
    casos previos: correccion_nombre_proyecto='' protegido con tiene_error=1."""
    conn = _connect_or_skip()
    docs = [
        "290718bbd0ad42bc30f57690d53d3672796ca4d9456143d72be6b1611db68dc2",  # "Solucion Sanitaria para un sector de Quilicura"
        "42c8b7e00822408d333117960962a4ac9a5fb982220ccba0e343973fbd499178",  # "proyecto Avda. Vespucio con Renato Sanchez Fontecilla y Asturias"
        "55dae700063cebc780630f0ed7e15fb33ee8a59bfb8c84c1577739c937265e6e",  # "edificio de la estrecha calle Santa Petronila"
        "644d3dd05d9fceb5383b9dfcd7da46e9849d586222b581702ab8518997d718f2",  # "Alameda 4499"
        "8f0dc37c09c989b600716d65dd413da217335b3c496c7eeec80f86b59cae2e1b",  # "edificio de 17 pisos... Americo Vespucio 7550"
        "f491365929e87b322139b7a7b75d8b6933ac1e18dc1a9a60db0205d4fa0b6ccd",  # "Portal Bicentenario"
    ]
    for doc_id in docs:
        row = conn.execute(
            "SELECT role FROM document_conflict WHERE document_id = ?", (doc_id,)
        ).fetchone()
        assert row is not None, f"el documento {doc_id} debe seguir presente en el warehouse"
        assert row[0] == "mentioned_unreviewed", f"{doc_id} ya no debe contar como evidencia focal/verificada"
    conn.close()


def test_fix_1c_ronda_4_ivo_gasic_vespucio_oriente_ya_no_focal():
    """Fix 1C, ronda 4 (2026-09-23): la revision AI-assisted del enriquecimiento
    N=150 (ejecutada por Luna/Codex, verificada por Claude Sonnet 5 contra el
    SQL real) marco como error_grave la entrevista a Ivo Gasic (Revista
    Planeo) por tener nombre_proyecto='Autopista Vespucio Oriente (AVO)'. La
    verificacion confirmo el mismo patron que Hospital Ochagavia: la cita
    literal 'Autopista Vespucio Oriente' solo existe en case_mention:4,
    EXCLUIDA; las case_mention incluidas (0,1,2) tratan de la lucha del MPL
    por vivienda social y contra el Plan Regulador Comunal de Penalolen (canal
    Las Perdices, Lo Hermida, conjunto habitacional de 120 familias) --
    Vespucio Oriente aparece solo de pasada en una entrevista panoramica.
    Corregido igual que los casos previos: correccion_nombre_proyecto=''
    protegido con tiene_error=1.

    De los otros 6 error_grave de la misma revision N=150, 2 coincidian
    exactamente con documentos ya corregidos en la ronda 3 (Portal
    Bicentenario, Americo Vespucio 7550) -- confirmacion cruzada
    independiente real, sin necesidad de correccion adicional. El desacuerdo
    de severidad sobre el caso Ex-Ante/FIMA se adjudico a error_menor (la
    case_mention focal SI tiene evidencia objeto real de 'Edificio
    Pajaritos'); los 3 restantes no estan en role focal/co_focal en ningun
    conflicto y quedan documentados como limitacion de calidad de
    enriquecimiento, no corregidos individualmente."""
    conn = _connect_or_skip()
    row = conn.execute(
        "SELECT role FROM document_conflict WHERE document_id = ?",
        ("9c71d8a489c1f04aae08dd95bf6044086528dd80e38a5621b979e12ee43140f7",),
    ).fetchone()
    conn.close()
    assert row is not None, "el documento debe seguir presente en el warehouse"
    assert row[0] == "mentioned_unreviewed", "ya no debe contar como evidencia focal/verificada"


def test_backing_rows_declare_document_level_scope_and_ambiguity_columns():
    """Fix 1D: ademas del scope documental original (exact_substring_v1),
    ahora tambien es valido el scope a nivel de mencion verificada por v3.3
    -- ambos son los UNICOS 2 valores esperados, nunca un typo nuevo."""
    conn = _connect_or_skip()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(conflict_evidence_backing)")}
    assert {
        "backing_scope",
        "document_case_mention_count",
        "document_object_case_mention_count",
        "ambiguous_multi_case_document",
        "detector_version",
    } <= columns
    valid_scopes = {"document_level_case_mention_without_project_link", "mention_level_verified_index"}
    bad_scope = conn.execute(
        "SELECT COUNT(*) FROM conflict_evidence_backing WHERE backing_scope NOT IN (%s)"
        % ",".join("?" * len(valid_scopes)),
        list(valid_scopes),
    ).fetchone()[0]
    v3_3_rows_have_correct_scope = conn.execute(
        "SELECT COUNT(*) FROM conflict_evidence_backing "
        "WHERE detector_version = 'v3_3_verified_index' AND backing_scope != 'mention_level_verified_index'"
    ).fetchone()[0]
    conn.close()
    assert bad_scope == 0
    assert v3_3_rows_have_correct_scope == 0


def _v3_3_sources_available() -> bool:
    """Auditoria/ es gitignorada (trabajo interno) -- un clon publico limpio
    (ej. CI) no tiene classifications.jsonl ni los enrichment.jsonl de v3.3.
    Mismo patron que _connect_or_skip() para warehouse.sqlite."""
    return reg.CLASSIFICATIONS_PATH.exists() and any(p.exists() for p in reg.V3_3_ENRICHMENT_FILES)


def test_load_v3_3_verified_links_excludes_out_of_universe_url_and_parses_real_data():
    if not _v3_3_sources_available():
        import pytest

        pytest.skip("Auditoria/clasificacion/classifications.jsonl o los enrichment.jsonl de v3.3 no existen en este entorno (gitignorados)")
    links = reg.load_v3_3_verified_links()
    assert len(links) > 0
    assert all(url != reg.V3_3_URL_FUERA_DE_UNIVERSO for (url, _name) in links)
    # al menos una entrada real con indice no nulo y una con null deben existir
    assert any(idx is not None for idx in links.values())
    assert any(idx is None for idx in links.values())


def test_load_v3_3_verified_links_aborts_on_classifications_sha256_mismatch(monkeypatch):
    import pytest

    if not reg.CLASSIFICATIONS_PATH.exists():
        pytest.skip("Auditoria/clasificacion/classifications.jsonl no existe en este entorno (gitignorado)")
    monkeypatch.setattr(reg, "CLASSIFICATIONS_SHA256_EXPECTED", "0" * 64)
    with pytest.raises(RuntimeError, match="sha256"):
        reg.load_v3_3_verified_links()


def test_backing_report_count_matches_persisted_rows():
    import json
    from pathlib import Path

    conn = _connect_or_skip()
    persisted = conn.execute("SELECT COUNT(*) FROM conflict_evidence_backing").fetchone()[0]
    conn.close()
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "audit" / "conflict_evidence_backing_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["backing_rows_persisted"] == persisted
    assert report["backing_rows_deduplicated"] == (
        report["backing_rows_detected_raw"] - report["backing_rows_persisted"]
    )


def test_document_conflict_case_safe_view_only_includes_caso_unico():
    conn = _connect_or_skip()
    bad = conn.execute(
        "SELECT COUNT(*) FROM document_conflict_case_safe WHERE unidad_caso_tipo != 'caso_unico'"
    ).fetchone()[0]
    n_safe = conn.execute("SELECT COUNT(*) FROM document_conflict_case_safe").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM document_conflict").fetchone()[0]
    conn.close()
    assert bad == 0
    assert 0 < n_safe <= n_total
