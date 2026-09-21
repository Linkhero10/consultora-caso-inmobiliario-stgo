"""Construye la capa CONFLICT: unidad sociologica de disputa, separada de
PROJECT/PROJECT_PHASE/CASE (identidad fisica/historica de proyecto, ya
cerrada). Motivacion y diseno acordados con la revisión (2026-09-18), tras la
auditoria de los 63 documentos 'caso_unico' con >1 case_id:

    project.case_id resuelve identidad de PROYECTO, no la unidad
    narrativa de CONFLICTO de un documento. Un solo conflicto puede
    involucrar legitimamente 2+ case_id (ej. cementerio Parque Santiago
    de Huechuraba vs. trazado del Teleferico Bicentenario: 2 proyectos
    reales y distintos, 1 solo conflicto judicial). En el otro extremo,
    un mismo territorio/actor colectivo puede sostener VARIOS conflictos
    distintos a lo largo del tiempo sin que eso los convierta en el mismo
    caso (ej. Poblacion La Victoria: toma de terreno fundacional 1957 vs.
    protesta contemporanea contra Rancagua Express).

Objeto de prueba adversarial explicito (pedido por la revisión): el esquema debe
poder representar AMBOS extremos sin forzar una decision en el segundo
caso, que queda deliberadamente sin resolver como PENDIENTE humano.

## Esquema

- conflict: unidad de conflicto. conflict_id es un hash ESTABLE de los
  case_id agrupados (nunca un label de texto libre -- ese fue exactamente
  el problema que la revisión senalo con `conflict_id_sugerido` en el paquete de
  63: dos personas pueden escribir el mismo conflicto con 2 strings
  distintos). `label` es solo para lectura humana, no es identidad.
- conflict_case: que case_id componen un conflict_id (1 fila = trivial;
  2+ filas = conflicto multi-proyecto evidenciado).
- conflict_project: que project_id (via su case_id) componen el
  conflicto -- vista materializada de conflict_case + project, para no
  tener que hacer el join cada vez.
- document_conflict: que documentos discuten cada conflicto, con rol
  (focal / co_focal / contextual_mention / panoramic_mention /
  mentioned_unreviewed) y `source` que distingue evidencia revisada a
  mano (conflict_unit_63_sol) de derivacion mecanica del resto del
  corpus (trivial_from_project_mention).
- conflict_relation: relaciones ENTRE conflictos que NO implican fusion
  -- ej. 'same_territorial_actor_pending_review' para Poblacion La
  Victoria / Rancagua Express. Nunca se auto-resuelve a un merge.
- conflict_episode: tabla creada VACIA a proposito. Poblarla exige
  extraer fechas por episodio desde enrichment_evento_v3_2 con el mismo
  rigor de verificacion de citas que el resto del pipeline -- eso es
  trabajo separado, no inventado aqui solo para "llenar la tabla".

## Orden de pipeline

Este script debe correr SIEMPRE al final de la cadena, despues de
build_case_project_bridge.py y resolve_project_review_queue.py (lee la
tabla `project.case_id` ya fusionada). Si se vuelve a correr
build_case_project_bridge.py despues de este script, las tablas CONFLICT
se pierden (ese script copia el warehouse fuente completo) -- hay que
volver a correr resolve_project_review_queue.py y luego este script.

## Algoritmo de agrupacion

1. Union-find sobre TODOS los case_id del registro de proyectos.
2. Para cada uno de los 63 documentos clasificados por la revisión
   (conflict_unit_63), cada relacion `relaciones_case_groups_sol` con
   relacion=='mismo_conflicto' UNE sus case_id (con o sin
   project_relation especifico -- parent_subproject/phase/
   distinct_conflict_objects son todas variantes de "es el mismo
   conflicto"). relacion in ('focal','contextual','conflictos_distintos')
   NUNCA une -- esa es precisamente la distincion que motiva esta capa.
3. Cualquier case_id no tocado por una union 'mismo_conflicto' queda como
   conflicto trivial de 1 solo case_id (cobertura total del corpus,
   sin inventar estructura donde no hay evidencia de que haga falta).
4. document_conflict para los 63 documentos evidenciados usa las mismas
   relaciones_case_groups_sol (fuente humana verificada). Para el resto
   del corpus (project_mention_resolved), se deriva mecanicamente: el
   project_id cuyo raw_nombre_proyecto coincide exactamente con
   nombre_proyecto (el foco declarado del documento) se marca 'focal';
   cualquier otro project_id mencionado en el mismo documento se marca
   'mentioned_unreviewed' -- rotulado asi a proposito para no aparentar
   el mismo nivel de confianza que la revision humana de los 63.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2_bridge.sqlite"
CLASSIFIED_63 = PROJECT_ROOT / "Auditoria" / "validacion_humana_v3_2" / "paquete_revision_conflict_unit_63_clasificado_sol.json"

# Relaciones que SI unen case_id en un mismo conflicto -- cualquier
# project_relation bajo 'mismo_conflicto' (parent_subproject, phase,
# distinct_conflict_objects) sigue siendo, a nivel de CONFLICTO, "el
# mismo conflicto"; la distincion de project_relation ya vive en la capa
# de identidad de proyecto (project_review_queue/PROJECT_PHASE), no debe
# repetirse aqui como una segunda razon para no unir.
RELACIONES_QUE_UNEN = {"mismo_conflicto"}
# 'mismo_proyecto' (alias) no necesita union aqui -- ya se resolvio a
# nivel de project_review_queue antes de calcular case_id, asi que esos
# case_id ya llegan identicos. 'focal'/'contextual'/'conflictos_distintos'
# son precisamente los casos que la capa CONFLICT existe para NO unir.


def _stable_conflict_id(case_ids: list[str]) -> str:
    return "conflict:" + hashlib.sha256("|".join(sorted(case_ids)).encode("utf-8")).hexdigest()[:24]


class UnionFind:
    def __init__(self, items):
        self.parent = {x: x for x in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def load_classified_63() -> list[dict]:
    if not CLASSIFIED_63.exists():
        return []
    return json.loads(CLASSIFIED_63.read_text(encoding="utf-8"))["documentos"]


def build_case_groups(all_case_ids: list[str], documentos_63: list[dict]) -> dict[str, list[str]]:
    """case_id -> lista ordenada de case_id de su grupo (incluyendose a si
    mismo si es trivial)."""
    uf = UnionFind(all_case_ids)
    for doc in documentos_63:
        for rel in doc.get("relaciones_case_groups_sol", []):
            if rel.get("relacion") not in RELACIONES_QUE_UNEN:
                continue
            ids = [cid for cid in rel["case_ids"] if cid in uf.parent]
            for cid in ids[1:]:
                uf.union(ids[0], cid)

    groups: dict[str, list[str]] = defaultdict(list)
    for cid in all_case_ids:
        groups[uf.find(cid)].append(cid)
    return {root: sorted(members) for root, members in groups.items()}


def build_conflict_relations(
    documentos_63: list[dict], case_id_to_conflict: dict[str, str], gate_status_by_document: dict[str, str]
) -> list[dict]:
    """Relaciones entre conflictos que NO se fusionan -- 'conflictos_distintos'
    marcado explicitamente por la revisión como posible trayectoria longitudinal
    compartiendo territorio/actor.

    [CORREGIDO 2026-09-18, hallazgo real de la revisión] La v1 marcaba
    review_status='pending_human_decision' para LOS 3 documentos D por
    igual, aunque 2 de ellos (UPC, Recuperacion de barrios) YA fueron
    adjudicados explicitamente en apply_conflict_unit_gate_decisions.py
    (reclasificados de caso_unico a documento_comparativo_panoramico --
    la decision de "no son el mismo conflicto, son panoramicos" YA se
    tomo). Solo Poblacion La Victoria/Rancagua Express sigue
    genuinamente pendiente (esa reclasificacion se dejo explicitamente
    sin aplicar). Se lee gate_status_by_document (el unidad_caso_tipo
    ACTUAL en document_unidad_caso_sol, no un id hardcodeado) para
    derivar review_status: si el documento ya salio de 'caso_unico',
    la relacion queda 'resolved_keep_separate'; si sigue en 'caso_unico',
    sigue 'pending_human_decision'.

    [CORREGIDO 2026-09-18, hallazgo menor de la revisión] Antes, si 2+ documentos
    evidenciaban el mismo par de conflictos, solo se conservaba el primer
    'note' encontrado (provenance perdido). Ahora se acumulan todos los
    documentos de evidencia por par en 'documentos_evidencia'."""
    relations: dict[tuple, dict] = {}
    for doc in documentos_63:
        gate_status = gate_status_by_document.get(doc["document_id"], "caso_unico")
        review_status = "pending_human_decision" if gate_status == "caso_unico" else "resolved_keep_separate"
        for rel in doc.get("relaciones_case_groups_sol", []):
            if rel.get("relacion") != "conflictos_distintos":
                continue
            conflict_ids = sorted({case_id_to_conflict[cid] for cid in rel["case_ids"] if cid in case_id_to_conflict})
            if len(conflict_ids) < 2:
                continue
            for i in range(len(conflict_ids)):
                for j in range(i + 1, len(conflict_ids)):
                    key = (conflict_ids[i], conflict_ids[j])
                    entry = relations.setdefault(
                        key,
                        {
                            "conflict_id_a": conflict_ids[i],
                            "conflict_id_b": conflict_ids[j],
                            "relation_type": "same_document_distinct_conflicts",
                            "review_status": review_status,
                            "documentos_evidencia": [],
                        },
                    )
                    # si CUALQUIER documento que evidencia el par sigue
                    # pendiente, la relacion en su conjunto sigue pendiente
                    # (no basta con que UN documento ya se haya resuelto).
                    if review_status == "pending_human_decision":
                        entry["review_status"] = "pending_human_decision"
                    entry["documentos_evidencia"].append(
                        {
                            "document_id": doc["document_id"],
                            "title": doc["title"],
                            "justificacion_sol": doc["justificacion_sol"],
                            "gate_status_al_construir": gate_status,
                        }
                    )

    result = []
    for entry in relations.values():
        entry["note"] = json.dumps(entry.pop("documentos_evidencia"), ensure_ascii=False)
        result.append(entry)
    return result


def main():
    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")

    all_case_ids = sorted({r[0] for r in conn.execute("SELECT DISTINCT case_id FROM project WHERE case_id IS NOT NULL")})
    documentos_63 = load_classified_63()

    case_groups = build_case_groups(all_case_ids, documentos_63)
    case_id_to_conflict = {}
    conflict_rows = []
    conflict_case_rows = []
    for members in case_groups.values():
        conflict_id = _stable_conflict_id(members)
        label = None
        names = conn.execute(
            "SELECT canonical_name FROM project WHERE case_id IN (%s) ORDER BY canonical_name" % ",".join("?" * len(members)),
            members,
        ).fetchall()
        if names:
            label = names[0][0]
        conflict_rows.append(
            {
                "conflict_id": conflict_id,
                "label": label,
                "n_case_ids": len(members),
                "origen": "conflict_unit_63_evidence" if len(members) > 1 else "trivial_single_case",
                "confidence": "alta_revisado_por_sol" if len(members) > 1 else "baja_derivado_mecanicamente",
            }
        )
        for cid in members:
            case_id_to_conflict[cid] = conflict_id
            conflict_case_rows.append({"conflict_id": conflict_id, "case_id": cid})

    conflict_project_rows = []
    for row in conn.execute("SELECT project_id, case_id FROM project WHERE case_id IS NOT NULL"):
        pid, cid = row
        if cid in case_id_to_conflict:
            conflict_project_rows.append({"conflict_id": case_id_to_conflict[cid], "project_id": pid, "case_id": cid})

    # Estado ACTUAL del gate (no el snapshot congelado en el JSON de los
    # 63, que puede haber quedado desactualizado tras
    # apply_conflict_unit_gate_decisions.py -- exactamente el caso de UPC
    # y Recuperacion de barrios, ya reclasificados).
    gate_status_by_document = dict(conn.execute("SELECT document_id, unidad_caso_tipo FROM document_unidad_caso_sol"))

    conflict_relation_rows = build_conflict_relations(documentos_63, case_id_to_conflict, gate_status_by_document)

    # [CORREGIDO 2026-09-18, bug real de la revisión] role tenia 2 fallas: (1)
    # relaciones 'mismo_proyecto' (alias de identidad de proyecto, ya
    # resuelto en project_review_queue) caian en el default
    # 'mentioned_unreviewed' en vez de ignorarse -- no describen una
    # relacion documento->conflicto, describen identidad de proyecto, y
    # no deberian generar una fila de document_conflict; (2) el dedupe
    # cuando un documento aportaba 2+ roles distintos al MISMO conflicto
    # solo preferia 'focal' sobre cualquier otra cosa, asi que
    # 'mentioned_unreviewed' podia ganarle a 'co_focal'/'contextual_mention'/
    # 'panoramic_mention' por orden de aparicion -- exactamente lo que le
    # paso al conflicto de Quilicura (LA PLANTA DE CACA / Solucion
    # transitoria...): la relacion 'mismo_proyecto' se procesaba primero y
    # su 'mentioned_unreviewed' quedaba fijo antes de que la relacion real
    # 'mismo_conflicto' pudiera aportar 'co_focal'. Ahora hay una prioridad
    # explicita, y 'mismo_proyecto' se ignora aqui (no es evidencia sobre
    # el CONFLICTO, es evidencia sobre identidad de PROYECTO).
    ROLE_PRIORITY = {
        "focal": 5,
        "co_focal": 4,
        "contextual_mention": 3,
        "panoramic_mention": 2,
        "mentioned_unreviewed": 1,
    }
    ROLE_BY_RELACION = {
        "focal": "focal",
        "mismo_conflicto": "co_focal",
        "contextual": "contextual_mention",
        "conflictos_distintos": "panoramic_mention",
    }

    def _mejor_rol(actual: str, nuevo: str) -> str:
        return nuevo if ROLE_PRIORITY.get(nuevo, 0) > ROLE_PRIORITY.get(actual, 0) else actual

    document_conflict_rows = []
    documentos_63_ids = {doc["document_id"] for doc in documentos_63}
    for doc in documentos_63:
        por_conflicto: dict[str, dict] = {}
        for rel in doc.get("relaciones_case_groups_sol", []):
            relacion = rel.get("relacion")
            if relacion == "mismo_proyecto":
                continue  # identidad de proyecto (alias), no evidencia de conflicto
            role = ROLE_BY_RELACION.get(relacion, "mentioned_unreviewed")
            for cid in rel["case_ids"]:
                cflt = case_id_to_conflict.get(cid)
                if cflt is None:
                    continue
                entry = por_conflicto.setdefault(cflt, {"role": role, "evidence": []})
                entry["role"] = _mejor_rol(entry["role"], role)
                entry["evidence"].append(
                    {"relacion": relacion, "project_relation": rel.get("project_relation")}
                )
        for cflt, info in por_conflicto.items():
            document_conflict_rows.append(
                {
                    "document_id": doc["document_id"],
                    "conflict_id": cflt,
                    "role": info["role"],
                    "evidence_json": json.dumps(
                        {"relaciones": info["evidence"], "justificacion_sol": doc["justificacion_sol"]},
                        ensure_ascii=False,
                    ),
                    "source": "conflict_unit_63_sol",
                    "unidad_caso_tipo": gate_status_by_document.get(doc["document_id"], doc["unidad_caso_tipo"]),
                }
            )

    # [CORREGIDO 2026-09-18, hallazgo real de la revisión] usaba directamente
    # enrichment_document_v3_2.nombre_proyecto para decidir cual mencion es
    # 'focal', ignorando las 9 correcciones humanas de nombre_proyecto ya
    # guardadas en document_unidad_caso_sol.correccion_nombre_proyecto.
    # COALESCE respeta el caso especial de correccion a '' (la revisión dijo "este
    # documento no tiene foco valido"): COALESCE solo cae al valor original
    # si la correccion es NULL (columna nunca corregida), no si es '' (una
    # correccion explicita a "sin foco"), asi que '' se queda como '' y
    # ninguna mencion coincidira con ella -- correcto.
    rows = conn.execute(
        """
        SELECT pmr.document_id, pmr.raw_nombre_proyecto, pmr.project_id, p.case_id,
               COALESCE(g.correccion_nombre_proyecto, ed.nombre_proyecto) AS nombre_proyecto_focal,
               g.unidad_caso_tipo
        FROM project_mention_resolved pmr
        JOIN enrichment_document_v3_2 ed ON ed.document_id = pmr.document_id
        JOIN project p ON p.project_id = pmr.project_id
        LEFT JOIN document_unidad_caso_sol g ON g.document_id = pmr.document_id
        """
    ).fetchall()
    for document_id, raw_nombre, project_id, case_id, nombre_proyecto_focal, unidad_caso_tipo in rows:
        if document_id in documentos_63_ids:
            continue  # ya cubierto por evidencia humana, no duplicar con derivacion mecanica
        cflt = case_id_to_conflict.get(case_id)
        if cflt is None:
            continue
        role = "focal" if raw_nombre == nombre_proyecto_focal else "mentioned_unreviewed"
        document_conflict_rows.append(
            {
                "document_id": document_id,
                "conflict_id": cflt,
                "role": role,
                "evidence_json": None,
                "source": "trivial_from_project_mention",
                "unidad_caso_tipo": unidad_caso_tipo,
            }
        )
    # dedupe (un documento puede mencionar 2 project_id del MISMO
    # conflicto, o el mismo conflicto por 2 fuentes) -- se queda con el
    # rol de mayor prioridad, no simplemente "el primero que no sea focal".
    dedup: dict[tuple, dict] = {}
    for r in document_conflict_rows:
        key = (r["document_id"], r["conflict_id"])
        if key not in dedup or ROLE_PRIORITY.get(r["role"], 0) > ROLE_PRIORITY.get(dedup[key]["role"], 0):
            dedup[key] = r
    document_conflict_rows = list(dedup.values())

    conn.executescript(
        """
        DROP VIEW IF EXISTS actor_event_project_link_conflict_safe;
        DROP VIEW IF EXISTS actor_event_project_link_conflict_extended;
        DROP VIEW IF EXISTS document_conflict_case_safe;
        DROP VIEW IF EXISTS document_conflict_case_extended;
        DROP TABLE IF EXISTS conflict_relation;
        DROP TABLE IF EXISTS document_conflict;
        DROP TABLE IF EXISTS conflict_project;
        DROP TABLE IF EXISTS conflict_case;
        DROP TABLE IF EXISTS conflict_episode;
        DROP TABLE IF EXISTS conflict;

        CREATE TABLE conflict (
            conflict_id TEXT PRIMARY KEY,
            label TEXT,
            n_case_ids INTEGER NOT NULL,
            origen TEXT NOT NULL,
            confidence TEXT NOT NULL
        );
        CREATE TABLE conflict_case (
            conflict_id TEXT NOT NULL REFERENCES conflict(conflict_id),
            case_id TEXT NOT NULL,
            PRIMARY KEY (conflict_id, case_id)
        );
        CREATE TABLE conflict_project (
            conflict_id TEXT NOT NULL REFERENCES conflict(conflict_id),
            project_id TEXT NOT NULL REFERENCES project(project_id),
            case_id TEXT NOT NULL,
            PRIMARY KEY (conflict_id, project_id)
        );
        CREATE TABLE document_conflict (
            document_id TEXT NOT NULL REFERENCES document(document_id),
            conflict_id TEXT NOT NULL REFERENCES conflict(conflict_id),
            role TEXT NOT NULL,
            evidence_json TEXT,
            source TEXT NOT NULL,
            unidad_caso_tipo TEXT,
            PRIMARY KEY (document_id, conflict_id)
        );
        CREATE TABLE conflict_relation (
            conflict_id_a TEXT NOT NULL REFERENCES conflict(conflict_id),
            conflict_id_b TEXT NOT NULL REFERENCES conflict(conflict_id),
            relation_type TEXT NOT NULL,
            review_status TEXT NOT NULL,
            note TEXT,
            PRIMARY KEY (conflict_id_a, conflict_id_b, relation_type)
        );
        CREATE TABLE conflict_episode (
            episode_id TEXT PRIMARY KEY,
            conflict_id TEXT NOT NULL REFERENCES conflict(conflict_id),
            fecha_aprox TEXT,
            descripcion TEXT,
            orden INTEGER
        );

        -- [CORREGIDO 2026-09-18, hallazgo real de revisión] la primera version
        -- solo filtraba unidad_caso_tipo='caso_unico', pero dentro de un
        -- documento caso_unico siguen existiendo document_conflict con
        -- role='mentioned_unreviewed' (mencion mecanica sin revisar) o
        -- 'panoramic_mention' (el propio caso adversarial de Poblacion La
        -- Victoria/Rancagua Express: unidad_caso_tipo sigue en caso_unico
        -- porque el gate esta pendiente, pero sus 2 conflictos son
        -- 'conflictos_distintos' -> role='panoramic_mention'). Sin filtrar
        -- tambien por role, la vista "safe" conectaria erroneamente
        -- actores del conflicto focal con conflictos meramente contextuales
        -- o con el propio caso pendiente de decision -- exactamente el
        -- problema que actor_event_project_link_case_safe ya resolvio a
        -- nivel proyecto (exigir resolution_status='resolved_explicit', no
        -- solo unidad_caso_tipo='caso_unico'). Ahora exige ademas
        -- role IN ('focal','co_focal') -- solo relaciones documento-conflicto
        -- humanamente evidenciadas como protagonicas.
        CREATE VIEW document_conflict_case_safe AS
            SELECT * FROM document_conflict
            WHERE unidad_caso_tipo = 'caso_unico' AND role IN ('focal', 'co_focal');

        -- Version mas inclusiva para analisis de sensibilidad (agrega
        -- contextual_mention, revisado a mano pero no protagonico) --
        -- nunca incluye mentioned_unreviewed ni panoramic_mention.
        CREATE VIEW document_conflict_case_extended AS
            SELECT * FROM document_conflict
            WHERE unidad_caso_tipo = 'caso_unico' AND role IN ('focal', 'co_focal', 'contextual_mention');

        -- [AGREGADO 2026-09-18] Base para la red ACTOR<->CONFLICT (siguiente
        -- paso pedido en revisión tras cerrar CONFLICT v1): mismo estandar de
        -- evidencia a nivel de mencion de actor que actor_event_project_link_case_safe
        -- (resolution_status='resolved_explicit'), pero agrupando por
        -- conflict_id via conflict_project en vez de por project.case_id, y
        -- exigiendo ademas que el DOCUMENTO de esa mencion tenga ese
        -- conflicto como protagonico (document_conflict_case_safe/extended)
        -- -- no basta con que el actor este resuelto a un proyecto, ese
        -- proyecto tiene que pertenecer a un conflicto que el documento
        -- trata como focal/co_focal (o +contextual en la version extendida).
        CREATE VIEW actor_event_project_link_conflict_safe AS
            SELECT l.*, cp.conflict_id AS conflict_id
            FROM actor_event_project_link l
            JOIN conflict_project cp ON cp.project_id = l.project_id
            JOIN document_conflict_case_safe dcs ON dcs.document_id = l.document_id AND dcs.conflict_id = cp.conflict_id
            WHERE l.resolution_status = 'resolved_explicit';

        CREATE VIEW actor_event_project_link_conflict_extended AS
            SELECT l.*, cp.conflict_id AS conflict_id
            FROM actor_event_project_link l
            JOIN conflict_project cp ON cp.project_id = l.project_id
            JOIN document_conflict_case_extended dce ON dce.document_id = l.document_id AND dce.conflict_id = cp.conflict_id
            WHERE l.resolution_status = 'resolved_explicit';
        """
    )

    conn.executemany(
        "INSERT INTO conflict (conflict_id, label, n_case_ids, origen, confidence) VALUES (:conflict_id, :label, :n_case_ids, :origen, :confidence)",
        conflict_rows,
    )
    conn.executemany(
        "INSERT INTO conflict_case (conflict_id, case_id) VALUES (:conflict_id, :case_id)", conflict_case_rows
    )
    conn.executemany(
        "INSERT INTO conflict_project (conflict_id, project_id, case_id) VALUES (:conflict_id, :project_id, :case_id)",
        conflict_project_rows,
    )
    conn.executemany(
        "INSERT INTO document_conflict (document_id, conflict_id, role, evidence_json, source, unidad_caso_tipo) "
        "VALUES (:document_id, :conflict_id, :role, :evidence_json, :source, :unidad_caso_tipo)",
        document_conflict_rows,
    )
    conn.executemany(
        "INSERT INTO conflict_relation (conflict_id_a, conflict_id_b, relation_type, review_status, note) "
        "VALUES (:conflict_id_a, :conflict_id_b, :relation_type, :review_status, :note)",
        conflict_relation_rows,
    )
    conn.commit()

    n_multi = sum(1 for c in conflict_rows if c["n_case_ids"] > 1)
    role_counts: dict[str, int] = defaultdict(int)
    for r in document_conflict_rows:
        role_counts[r["role"]] += 1
    summary = {
        "n_conflicts_total": len(conflict_rows),
        "n_conflicts_multi_case": n_multi,
        "n_conflicts_trivial": len(conflict_rows) - n_multi,
        "n_conflict_project_links": len(conflict_project_rows),
        "n_document_conflict_links": len(document_conflict_rows),
        "n_document_conflict_from_sol_evidence": sum(1 for r in document_conflict_rows if r["source"] == "conflict_unit_63_sol"),
        "n_document_conflict_trivial": sum(1 for r in document_conflict_rows if r["source"] == "trivial_from_project_mention"),
        "document_conflict_role_counts": dict(role_counts),
        "n_conflict_relations_total": len(conflict_relation_rows),
        "n_conflict_relations_pending_human_decision": sum(1 for r in conflict_relation_rows if r["review_status"] == "pending_human_decision"),
        "n_conflict_relations_resolved_keep_separate": sum(1 for r in conflict_relation_rows if r["review_status"] == "resolved_keep_separate"),
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_check_issues": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    conn.close()
    return summary


if __name__ == "__main__":
    main()
