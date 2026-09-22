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
  extraer fechas por episodio desde enrichment_event con el mismo
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

## Respaldo de evidencia (Fix 1A, 2026-09-22)

Validacion externa ampliada (N=150, Sol) midio 42.0% de error grave sobre el
universo real de conflictos -- mucho mas alto que el 24% de la auditoria
original de 50/63, porque esa muestra anterior solo cubria documentos ya
senalados para revision, no una muestra aleatoria del universo completo.
Causa raiz rastreada y verificada a mano contra 2 casos reales ("Museo de
la Memoria y Derechos Humanos en Punta Arenas", "Proyecto Tunel
Internacional Paso Las Lenas"): el bloque de arriba (linea ~217, antes de
este fix) tomaba TODO case_id de `project` sin excepcion y lo promovia a
conflicto trivial -- sin comprobar nunca que ese project_id correspondiera
a un case_mention real, incluido, con evidencia de "objeto" que lo
respalde. Un nombre de proyecto mencionado solo de pasada (biografia de un
arquitecto, comparacion de otro articulo) se volvia un "conflicto" con la
misma jerarquia que uno real. La medición exploratoria inicial (595/990
proyectos y 573/819 conflictos triviales sin respaldo) quedó superada por
el reporte generado desde el warehouse vigente; nunca debe tratarse como
una cifra congelada.

Fuente autoritativa del respaldo documental: `evidence` (tiene
`case_mention_id` real) + `case_mention.decision_final_amplio='include'`
-- nunca `enrichment_evidence` (no conserva ese vinculo). Candidato a
respaldo solo si ademas `evidence.quote_role='objeto'` AND
`evidence.verified=1`. `project_mention_resolved`/`project`/`case_id`
siguen interviniendo para llegar hasta ahi (son la fuente autoritativa,
no la UNICA tabla tocada).

Matching: substring exacto normalizado en cualquier direccion
(`exact_substring_v1`), NUNCA fuzzy. Congelado a proposito durante Fix 1A
-- las matrices de calibracion de abajo describen exactamente esta regla;
agregar minimo de caracteres, limites de token, stopwords, embeddings o
excepciones manuales seria `exact_substring_v2` y exige re-medir las
matrices desde cero.

Metricas de calibracion (medidas sobre la misma N=150 que informo el
diseno del detector -- son CALIBRACION, no validacion externa; requieren
un holdout nuevo, independiente, antes de tratarlas como desempeno fuera
de muestra):
- Contra `error_grave`: TP=49, FP=27, FN=14, TN=60 -> precision 64.5%,
  recall 77.8%.
- Contra `falso_positivo_inclusion` UNION `etiqueta_no_coincide_con_evidencia`
  (las 2 categorias que este detector ataca): TP=44, FP=32, FN=4, TN=70 ->
  precision 57.9%, recall 91.7%.
Interpretacion: recall alto, precision moderada -- sirve para priorizar
revision y construir un universo analitico conservador, NUNCA para
declarar que un conflicto sin respaldo es falso. ~1 de cada 3 marcados
"sin respaldo" resulta legitimo en la calibracion.

[PREFLIGHT, 2026-09-22] Al implementar el detector real y cruzarlo contra
los 150 veredictos, aparecio una discrepancia de exactamente 1 caso
("calle Toro Mazotte") en ambas matrices frente a los numeros calculados
a mano durante el diseno (65.3%/58.7% de precision). Investigado antes de
aceptar cualquier numero: el script de calibracion original OLVIDABA el
filtro `evidence.verified=1` (una cita de ese conflicto, no verificada,
calzaba por substring y se conto como respaldo valido). La implementacion
real de este archivo SI exige verified=1, tal como exige el diseno
acordado -- es la implementacion la correcta, no el calculo de calibracion
original. Las cifras de arriba ya estan corregidas (64.5%/57.9%); nunca se
modifico el detector para ajustarse a un numero previo.

Aplicado UNIFORMEMENTE a conflictos triviales y multi-case, sin excepcion
para `n_case_ids > 1`: la validacion demostro que esa excepcion habria
sido incorrecta (Aeropuerto Los Cerrillos y Aldea del Encuentro, ambos
`n_case_ids=2` de la revision humana de los 63, resultaron `error_grave`
en la validacion N=150 -- que un grupo de case_id haya pasado por
revision humana confirma la UNION de casos, no garantiza que el conflicto
resultante este bien construido).

Provenance completo en `conflict_evidence_backing` (nunca solo una
bandera): cada fila que respalda un conflicto queda trazable hasta la
cita literal que lo justifica. `conflict.respaldo_evidencia` es el estado
derivado (con CHECK explicito, nunca un TEXT abierto sin control) --
'respaldo_exact_quote_detectado' si existe >=1 fila de respaldo,
'sin_respaldo_exact_quote_detectado' si no. Nada se borra: el universo
completo de `conflict` se preserva integro, la bandera solo decide que
cuenta en el universo analitico conservador del dashboard.
"""

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
CLASSIFIED_63 = PROJECT_ROOT / "Auditoria" / "validacion_humana_v3_2" / "paquete_revision_conflict_unit_63_clasificado_sol.json"
AUDIT_REPORT_PATH = PROJECT_ROOT / "audit" / "conflict_evidence_backing_report.json"

DETECTOR_VERSION = "exact_substring_v1"
MATCH_METHOD = "normalized_bidirectional_substring"
BACKING_SCOPE = "document_level_case_mention_without_project_link"

# El esquema actual no conserva un vinculo proyecto->case_mention. Por eso
# las coincidencias del detector son documentales, y cualquier documento con
# varias menciones incluidas y evidencia de objeto se marca como ambiguo.

# Metricas de calibracion (N=150, Sol) -- ver docstring del modulo. Fijas
# porque dependen de veredictos humanos externos, no se recalculan corriendo
# este script; se citan tal cual en el reporte de auditoria.
CALIBRATION_ERROR_GRAVE = {"tp": 49, "fp": 27, "fn": 14, "tn": 60, "precision": 0.645, "recall": 0.778}
CALIBRATION_TARGET_CATEGORIES = {
    "target": ["falso_positivo_inclusion", "etiqueta_no_coincide_con_evidencia"],
    "tp": 44, "fp": 32, "fn": 4, "tn": 70, "precision": 0.579, "recall": 0.917,
}


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _mention_has_case_backing(raw_nombre_proyecto: str, objeto_quotes: list[str]) -> bool:
    """Substring exacto normalizado en cualquier direccion. Nunca fuzzy --
    ver 'Congelado explicito de la heuristica' en el docstring del modulo."""
    pn = _norm(raw_nombre_proyecto)
    if not pn:
        return False
    return any(pn in q or q in pn for q in objeto_quotes if q)


def _project_backing_evidence(
    project_id: str,
    mentions_by_project: dict[str, list[dict]],
    included_by_doc: dict[str, list[str]],
    objeto_by_cm: dict[str, list[dict]],
) -> list[dict]:
    """Todas las filas de respaldo encontradas para este proyecto -- nunca
    solo un booleano. Cada fila es provenance completo: exactamente que
    cita, de que case_mention, de que documento, justifica el vinculo."""
    rows = []
    for mention in mentions_by_project.get(project_id, []):
        document_id = mention["document_id"]
        raw_nombre_proyecto = mention["raw_nombre_proyecto"]
        pn = _norm(raw_nombre_proyecto)
        if not pn:
            continue
        included_case_mentions = included_by_doc.get(document_id, [])
        object_case_mentions = [cm_id for cm_id in included_case_mentions if objeto_by_cm.get(cm_id)]
        ambiguous_multi_case_document = int(len(set(object_case_mentions)) > 1)
        for case_mention_id in included_case_mentions:
            for ev in objeto_by_cm.get(case_mention_id, []):
                q = ev["quote_norm"]
                if q and (pn in q or q in pn):
                    rows.append(
                        {
                            "project_id": project_id,
                            "document_id": document_id,
                            "case_mention_id": case_mention_id,
                            "evidence_id": ev["evidence_id"],
                            "raw_nombre_proyecto": raw_nombre_proyecto,
                            "quote_text": ev["quote_text"],
                            # El warehouse actual conserva el proyecto a
                            # nivel de documento, no de case_mention. No se
                            # presenta como un vinculo directo inexistente.
                            "backing_scope": BACKING_SCOPE,
                            "document_case_mention_count": len(included_case_mentions),
                            "document_object_case_mention_count": len(set(object_case_mentions)),
                            "ambiguous_multi_case_document": ambiguous_multi_case_document,
                        }
                    )
    return rows

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
    ACTUAL en document_case_unit, no un id hardcodeado) para
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


def _build_conflict_backing(
    conflict_id: str,
    projects: list[tuple[str, str]],
    case_id_by_project: dict[str, str],
    mentions_by_project: dict[str, list[dict]],
    included_by_doc: dict[str, list[str]],
    objeto_by_cm: dict[str, list[dict]],
) -> tuple[str | None, str, list[dict]]:
    """Aplica el detector de respaldo a TODOS los proyectos de un conflicto
    (sin excepcion por n_case_ids) y decide label + respaldo_evidencia.
    `projects` es la lista (project_id, canonical_name) de todos los
    project_id que componen el conflicto. Devuelve (label,
    respaldo_evidencia, filas de conflict_evidence_backing)."""
    backed_projects: list[tuple[str, str]] = []
    backing_rows: list[dict] = []
    for pid, canonical_name in projects:
        rows = _project_backing_evidence(pid, mentions_by_project, included_by_doc, objeto_by_cm)
        if rows:
            backed_projects.append((pid, canonical_name))
            case_id_of_pid = case_id_by_project[pid]
            for r in rows:
                backing_rows.append(
                    {
                        "conflict_id": conflict_id,
                        "case_id": case_id_of_pid,
                        "project_id": r["project_id"],
                        "document_id": r["document_id"],
                        "case_mention_id": r["case_mention_id"],
                        "evidence_id": r["evidence_id"],
                        "raw_nombre_proyecto": r["raw_nombre_proyecto"],
                        "quote_text": r["quote_text"],
                        "quote_role": "objeto",
                        "detector_version": DETECTOR_VERSION,
                        "match_method": MATCH_METHOD,
                        "backing_scope": r["backing_scope"],
                        "document_case_mention_count": r["document_case_mention_count"],
                        "document_object_case_mention_count": r["document_object_case_mention_count"],
                        "ambiguous_multi_case_document": r["ambiguous_multi_case_document"],
                    }
                )

    # Label: preferir canonical_name entre proyectos RESPALDADOS (Fix 1A,
    # corrige etiqueta_no_coincide_con_evidencia -- 27/63 error_grave en la
    # validacion N=150). Fallback explicito al mecanismo anterior (primero
    # alfabetico entre TODOS) solo si ningun proyecto tiene respaldo.
    if backed_projects:
        label = sorted(backed_projects, key=lambda x: x[1])[0][1]
    elif projects:
        label = sorted(projects, key=lambda x: x[1])[0][1]
    else:
        label = None

    respaldo_evidencia = "respaldo_exact_quote_detectado" if backed_projects else "sin_respaldo_exact_quote_detectado"
    return label, respaldo_evidencia, backing_rows


def _backing_summary(projects: list[tuple[str, str]], backing_rows: list[dict]) -> dict:
    """Resume cobertura y ambigüedad sin convertir ausencia en falsedad.

    El detector solo observa respaldo documental a nivel de documento/case
    mention. Por eso la cobertura de un conflicto con varios proyectos debe
    distinguirse de una bandera binaria: un proyecto respaldado no respalda
    automáticamente a sus hermanos.
    """
    project_ids = {pid for pid, _ in projects}
    backed_ids = {row["project_id"] for row in backing_rows if row.get("project_id") in project_ids}
    n_backed = len(backed_ids)
    n_unbacked = len(project_ids) - n_backed
    if not project_ids or n_backed == 0:
        coverage = "ninguna"
    elif n_unbacked == 0:
        coverage = "total"
    else:
        coverage = "parcial"
    if backed_ids:
        label_candidates = sorted((name, pid) for pid, name in projects if pid in backed_ids)
    else:
        label_candidates = sorted((name, pid) for pid, name in projects)
    return {
        "n_projects_backed": n_backed,
        "n_projects_unbacked": n_unbacked,
        "coverage_backing": coverage,
        "label_source_project_id": label_candidates[0][1] if label_candidates else None,
        "n_documents_ambiguous_backing": len({
            row["document_id"] for row in backing_rows if row.get("ambiguous_multi_case_document")
        }),
    }


def main():
    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")

    all_case_ids = sorted({r[0] for r in conn.execute("SELECT DISTINCT case_id FROM project WHERE case_id IS NOT NULL")})
    documentos_63 = load_classified_63()

    # Precomputo unico para el detector de respaldo (Fix 1A) -- sin cascada
    # de queries por conflicto. Fuente autoritativa: evidence + case_mention
    # (nunca enrichment_evidence, que no conserva case_mention_id).
    included_by_doc: dict[str, list[str]] = defaultdict(list)
    for doc_id, cm_id in conn.execute("SELECT document_id, case_mention_id FROM case_mention WHERE decision_final_amplio = 'include'"):
        included_by_doc[doc_id].append(cm_id)
    objeto_by_cm: dict[str, list[dict]] = defaultdict(list)
    for cm_id, ev_id, quote_text in conn.execute(
        "SELECT case_mention_id, evidence_id, quote_text FROM evidence WHERE quote_role = 'objeto' AND verified = 1"
    ):
        objeto_by_cm[cm_id].append({"evidence_id": ev_id, "quote_text": quote_text, "quote_norm": _norm(quote_text)})
    mentions_by_project: dict[str, list[dict]] = defaultdict(list)
    for pid, doc_id, raw_name in conn.execute("SELECT project_id, document_id, raw_nombre_proyecto FROM project_mention_resolved"):
        mentions_by_project[pid].append({"document_id": doc_id, "raw_nombre_proyecto": raw_name})
    case_id_by_project: dict[str, str] = dict(conn.execute("SELECT project_id, case_id FROM project WHERE case_id IS NOT NULL"))

    case_groups = build_case_groups(all_case_ids, documentos_63)
    case_id_to_conflict = {}
    conflict_rows = []
    conflict_case_rows = []
    conflict_evidence_backing_rows = []
    for members in case_groups.values():
        conflict_id = _stable_conflict_id(members)
        projects = conn.execute(
            "SELECT project_id, canonical_name FROM project WHERE case_id IN (%s) ORDER BY canonical_name" % ",".join("?" * len(members)),
            members,
        ).fetchall()

        # Detector de respaldo (Fix 1A): aplicado UNIFORMEMENTE, sin
        # excepcion para n_case_ids>1 -- ver docstring del modulo (Aeropuerto
        # Los Cerrillos y Aldea del Encuentro, ambos multi-case revisados,
        # resultaron error_grave en la validacion N=150).
        label, respaldo_evidencia, backing_rows = _build_conflict_backing(
            conflict_id, projects, case_id_by_project, mentions_by_project, included_by_doc, objeto_by_cm
        )
        conflict_evidence_backing_rows.extend(backing_rows)
        backing_summary = _backing_summary(projects, backing_rows)

        conflict_rows.append(
            {
                "conflict_id": conflict_id,
                "label": label,
                "n_case_ids": len(members),
                "origen": "conflict_unit_63_evidence" if len(members) > 1 else "trivial_single_case",
                "confidence": "alta_revisado_por_sol" if len(members) > 1 else "baja_derivado_mecanicamente",
                "respaldo_evidencia": respaldo_evidencia,
                **backing_summary,
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
    gate_status_by_document = dict(conn.execute("SELECT document_id, unidad_caso_tipo FROM document_case_unit"))

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
    # enrichment_document.nombre_proyecto para decidir cual mencion es
    # 'focal', ignorando las 9 correcciones humanas de nombre_proyecto ya
    # guardadas en document_case_unit.correccion_nombre_proyecto.
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
        JOIN enrichment_document ed ON ed.document_id = pmr.document_id
        JOIN project p ON p.project_id = pmr.project_id
        LEFT JOIN document_case_unit g ON g.document_id = pmr.document_id
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
        DROP TABLE IF EXISTS conflict_evidence_backing;
        DROP TABLE IF EXISTS conflict_project;
        DROP TABLE IF EXISTS conflict_case;
        DROP TABLE IF EXISTS conflict_episode;
        DROP TABLE IF EXISTS conflict;

        CREATE TABLE conflict (
            conflict_id TEXT PRIMARY KEY,
            label TEXT,
            n_case_ids INTEGER NOT NULL,
            origen TEXT NOT NULL,
            confidence TEXT NOT NULL,
            respaldo_evidencia TEXT NOT NULL CHECK (
                respaldo_evidencia IN ('respaldo_exact_quote_detectado', 'sin_respaldo_exact_quote_detectado')
            ),
            n_projects_backed INTEGER NOT NULL CHECK (n_projects_backed >= 0),
            n_projects_unbacked INTEGER NOT NULL CHECK (n_projects_unbacked >= 0),
            coverage_backing TEXT NOT NULL CHECK (coverage_backing IN ('total', 'parcial', 'ninguna')),
            label_source_project_id TEXT,
            n_documents_ambiguous_backing INTEGER NOT NULL CHECK (n_documents_ambiguous_backing >= 0)
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

        -- [AGREGADO Fix 1A, 2026-09-22] Provenance completo del respaldo de
        -- evidencia -- nunca solo una bandera. Cada fila es una cita literal
        -- que justifica que un project_id (y por lo tanto el conflict_id que
        -- lo contiene) tiene un case_mention incluido y verificado detras.
        -- Ausencia de filas para un conflict_id = sin_respaldo_exact_quote_detectado.
        -- detector_version separado de match_method a proposito: manana puede
        -- existir exact_substring_v2 con varios tipos de match, y la fila debe
        -- ser autosuficiente sin volver a consultar evidence.
        CREATE TABLE conflict_evidence_backing (
            conflict_id TEXT NOT NULL REFERENCES conflict(conflict_id),
            case_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES project(project_id),
            document_id TEXT NOT NULL REFERENCES document(document_id),
            case_mention_id TEXT NOT NULL,
            evidence_id TEXT NOT NULL,
            raw_nombre_proyecto TEXT NOT NULL,
            quote_text TEXT NOT NULL,
            quote_role TEXT NOT NULL,
            detector_version TEXT NOT NULL,
            match_method TEXT NOT NULL,
            backing_scope TEXT NOT NULL CHECK (backing_scope = 'document_level_case_mention_without_project_link'),
            document_case_mention_count INTEGER NOT NULL CHECK (document_case_mention_count >= 0),
            document_object_case_mention_count INTEGER NOT NULL CHECK (document_object_case_mention_count >= 0),
            ambiguous_multi_case_document INTEGER NOT NULL CHECK (ambiguous_multi_case_document IN (0, 1)),
            PRIMARY KEY (conflict_id, project_id, document_id, case_mention_id, evidence_id)
        );
        CREATE INDEX idx_conflict_backing_conflict ON conflict_evidence_backing(conflict_id);
        CREATE INDEX idx_conflict_backing_project ON conflict_evidence_backing(project_id);
        CREATE INDEX idx_conflict_backing_case_mention ON conflict_evidence_backing(case_mention_id);
        CREATE INDEX idx_conflict_backing_document ON conflict_evidence_backing(document_id);

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
        "INSERT INTO conflict (conflict_id, label, n_case_ids, origen, confidence, respaldo_evidencia, "
        "n_projects_backed, n_projects_unbacked, coverage_backing, label_source_project_id, "
        "n_documents_ambiguous_backing) "
        "VALUES (:conflict_id, :label, :n_case_ids, :origen, :confidence, :respaldo_evidencia, "
        ":n_projects_backed, :n_projects_unbacked, :coverage_backing, :label_source_project_id, "
        ":n_documents_ambiguous_backing)",
        conflict_rows,
    )
    # INSERT OR IGNORE: un mismo project_id puede tener 2 raw_nombre_proyecto
    # distintos para el mismo documento (ej. "Lote 18" / "Lote 18-A", 2
    # menciones reales del mismo proyecto con redaccion distinta) que calzan
    # con la misma cita de evidencia -- la clave primaria no incluye
    # raw_nombre_proyecto a proposito (la pregunta que responde la fila es
    # "que evidencia respalda este project_id en este conflicto", no "cuantas
    # variantes de texto calzaron"), asi que el duplicado se ignora sin
    # perder la senal de respaldo.
    conn.executemany(
        "INSERT OR IGNORE INTO conflict_evidence_backing (conflict_id, case_id, project_id, document_id, case_mention_id, "
        "evidence_id, raw_nombre_proyecto, quote_text, quote_role, detector_version, match_method, "
        "backing_scope, document_case_mention_count, document_object_case_mention_count, "
        "ambiguous_multi_case_document) "
        "VALUES (:conflict_id, :case_id, :project_id, :document_id, :case_mention_id, :evidence_id, "
        ":raw_nombre_proyecto, :quote_text, :quote_role, :detector_version, :match_method, "
        ":backing_scope, :document_case_mention_count, :document_object_case_mention_count, "
        ":ambiguous_multi_case_document)",
        conflict_evidence_backing_rows,
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

    # `conflict_evidence_backing_rows` conserva todas las coincidencias
    # detectadas; la clave primaria de la tabla puede deduplicar variantes
    # que apuntan al mismo conflicto/proyecto/documento/case_mention/evidence.
    # Reportamos ambas magnitudes para que el audit no confunda detección con
    # filas efectivamente persistidas.
    n_backing_rows_persisted = conn.execute("SELECT COUNT(*) FROM conflict_evidence_backing").fetchone()[0]

    n_multi = sum(1 for c in conflict_rows if c["n_case_ids"] > 1)
    role_counts: dict[str, int] = defaultdict(int)
    for r in document_conflict_rows:
        role_counts[r["role"]] += 1
    n_conflicts_backed = sum(1 for c in conflict_rows if c["respaldo_evidencia"] == "respaldo_exact_quote_detectado")
    n_trivial = len(conflict_rows) - n_multi
    n_trivial_backed = sum(
        1 for c in conflict_rows if c["n_case_ids"] == 1 and c["respaldo_evidencia"] == "respaldo_exact_quote_detectado"
    )
    n_projects_total = len(case_id_by_project)
    n_projects_with_backing = sum(
        1 for pid in case_id_by_project if _project_backing_evidence(pid, mentions_by_project, included_by_doc, objeto_by_cm)
    )
    summary = {
        "n_conflicts_total": len(conflict_rows),
        "n_conflicts_multi_case": n_multi,
        "n_conflicts_trivial": n_trivial,
        "n_conflicts_evidence_backed": n_conflicts_backed,
        "n_conflicts_without_exact_backing": len(conflict_rows) - n_conflicts_backed,
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
        "n_conflict_evidence_backing_rows_detected_raw": len(conflict_evidence_backing_rows),
        "n_conflict_evidence_backing_rows_persisted": n_backing_rows_persisted,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    audit_report = {
        "detector_version": DETECTOR_VERSION,
        "backing_scope": BACKING_SCOPE,
        "backing_scope_note": "El warehouse no conserva vinculo proyecto-case_mention; las coincidencias son documentales y los documentos multi-caso quedan senalados como ambiguos.",
        "projects_total": n_projects_total,
        "projects_with_backing": n_projects_with_backing,
        "projects_without_backing": n_projects_total - n_projects_with_backing,
        "conflicts_total": len(conflict_rows),
        "trivial_conflicts_total": n_trivial,
        "trivial_conflicts_without_backing": n_trivial - n_trivial_backed,
        "conflicts_with_backing": n_conflicts_backed,
        "conflicts_without_backing": len(conflict_rows) - n_conflicts_backed,
        "backing_rows": n_backing_rows_persisted,
        "backing_rows_detected_raw": len(conflict_evidence_backing_rows),
        "backing_rows_persisted": n_backing_rows_persisted,
        "coverage_backing": {
            "total": sum(1 for c in conflict_rows if c["coverage_backing"] == "total"),
            "parcial": sum(1 for c in conflict_rows if c["coverage_backing"] == "parcial"),
            "ninguna": sum(1 for c in conflict_rows if c["coverage_backing"] == "ninguna"),
        },
        "conflicts_with_ambiguous_multi_case_backing": sum(
            1 for c in conflict_rows if c["n_documents_ambiguous_backing"] > 0
        ),
        "calibration_n": 150,
        "calibration_error_grave": CALIBRATION_ERROR_GRAVE,
        "calibration_target_categories": CALIBRATION_TARGET_CATEGORIES,
    }
    conn.close()
    audit_report["warehouse_sha256"] = hashlib.sha256(WAREHOUSE.read_bytes()).hexdigest()
    AUDIT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_REPORT_PATH.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["audit_report_path"] = str(AUDIT_REPORT_PATH.relative_to(PROJECT_ROOT))
    return summary


if __name__ == "__main__":
    main()
