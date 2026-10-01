"""Construye la capa CONFLICT: la unidad sociologica de disputa, separada de la identidad fisica de
proyecto (PROJECT / PROJECT_PHASE / CASE).

`project.case_id` resuelve la identidad de un PROYECTO, no la unidad narrativa de CONFLICTO de un
documento. Un solo conflicto puede involucrar legitimamente 2+ `case_id` (el cementerio Parque
Santiago de Huechuraba y el trazado del Teleferico Bicentenario son dos proyectos y un solo litigio).
En el otro extremo, un mismo territorio o actor colectivo puede sostener VARIOS conflictos distintos a
lo largo del tiempo sin que eso los vuelva el mismo (Poblacion La Victoria: la toma de terreno
fundacional de 1957 y la protesta contemporanea contra Rancagua Express). El esquema debe poder
representar ambos extremos; el segundo queda como pendiente humano, nunca se resuelve por inercia.

## Esquema

- conflict: unidad de conflicto. `conflict_id` es un hash ESTABLE de los case_id agrupados, nunca un
  label de texto libre (dos personas pueden escribir el mismo conflicto con dos strings distintos).
  `label` es solo para lectura humana, no es identidad.
- conflict_case: que case_id componen un conflict_id (1 fila = trivial; 2+ = multi-proyecto evidenciado).
- conflict_project: que project_id (via su case_id) componen el conflicto.
- document_conflict: que documentos discuten cada conflicto, con rol (focal / co_focal /
  contextual_mention / panoramic_mention / mentioned_unreviewed) y `source`, que distingue evidencia
  revisada a mano (`conflict_unit_review`) de derivacion mecanica (`trivial_from_project_mention`).
- conflict_relation: relaciones ENTRE conflictos que NO implican fusion. Nunca se auto-resuelve a un merge.
- conflict_episode: tabla creada VACIA a proposito. Poblarla exige extraer fechas por episodio con el
  mismo rigor de verificacion de citas que el resto del pipeline; es trabajo separado.

## Orden de pipeline

Este script corre siempre despues de `resolve_project_review.py` (lee `project.case_id` ya fusionado) y
reescribe solo las tablas CONFLICT dentro de `data/warehouse.sqlite`. `src/rebuild.py` fija el orden.

## Algoritmo de agrupacion

1. Union-find sobre TODOS los case_id del registro de proyectos.
2. Para cada documento de la revision manual de unidades (`config/conflict_unit_review.json`), cada
   relacion `mismo_conflicto` UNE sus case_id. Las relaciones focal / contextual / conflictos_distintos
   NUNCA unen: esa es precisamente la distincion que motiva esta capa.
3. Todo case_id no tocado por una union queda como conflicto trivial de un solo case_id (cobertura total
   del corpus, sin inventar estructura donde no hay evidencia de que haga falta).
4. `document_conflict` para los documentos revisados usa esas mismas relaciones. Para el resto del
   corpus se deriva mecanicamente: el project_id cuyo nombre coincide exactamente con `nombre_proyecto`
   (el foco declarado del documento) se marca `focal`; cualquier otro proyecto mencionado se marca
   `mentioned_unreviewed`, rotulado asi a proposito para no aparentar la confianza de la revision humana.

## Respaldo de evidencia

Un conflicto trivial solo cuenta como respaldado si alguna mencion de sus proyectos apunta, por el
`case_mention_index` que el modelo eligio en la extraccion y que el pipeline verifico, a una
`case_mention` incluida con al menos una cita de `objeto` verificada (subcadena literal del texto).
Fuente autoritativa: `evidence` (tiene `case_mention_id` real) mas `case_mention.decision_final_amplio`.

`conflict_evidence_backing` conserva la cadena completa hasta la cita (nunca solo una bandera).
`conflict.respaldo_evidencia` es el estado derivado, con CHECK explicito: 'respaldo_exact_quote_detectado'
si existe al menos una fila de respaldo y 'sin_respaldo_exact_quote_detectado' si no. Nada se borra: el
universo completo de `conflict` se preserva y la bandera solo decide que cuenta en el universo analitico
conservador. La ausencia de respaldo NO demuestra que el conflicto sea falso.

Una `case_mention` que la clasificacion dejo `uncertain`/`exclude` pero que su documento trata como el
objeto de una disputa concreta puede respaldar el conflicto solo por adjudicacion manual explicita
(`config/case_mention_eligibility_adjudications.json`); queda visible en `match_method` y nunca modifica
`case_mention.decision_final_amplio`. Compartir un grupo de duplicados NO transfiere evidencia entre
menciones: el detector agrupa por texto y puede juntar proyectos distintos.

La asociacion proyecto -> mencion que produce el modelo se valido con dos rondas de revision ciega
independiente (0 fabricaciones en 809 evaluaciones); ver `audit/validation_summary.json`. Un respaldo
verificado prueba que la mencion existe y tiene cita literal, no que el conflicto este bien delimitado.
"""

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from historical_case_publication_gate import conflict_topology_fingerprint

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
CASE_BASELINE = PROJECT_ROOT / "config" / "project_case_baseline.json"
CONFLICT_UNIT_REVIEW = PROJECT_ROOT / "config" / "conflict_unit_review.json"
AUDIT_REPORT_PATH = PROJECT_ROOT / "audit" / "conflict_evidence_backing_report.json"
HISTORICAL_CASE_PREFLIGHT_REPORT_PATH = PROJECT_ROOT / "audit" / "historical_case_reference_preflight.json"
HISTORICAL_CASE_ID_RESOLUTIONS_PATH = PROJECT_ROOT / "config" / "historical_case_id_resolutions.json"

# Unico metodo de respaldo: el `case_mention_index` que el modelo eligio en la extraccion y el pipeline
# verifico. No hay heuristica de texto de respaldo; una mencion sin indice queda sin respaldo.
DETECTOR_VERSION = "verified_index"
MATCH_METHOD = "model_verified_case_mention_index"
BACKING_SCOPE = "mention_level_verified_index"
# Adjudicacion humana de elegibilidad: una case_mention que la clasificacion dejo uncertain/exclude pero cuyo
# documento la trata como el objeto de una disputa concreta puede respaldar el conflicto. Solo afecta este
# respaldo, nunca case_mention.decision_final_amplio, y queda visible en match_method.
CASE_MENTION_ELIGIBILITY_ADJUDICATIONS_PATH = PROJECT_ROOT / "config" / "case_mention_eligibility_adjudications.json"
MATCH_METHOD_ADJUDICATED_ELIGIBILITY = "adjudicated_eligibility"


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def load_verified_links(conn: sqlite3.Connection) -> dict[tuple[str, str], int | None]:
    """dict[(document_id, nombre_normalizado)] -> case_mention_index, o None si el modelo determino que ninguna
    case_mention es el objeto de esa mencion.

    El vinculo esta materializado en `enrichment_project_mention` (lo escribe `build_enrichment_tables.py` desde la
    extraccion) y `project_mention_resolved` sale de la MISMA fuente, asi que el nombre coincide por construccion.
    La clave se normaliza (`_norm`) solo como salvaguarda de espacios, mayusculas y acentos."""
    links: dict[tuple[str, str], int | None] = {}
    for document_id, nombre_proyecto, case_mention_index in conn.execute(
        "SELECT document_id, nombre_proyecto, case_mention_index FROM enrichment_project_mention"
    ):
        key = (document_id, _norm(nombre_proyecto))
        if key in links and links[key] != case_mention_index:
            raise ValueError(
                "enrichment_project_mention tiene colisión tras normalizar "
                f"(document_id, nombre_proyecto)={key!r}: {links[key]!r} vs {case_mention_index!r}"
            )
        links[key] = case_mention_index
    return links


def load_case_mention_eligibility_adjudications(conn: sqlite3.Connection, path: Path) -> dict[str, dict]:
    """Lee y valida las adjudicaciones de elegibilidad contra el warehouse; falla cerrado."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "case_mention_eligibility_adjudications":
        raise ValueError("schema_version de case_mention_eligibility_adjudications no reconocido")
    result: dict[str, dict] = {}
    for entry in payload.get("adjudications", []):
        cm_id = entry.get("case_mention_id")
        if not cm_id or cm_id in result:
            raise ValueError(f"adjudicacion de elegibilidad sin case_mention_id o duplicada: {cm_id!r}")
        if entry.get("adjudicated_decision") != "include" or not entry.get("rationale") or not entry.get("evidence"):
            raise ValueError(f"adjudicacion de elegibilidad incompleta: {cm_id!r}")
        row = conn.execute("SELECT decision_final_amplio FROM case_mention WHERE case_mention_id = ?", (cm_id,)).fetchone()
        if row is None:
            raise ValueError(f"adjudicacion de elegibilidad apunta a case_mention inexistente: {cm_id!r}")
        if row[0] != entry.get("original_decision_final_amplio"):
            raise ValueError(
                f"adjudicacion de elegibilidad de {cm_id!r} esperaba {entry.get('original_decision_final_amplio')!r} y el warehouse tiene {row[0]!r}"
            )
        for ev in entry["evidence"]:
            ev_row = conn.execute(
                "SELECT quote_text FROM evidence WHERE evidence_id = ? AND case_mention_id = ? AND quote_role = 'objeto' AND verified = 1",
                (ev["evidence_id"], cm_id),
            ).fetchone()
            if ev_row is None or ev_row[0] != ev["quote"]:
                raise ValueError(f"evidencia de la adjudicacion {cm_id!r} no coincide con el warehouse: {ev['evidence_id']!r}")
        result[cm_id] = entry
    return result


def _project_backing_evidence(
    project_id: str,
    mentions_by_project: dict[str, list[dict]],
    included_by_doc: dict[str, list[str]],
    objeto_by_cm: dict[str, list[dict]],
    verified_links_by_docid: dict[tuple[str, str], int | None],
    adjudicated_cms: frozenset[str] | None = None,
) -> list[dict]:
    """Todas las filas de respaldo de este proyecto -- nunca solo un booleano. Cada fila es provenance completo:
    exactamente que cita, de que case_mention y de que documento justifica el vinculo.

    Una mencion respalda solo por el `case_mention_index` verificado que el modelo le asigno, y solo si esa
    case_mention esta incluida y tiene al menos una cita de `objeto` verificada. Sin indice (None) no hay respaldo:
    el modelo decidio explicitamente que no hay vinculo claro, y adivinarlo por texto fue el problema original."""
    adjudicated_cms = adjudicated_cms or frozenset()
    rows = []
    for mention in mentions_by_project.get(project_id, []):
        document_id = mention["document_id"]
        raw_nombre_proyecto = mention["raw_nombre_proyecto"]
        pn = _norm(raw_nombre_proyecto)
        if not pn:
            continue

        idx = verified_links_by_docid.get((document_id, pn))
        if idx is None:
            continue

        case_mention_id = f"{document_id}:{idx}"
        doc_included = included_by_doc.get(document_id, [])
        if case_mention_id in doc_included and objeto_by_cm.get(case_mention_id):
            for ev in objeto_by_cm.get(case_mention_id, []):
                rows.append(
                    {
                        "project_id": project_id,
                        "document_id": document_id,
                        "case_mention_id": case_mention_id,
                        "evidence_id": ev["evidence_id"],
                        "raw_nombre_proyecto": raw_nombre_proyecto,
                        "quote_text": ev["quote_text"],
                        "backing_scope": BACKING_SCOPE,
                        "document_case_mention_count": len(doc_included),
                        "document_object_case_mention_count": 1,
                        "ambiguous_multi_case_document": 0,
                        "duplicate_group_mixed_decision": 0,
                        "detector_version": DETECTOR_VERSION,
                        "match_method": MATCH_METHOD_ADJUDICATED_ELIGIBILITY if case_mention_id in adjudicated_cms else MATCH_METHOD,
                    }
                )
        # No se hereda evidencia de otra case_mention por compartir grupo de
        # duplicados. El grupo es una señal para revision, no una relacion
        # project -> case_mention. Solo la asignacion la extraccion vigente exacta, junto con
        # su propia elegibilidad y evidencia de objeto verificada, respalda.
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
RELACIONES_QUE_CAMBIAN_TOPOLOGIA = {"mismo_conflicto", "conflictos_distintos"}
RELACIONES_DE_MEMBRESIA_DOCUMENTAL = {"focal", "contextual"}
RELACIONES_IDENTIDAD_PROYECTO = {"mismo_proyecto"}
RELACIONES_CASE_CONOCIDAS = (
    RELACIONES_QUE_CAMBIAN_TOPOLOGIA
    | RELACIONES_DE_MEMBRESIA_DOCUMENTAL
    | RELACIONES_IDENTIDAD_PROYECTO
)


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


def load_conflict_unit_review() -> list[dict]:
    if not CONFLICT_UNIT_REVIEW.exists():
        raise FileNotFoundError(f"CONFLICT_UNIT_REVIEW requerido para construir CONFLICT: {CONFLICT_UNIT_REVIEW}")
    payload = json.loads(CONFLICT_UNIT_REVIEW.read_text(encoding="utf-8"))
    documentos = payload.get("documentos") if isinstance(payload, dict) else None
    if not isinstance(documentos, list):
        raise ValueError(f"CONFLICT_UNIT_REVIEW debe contener una lista 'documentos': {CONFLICT_UNIT_REVIEW}")
    return documentos


def _validate_sha256_field(payload: dict, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} debe ser SHA-256 hexadecimal de 64 caracteres")
    return value


def validate_case_id_alias_rows(
    rows: list[tuple[str, str, str, str]],
    current_case_ids: set[str],
    expected_aliases: dict[str, str],
    expected_baseline_sha256: str,
) -> dict[str, str]:
    """Valida aliases contra el baseline y el estado actual, sin confiar en la tabla.

    Detecta duplicados antes de construir un dict, destinos inexistentes,
    cadenas/ciclos y cualquier deriva respecto del mapeo que se deduce del
    baseline project_id→case_id. Un alias manual solo se añadirá aquí cuando
    exista un manifiesto de evidencia versionado y validado por separado.
    """
    aliases: dict[str, str] = {}
    for old_case_id, canonical_case_id, mapping_basis, baseline_sha256 in rows:
        if old_case_id in aliases:
            raise ValueError(f"case_id_alias tiene old_case_id duplicado: {old_case_id!r}")
        if canonical_case_id not in current_case_ids:
            raise ValueError(
                f"case_id_alias apunta a canonical_case_id inexistente: {old_case_id!r}→{canonical_case_id!r}"
            )
        if mapping_basis not in {"preserved", "merged"}:
            raise ValueError(f"case_id_alias tiene mapping_basis no permitido: {mapping_basis!r}")
        if (mapping_basis == "preserved") != (old_case_id == canonical_case_id):
            raise ValueError(
                f"case_id_alias mapping_basis contradice el par {old_case_id!r}→{canonical_case_id!r}"
            )
        if baseline_sha256 != expected_baseline_sha256:
            raise ValueError(f"case_id_alias usa baseline hash distinto en {old_case_id!r}")
        aliases[old_case_id] = canonical_case_id

    if aliases != expected_aliases:
        missing = sorted(set(expected_aliases) - set(aliases))
        extra = sorted(set(aliases) - set(expected_aliases))
        mismatched = sorted(
            key for key in set(aliases) & set(expected_aliases)
            if aliases[key] != expected_aliases[key]
        )
        raise ValueError(
            "case_id_alias no coincide con el baseline; "
            f"missing={missing[:10]}, extra={extra[:10]}, mismatched={mismatched[:10]}"
        )
    for old_case_id, canonical_case_id in aliases.items():
        if canonical_case_id in aliases and aliases[canonical_case_id] != canonical_case_id:
            raise ValueError(
                f"case_id_alias contiene cadena/ciclo: {old_case_id!r}→{canonical_case_id!r}"
            )
    return aliases


def expected_case_id_aliases_from_baseline(
    baseline_path: Path, current_project_to_case: dict[str, str]
) -> tuple[dict[str, str], str]:
    """Deriva el único alias de baseline permitido y comprueba sus hashes."""
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "project_case_baseline":
        raise ValueError("schema_version de project_case_baseline no reconocido")
    _validate_sha256_field(payload, "source_content_sha256")
    rows = payload.get("projects")
    if not isinstance(rows, list):
        raise ValueError("baseline.projects debe ser una lista")
    project_to_old_case = {row["project_id"]: row["case_id"] for row in rows}
    if len(project_to_old_case) != len(rows) or set(project_to_old_case) != set(current_project_to_case):
        raise ValueError("baseline project_id set no coincide con el warehouse actual")
    mapping_bytes = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    baseline_sha256 = hashlib.sha256(mapping_bytes).hexdigest()
    if payload.get("mapping_sha256") != baseline_sha256:
        raise ValueError("mapping_sha256 del baseline no coincide con su contenido")
    project_ids_bytes = ("\n".join(sorted(project_to_old_case)) + "\n").encode("utf-8")
    if payload.get("project_id_set_sha256") != hashlib.sha256(project_ids_bytes).hexdigest():
        raise ValueError("project_id_set_sha256 del baseline no coincide con su contenido")

    old_to_current: dict[str, set[str]] = defaultdict(set)
    for project_id, old_case_id in project_to_old_case.items():
        current_case_id = current_project_to_case[project_id]
        if not current_case_id:
            raise ValueError(f"project.case_id vacío para {project_id!r}")
        old_to_current[old_case_id].add(current_case_id)
    split = {old: sorted(targets) for old, targets in old_to_current.items() if len(targets) != 1}
    if split:
        raise ValueError(f"un case_id del baseline se dividió: {split}")
    return {old: next(iter(targets)) for old, targets in old_to_current.items()}, baseline_sha256


def execute_sql_statements(conn: sqlite3.Connection, script: str) -> None:
    """Ejecuta un script SQL sin el COMMIT implícito de Connection.executescript()."""
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if pending.strip():
                conn.execute(pending)
            pending = ""
    if pending.strip():
        raise ValueError("script SQL incompleto; falta terminar una sentencia")


def begin_build_transaction(conn: sqlite3.Connection) -> None:
    """Abre la transacción exclusiva que este builder debe poseer por completo.

    `_build_conflicts` confirma o revierte el reemplazo de sus tablas. Aceptar
    una transacción abierta por el llamador permitiría confirmar o descartar
    cambios ajenos, por lo que se rechaza antes de tocar el estado de conexión.
    """
    if conn.in_transaction:
        raise RuntimeError("_build_conflicts no acepta una caller-owned transaction")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN IMMEDIATE")


def hash_committed_warehouse(conn: sqlite3.Connection, warehouse_path: Path) -> dict:
    """Hash del archivo principal solo tras hacer checkpoint completo de WAL.

    El reporte identifica el archivo SQLite publicado. En modo WAL el hash del
    archivo principal omite páginas confirmadas aún residentes en `-wal`; por
    eso truncamos/checkpointeamos antes de calcularlo y fallamos si SQLite no
    confirma que todos los frames están en el archivo principal.
    """
    warehouse_path = Path(warehouse_path)
    journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    if journal_mode not in {"delete", "wal"}:
        raise RuntimeError(f"journal_mode no soportado para hash de warehouse: {journal_mode!r}")

    checkpoint = None
    wal_path = warehouse_path.with_name(warehouse_path.name + "-wal")
    if journal_mode == "wal":
        checkpoint = tuple(conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        busy, log_frames, checkpointed_frames = checkpoint
        if busy or (log_frames >= 0 and checkpointed_frames < log_frames):
            raise RuntimeError(
                "no se puede anclar el hash del warehouse: WAL checkpoint incompleto "
                f"(busy={busy}, log_frames={log_frames}, checkpointed_frames={checkpointed_frames})"
            )
    elif wal_path.exists() and wal_path.stat().st_size > 0:
        raise RuntimeError(
            f"journal_mode=delete pero hay un WAL no vacío; no se calcula un hash parcial: {wal_path}"
        )

    return {
        "sha256": hashlib.sha256(warehouse_path.read_bytes()).hexdigest(),
        "journal_mode": journal_mode,
        "wal_checkpoint": checkpoint,
    }


def atomic_write_json(path: Path, payload: dict, indent: int = 2) -> None:
    """Reemplaza un reporte JSON completo sin exponer archivos truncados."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=indent)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def collect_unresolved_historical_case_ids(
    documentos_63: list[dict], current_case_ids: set[str], case_id_alias: dict[str, str] | None = None
) -> list[dict]:
    """Devuelve todos los IDs historicos que consumira CONFLICT y aun no resuelven.

    Las relaciones ``mismo_proyecto`` se excluyen porque describen identidad
    de PROJECT y esta capa ya las omite deliberadamente. El reporte conserva
    nombres, documentos y tipos de relacion; no propone aliases por similitud.
    """
    references = analyze_historical_case_references(
        documentos_63, current_case_ids, case_id_alias
    )
    if references["unsupported_relations"]:
        unsupported = references["unsupported_relations"]
        raise ValueError(
            "relacion_case_groups contiene relaciones desconocidas; "
            "preflight bloqueado: "
            + ", ".join(
                f"{row.get('relation')!r} en {row.get('document_id')!r}"
                for row in unsupported
            )
        )
    # Compatibilidad con el preflight histórico: `mismo_proyecto` no es una
    # referencia consumida por CONFLICT. El nuevo análisis sí la conserva en
    # una capa de provenance, pero no la trata como bloqueo de esta función.
    return [
        row for row in references["all_unresolved"]
        if any(occ["relation"] != "mismo_proyecto" for occ in row["occurrences"])
    ]


def load_historical_case_id_resolutions(
    path: Path = HISTORICAL_CASE_ID_RESOLUTIONS_PATH,
) -> tuple[dict[str, str], set[str]]:
    """Lee resoluciones citadas de historical_case_id huérfanos de CONFLICT_UNIT_REVIEW.

    Devuelve (resolved_aliases, non_resolvable_ids). `resolved_aliases` son
    alias historical_case_id->case_id vigente, cada uno citando el grado y la
    justificación que la revisión ya escribió en CONFLICT_UNIT_REVIEW (nunca se reinterpreta
    esa decisión, solo se repara el destino tras fusiones posteriores).
    `non_resolvable_ids` son IDs investigados contra el warehouse real sin
    ningún anclaje vivo disponible -- se preservan como referencia histórica
    explícita, nunca se les fuerza un destino. Si el archivo no existe,
    devuelve vacío (esta corrección es opcional, no requerida)."""
    if not path.exists():
        return {}, set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    resolved_aliases: dict[str, str] = {}
    for entry in payload.get("resolved", []):
        hid = entry["historical_case_id"]
        if hid in resolved_aliases:
            raise ValueError(f"historical_case_id_resolutions tiene entrada 'resolved' duplicada: {hid!r}")
        resolved_aliases[hid] = entry["resolved_case_id"]
    non_resolvable_ids: set[str] = set()
    for entry in payload.get("non_resolvable", []):
        hid = entry["historical_case_id"]
        if hid in non_resolvable_ids:
            raise ValueError(f"historical_case_id_resolutions tiene entrada 'non_resolvable' duplicada: {hid!r}")
        non_resolvable_ids.add(hid)
    overlap = set(resolved_aliases) & non_resolvable_ids
    if overlap:
        raise ValueError(f"historical_case_id_resolutions tiene IDs en ambas listas: {sorted(overlap)}")
    return resolved_aliases, non_resolvable_ids


def analyze_historical_case_references(
    documentos_63: list[dict],
    current_case_ids: set[str],
    case_id_alias: dict[str, str] | None = None,
    non_resolvable_historical_ids: set[str] | None = None,
) -> dict[str, list[dict]]:
    """Clasifica referencias históricas no resueltas sin inventar aliases.

    Solo `mismo_conflicto` y `conflictos_distintos` alteran la topología de
    CONFLICT y bloquean una reconstrucción completa si contienen IDs sin
    destino validado. Las relaciones focal/contextual y mismo_proyecto se
    preservan como referencias históricas no proyectadas. Cualquier relación
    nueva/desconocida falla cerrada como bloqueante.

    `non_resolvable_historical_ids` son IDs investigados y confirmados sin
    ningún anclaje vivo disponible (ver historical_case_id_resolutions.json)
    -- se preservan como referencia histórica explícita en vez de bloquear
    indefinidamente. Nunca se infiere esta lista por ausencia de alias; debe
    venir de una investigación documentada aparte."""
    aliases = case_id_alias or {}
    non_resolvable = non_resolvable_historical_ids or set()
    missing: dict[str, dict] = {}
    unsupported_relations: list[dict] = []
    for doc in documentos_63:
        groups = {row.get("case_id"): row for row in doc.get("case_groups", [])}
        for relation_index, relation in enumerate(doc.get("relaciones_case_groups", [])):
            relation_type = relation.get("relacion")
            relation_case_ids = relation.get("case_ids", [])
            if relation_type not in RELACIONES_CASE_CONOCIDAS:
                unsupported_relations.append(
                    {
                        "document_id": doc.get("document_id"),
                        "relation_index": relation_index,
                        "relation": relation_type,
                        "case_ids": relation_case_ids,
                        "historical_case_id": relation_case_ids[0] if relation_case_ids else None,
                        "impact_scope": "unknown_relation_fail_closed",
                        "topology_blocking": True,
                    }
                )
                continue
            for historical_id in relation_case_ids:
                resolved_id = aliases.get(historical_id, historical_id)
                if resolved_id in current_case_ids:
                    continue
                if relation_type in RELACIONES_QUE_CAMBIAN_TOPOLOGIA and historical_id in non_resolvable:
                    # Investigado y confirmado sin ningun anclaje vivo disponible (ver
                    # historical_case_id_resolutions.json) -- se preserva explicitamente
                    # en vez de bloquear indefinidamente. Nunca se le asigna un destino.
                    impact_scope = "confirmed_non_resolvable_historical_reference"
                    topology_blocking = False
                elif relation_type in RELACIONES_QUE_CAMBIAN_TOPOLOGIA:
                    impact_scope = "conflict_topology"
                    topology_blocking = True
                elif relation_type in RELACIONES_DE_MEMBRESIA_DOCUMENTAL:
                    impact_scope = "document_conflict_membership"
                    topology_blocking = False
                elif relation_type in RELACIONES_IDENTIDAD_PROYECTO:
                    impact_scope = "project_identity_not_resolved"
                    topology_blocking = False
                item = missing.setdefault(
                    historical_id,
                    {
                        "historical_case_id": historical_id,
                        "resolved_case_id": resolved_id,
                        "canonical_names": set(),
                        "occurrences": [],
                        "impact_scopes": set(),
                        "topology_blocking": False,
                    },
                )
                group = groups.get(historical_id, {})
                item["canonical_names"].update(group.get("canonical_names", []))
                item["impact_scopes"].add(impact_scope)
                item["topology_blocking"] = item["topology_blocking"] or topology_blocking
                item["occurrences"].append(
                    {
                        "document_id": doc.get("document_id"),
                        "relation": relation_type,
                        "project_relation": relation.get("project_relation"),
                        "case_ids": relation.get("case_ids", []),
                        "impact_scope": impact_scope,
                    }
                )
    rows = []
    for _historical_id, item in sorted(missing.items()):
        row = {
            **item,
            "canonical_names": sorted(item["canonical_names"]),
            "impact_scopes": sorted(item["impact_scopes"]),
            "impact_scope": (
                "unknown_relation_fail_closed"
                if "unknown_relation_fail_closed" in item["impact_scopes"]
                else "conflict_topology"
                if item["topology_blocking"]
                else sorted(item["impact_scopes"])[0]
            ),
            "occurrences": sorted(
                item["occurrences"],
                key=lambda occurrence: (
                    occurrence["document_id"] or "",
                    occurrence["relation"] or "",
                    occurrence["project_relation"] or "",
                ),
            ),
        }
        rows.append(row)
    topology_blockers = [row for row in rows if row["topology_blocking"]]
    topology_blockers.extend(unsupported_relations)
    return {
        "all_unresolved": rows,
        "topology_blockers": topology_blockers,
        "preserved_references": [row for row in rows if not row["topology_blocking"]],
        "unsupported_relations": unsupported_relations,
    }


def build_historical_case_reference_rows(
    documentos_63: list[dict],
    current_case_ids: set[str],
    case_id_alias: dict[str, str] | None = None,
    non_resolvable_historical_ids: set[str] | None = None,
) -> list[dict]:
    """Serializa referencias no resueltas sin asignar `case_id`, proyecto ni conflicto.

    La tabla resultante es provenance, no una entidad de conflicto. Relaciones
    topológicas permanecen bloqueadas por `analyze_historical_case_references`,
    salvo que el ID esté en `non_resolvable_historical_ids` (investigado y
    confirmado sin anclaje vivo) -- en ese caso sí se persiste como referencia
    histórica explícita, nunca se descarta en silencio.
    """
    aliases = case_id_alias or {}
    non_resolvable = non_resolvable_historical_ids or set()
    rows = []
    for doc in documentos_63:
        groups = {row.get("case_id"): row for row in doc.get("case_groups", [])}
        for relation_index, relation in enumerate(doc.get("relaciones_case_groups", [])):
            relation_type = relation.get("relacion")
            if relation_type not in RELACIONES_CASE_CONOCIDAS:
                raise ValueError(f"relacion_case_groups desconocida: {relation_type!r}")
            for historical_id in relation.get("case_ids", []):
                resolved_id = aliases.get(historical_id, historical_id)
                if resolved_id in current_case_ids:
                    continue
                if relation_type in RELACIONES_QUE_CAMBIAN_TOPOLOGIA and historical_id in non_resolvable:
                    impact_scope = "confirmed_non_resolvable_historical_reference"
                elif relation_type in RELACIONES_QUE_CAMBIAN_TOPOLOGIA:
                    # No se materializa una topología incompleta; el caller
                    # debe haber abortado antes de DDL.
                    continue
                elif relation_type in RELACIONES_DE_MEMBRESIA_DOCUMENTAL:
                    impact_scope = "document_conflict_membership"
                else:
                    impact_scope = "project_identity_not_resolved"
                group = groups.get(historical_id, {})
                occurrence_key = "|".join(
                    [
                        str(doc.get("document_id") or ""),
                        str(historical_id),
                        str(relation_type or ""),
                        str(relation.get("project_relation") or ""),
                        str(relation_index),
                    ]
                )
                rows.append(
                    {
                        "reference_id": hashlib.sha256(occurrence_key.encode("utf-8")).hexdigest()[:32],
                        "document_id": doc.get("document_id"),
                        "historical_case_id": historical_id,
                        "canonical_names_json": json.dumps(
                            sorted(group.get("canonical_names", [])), ensure_ascii=False
                        ),
                        "relation_type": relation_type or "",
                        "project_relation": relation.get("project_relation"),
                        "case_ids_json": json.dumps(relation.get("case_ids", []), ensure_ascii=False),
                        "impact_scope": impact_scope,
                        "status": "preserved_unresolved_not_projected",
                        "source": "conflict_unit_review_historical_reference",
                    }
                )
    return rows


def create_historical_case_reference_table(conn: sqlite3.Connection) -> None:
    """Crea la tabla lateral de provenance sin claves de identidad proyectadas."""
    conn.execute(
        """
        CREATE TABLE historical_case_reference (
            reference_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES document(document_id),
            historical_case_id TEXT NOT NULL,
            canonical_names_json TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            project_relation TEXT,
            case_ids_json TEXT NOT NULL,
            impact_scope TEXT NOT NULL CHECK (impact_scope IN ('document_conflict_membership', 'project_identity_not_resolved', 'confirmed_non_resolvable_historical_reference')),
            status TEXT NOT NULL CHECK (status = 'preserved_unresolved_not_projected'),
            source TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_historical_case_reference_document ON historical_case_reference(document_id)"
    )
    conn.execute(
        "CREATE INDEX idx_historical_case_reference_id ON historical_case_reference(historical_case_id)"
    )


def persist_historical_case_reference_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany(
        "INSERT INTO historical_case_reference (reference_id, document_id, historical_case_id, canonical_names_json, "
        "relation_type, project_relation, case_ids_json, impact_scope, status, source) "
        "VALUES (:reference_id, :document_id, :historical_case_id, :canonical_names_json, :relation_type, "
        ":project_relation, :case_ids_json, :impact_scope, :status, :source)",
        rows,
    )
    return len(rows)


def split_case_ids_for_projection(
    case_ids: list[str], current_case_ids: set[str], case_id_alias: dict[str, str] | None = None
) -> tuple[list[str], list[str]]:
    """Devuelve IDs vigentes proyectables y los históricos que quedan preservados."""
    aliases = case_id_alias or {}
    projected: list[str] = []
    unresolved: list[str] = []
    for historical_id in case_ids:
        resolved_id = aliases.get(historical_id, historical_id)
        if resolved_id in current_case_ids:
            projected.append(resolved_id)
        else:
            unresolved.append(historical_id)
    return sorted(set(projected)), sorted(set(unresolved))


def _sha256_file_if_present(path: Path, text: bool = True) -> str | None:
    """SHA-256 del archivo. Los archivos de texto se normalizan a LF (la huella no depende de la configuracion de
    git del equipo); un archivo binario (`text=False`) se hashea tal cual."""
    path = Path(path)
    if not path.is_file():
        return None
    data = path.read_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if text else data).hexdigest()


def load_unresolved_project_identity_blockers(conn: sqlite3.Connection) -> list[dict]:
    """Return every unresolved PROJECT identity pair as a publication blocker.

    `project_review_queue` is upstream of CASE/CONFLICT topology. Missing or
    malformed queue state fails closed instead of silently authorizing a full
    rebuild from an incomplete identity review.
    """
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_review_queue'"
    ).fetchone()
    if not table_exists:
        return [{"blocker_type": "project_review_queue_missing", "reason": "falta la cola de identidad PROJECT"}]

    columns = {row[1] for row in conn.execute("PRAGMA table_info(project_review_queue)")}
    required = {"project_id_a", "canonical_name_a", "project_id_b", "canonical_name_b", "resolved"}
    missing = sorted(required - columns)
    if missing:
        return [{
            "blocker_type": "project_review_queue_invalid",
            "reason": "faltan columnas requeridas para verificar la cola de identidad",
            "missing_columns": missing,
        }]

    optional = {
        name: (name if name in columns else f"NULL AS {name}")
        for name in ("decision", "decision_reason", "decision_source")
    }
    where = "COALESCE(resolved, 0) = 0"
    if "decision" in columns:
        where += " OR decision = 'needs_human_review'"
    rows = conn.execute(
        "SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b, "
        f"{optional['decision']}, {optional['decision_reason']}, {optional['decision_source']} "
        f"FROM project_review_queue WHERE {where} ORDER BY rowid"
    ).fetchall()
    return [
        {
            "blocker_type": "unresolved_project_identity_pair",
            "queue_rowid": row[0],
            "project_id_a": row[1],
            "project_name_a": row[2],
            "project_id_b": row[3],
            "project_name_b": row[4],
            "decision": row[5],
            "decision_reason": row[6],
            "decision_source": row[7],
        }
        for row in rows
    ]


def build_historical_case_preflight_report(
    analysis: dict[str, list[dict]], classified_path: Path = CONFLICT_UNIT_REVIEW, warehouse_path: Path = WAREHOUSE
) -> dict:
    """Reporte durable de bloqueo, separado del reporte de una build exitosa."""
    blockers = analysis["topology_blockers"]
    return {
        "schema_version": "historical_case_reference_preflight",
        "run_id": datetime.now(timezone.utc).isoformat(),
        "status": "blocked_before_database_write" if blockers else "topology_preflight_passed",
        "policy": {
            "topology_blocking_relations": sorted(RELACIONES_QUE_CAMBIAN_TOPOLOGIA),
            "preserve_without_alias": sorted(
                RELACIONES_DE_MEMBRESIA_DOCUMENTAL | RELACIONES_IDENTIDAD_PROYECTO
            ),
            "unknown_relation_types": "fail_closed",
        },
        "source_hashes": {
            "classified_63_sha256": _sha256_file_if_present(classified_path),
            "warehouse_file_sha256": _sha256_file_if_present(warehouse_path, text=False),
            "preflight_script_sha256": _sha256_file_if_present(Path(__file__)),
        },
        "n_unresolved_ids": len(analysis["all_unresolved"]),
        "n_topology_blockers": len(blockers),
        "n_preserved_non_topological_ids": len(analysis["preserved_references"]),
        "unsupported_relations": analysis.get("unsupported_relations", []),
        "topology_blockers": blockers,
        "preserved_references": analysis["preserved_references"],
        "publication_note": (
            "Una preflight que bloquea no modifica tablas ni sustituye el reporte de una build exitosa. "
            "Las referencias no topológicas quedan preservadas en una tabla separada en una build futura; "
            "no se proyectan como project_id, case_id ni conflict_id."
        ),
    }


def remap_historical_case_ids(
    case_ids: list[str], current_case_ids: set[str], case_id_alias: dict[str, str] | None = None
) -> list[str]:
    aliases = case_id_alias or {}
    remapped = []
    for original_id in case_ids:
        current_id = aliases.get(original_id, original_id)
        if current_id not in current_case_ids:
            raise ValueError(f"case_id histórico {original_id!r} no existe en el baseline ni en case_id_alias")
        remapped.append(current_id)
    return sorted(set(remapped))


def build_case_groups(
    all_case_ids: list[str],
    documentos_63: list[dict],
    case_id_alias: dict[str, str] | None = None,
    non_resolvable_historical_ids: set[str] | None = None,
) -> dict[str, list[str]]:
    """case_id -> lista ordenada de case_id de su grupo (incluyendose a si
    mismo si es trivial). Los IDs históricos se remapean explícitamente; un
    ID desconocido falla, en vez de desaparecer silenciosamente -- salvo que
    esté en `non_resolvable_historical_ids` (investigado y confirmado sin
    anclaje vivo, ver historical_case_id_resolutions.json), en cuyo caso
    esa relación puntual se omite en vez de forzar un destino inventado."""
    uf = UnionFind(all_case_ids)
    current_ids = set(all_case_ids)
    aliases = case_id_alias or {}
    non_resolvable = non_resolvable_historical_ids or set()
    for doc in documentos_63:
        for rel in doc.get("relaciones_case_groups", []):
            relation_type = rel.get("relacion")
            if relation_type not in RELACIONES_CASE_CONOCIDAS:
                raise ValueError(f"relacion_case_groups desconocida: {relation_type!r}")
            if relation_type not in RELACIONES_QUE_UNEN:
                continue
            if non_resolvable & set(rel["case_ids"]):
                continue
            ids = remap_historical_case_ids(rel["case_ids"], current_ids, aliases)
            for cid in ids[1:]:
                uf.union(ids[0], cid)

    groups: dict[str, list[str]] = defaultdict(list)
    for cid in all_case_ids:
        groups[uf.find(cid)].append(cid)
    return {root: sorted(members) for root, members in groups.items()}


def build_conflict_relations(
    documentos_63: list[dict],
    case_id_to_conflict: dict[str, str],
    gate_status_by_document: dict[str, str],
    case_id_alias: dict[str, str] | None = None,
    non_resolvable_historical_ids: set[str] | None = None,
) -> list[dict]:
    """Relaciones entre conflictos que NO se fusionan -- 'conflictos_distintos'
    marcado explicitamente por la revisión como posible trayectoria longitudinal
    compartiendo territorio/actor.

    La v1 marcaba
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

    Antes, si 2+ documentos
    evidenciaban el mismo par de conflictos, solo se conservaba el primer
    'note' encontrado (provenance perdido). Ahora se acumulan todos los
    documentos de evidencia por par en 'documentos_evidencia'."""
    relations: dict[tuple, dict] = {}
    non_resolvable = non_resolvable_historical_ids or set()
    for doc in documentos_63:
        gate_status = gate_status_by_document.get(doc["document_id"], "caso_unico")
        review_status = "pending_human_decision" if gate_status == "caso_unico" else "resolved_keep_separate"
        for rel in doc.get("relaciones_case_groups", []):
            relation_type = rel.get("relacion")
            if relation_type not in RELACIONES_CASE_CONOCIDAS:
                raise ValueError(f"relacion_case_groups desconocida: {relation_type!r}")
            if relation_type != "conflictos_distintos":
                continue
            if non_resolvable & set(rel["case_ids"]):
                continue
            current_ids = remap_historical_case_ids(
                rel["case_ids"], set(case_id_to_conflict), case_id_alias
            )
            conflict_ids = sorted({case_id_to_conflict[cid] for cid in current_ids})
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
                            "justificacion": doc["justificacion"],
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
    verified_links_by_docid: dict[tuple[str, str], int | None],
    adjudicated_cms: frozenset[str] | None = None,
) -> tuple[str | None, str, list[dict]]:
    """Aplica el detector de respaldo a TODOS los proyectos de un conflicto
    (sin excepcion por n_case_ids) y decide label + respaldo_evidencia.
    `projects` es la lista (project_id, canonical_name) de todos los
    project_id que componen el conflicto. Devuelve (label,
    respaldo_evidencia, filas de conflict_evidence_backing)."""
    backed_projects: list[tuple[str, str]] = []
    backing_rows: list[dict] = []
    for pid, canonical_name in projects:
        rows = _project_backing_evidence(pid, mentions_by_project, included_by_doc, objeto_by_cm, verified_links_by_docid, adjudicated_cms)
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
                        "detector_version": r["detector_version"],
                        "match_method": r["match_method"],
                        "backing_scope": r["backing_scope"],
                        "document_case_mention_count": r["document_case_mention_count"],
                        "document_object_case_mention_count": r["document_object_case_mention_count"],
                        "ambiguous_multi_case_document": r["ambiguous_multi_case_document"],
                        "duplicate_group_mixed_decision": r["duplicate_group_mixed_decision"],
                    }
                )

    # Label: preferir canonical_name entre proyectos RESPALDADOS (la revision de respaldo,
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
        "n_documents_mixed_duplicate_group_backing": len({
            row["document_id"] for row in backing_rows if row.get("duplicate_group_mixed_decision")
        }),
    }


def _build_conflicts(conn: sqlite3.Connection):
    # Bloquea escrituras concurrentes antes de leer cualquier tabla fuente;
    # las tablas derivadas se reemplazan después dentro de esta transacción.
    begin_build_transaction(conn)
    project_identity_blockers = load_unresolved_project_identity_blockers(conn)

    all_case_ids = sorted({r[0] for r in conn.execute("SELECT DISTINCT case_id FROM project WHERE case_id IS NOT NULL")})
    documentos_63 = load_conflict_unit_review()

    # Precomputo unico para el detector de respaldo -- sin cascada
    # de queries por conflicto. Fuente autoritativa: evidence + case_mention
    # (nunca enrichment_evidence, que no conserva case_mention_id).
    included_by_doc: dict[str, list[str]] = defaultdict(list)
    for doc_id, cm_id in conn.execute("SELECT document_id, case_mention_id FROM case_mention WHERE decision_final_amplio = 'include'"):
        included_by_doc[doc_id].append(cm_id)
    eligibility_adjudications = load_case_mention_eligibility_adjudications(conn, CASE_MENTION_ELIGIBILITY_ADJUDICATIONS_PATH)
    for cm_id in eligibility_adjudications:
        doc_id = cm_id.rsplit(":", 1)[0]
        if cm_id not in included_by_doc[doc_id]:
            included_by_doc[doc_id].append(cm_id)
    adjudicated_cms = frozenset(eligibility_adjudications)
    objeto_by_cm: dict[str, list[dict]] = defaultdict(list)
    for cm_id, ev_id, quote_text in conn.execute(
        "SELECT case_mention_id, evidence_id, quote_text FROM evidence WHERE quote_role = 'objeto' AND verified = 1"
    ):
        objeto_by_cm[cm_id].append({"evidence_id": ev_id, "quote_text": quote_text, "quote_norm": _norm(quote_text)})
    mentions_by_project: dict[str, list[dict]] = defaultdict(list)
    for pid, doc_id, raw_name in conn.execute("SELECT project_id, document_id, raw_nombre_proyecto FROM project_mention_resolved"):
        mentions_by_project[pid].append({"document_id": doc_id, "raw_nombre_proyecto": raw_name})
    case_id_by_project: dict[str, str] = dict(conn.execute("SELECT project_id, case_id FROM project WHERE case_id IS NOT NULL"))

    # la extraccion vigente (2026-09-26): case_mention_index ya esta materializado en
    # enrichment_project_mention -- se consulta directo, sin releer JSONL.
    verified_links_by_docid = load_verified_links(conn)

    alias_table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_id_alias'"
    ).fetchone() is not None
    if alias_table_exists:
        current_project_to_case = dict(
            conn.execute("SELECT project_id, case_id FROM project WHERE case_id IS NOT NULL")
        )
        expected_aliases, baseline_sha256 = expected_case_id_aliases_from_baseline(
            CASE_BASELINE, current_project_to_case
        )
        alias_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(case_id_alias)").fetchall()
        }
        required_alias_columns = {
            "old_case_id", "canonical_case_id", "mapping_basis", "baseline_mapping_sha256"
        }
        if not required_alias_columns <= alias_columns:
            raise ValueError(
                "case_id_alias carece de columnas requeridas: "
                f"{sorted(required_alias_columns - alias_columns)}"
            )
        alias_rows = conn.execute(
            "SELECT old_case_id, canonical_case_id, mapping_basis, baseline_mapping_sha256 "
            "FROM case_id_alias"
        ).fetchall()
        case_id_alias = validate_case_id_alias_rows(
            alias_rows, set(all_case_ids), expected_aliases, baseline_sha256
        )
    else:
        case_id_alias = {case_id: case_id for case_id in all_case_ids}

    historical_resolved_aliases, non_resolvable_historical_ids = load_historical_case_id_resolutions(
        HISTORICAL_CASE_ID_RESOLUTIONS_PATH
    )
    for hid, target_case_id in historical_resolved_aliases.items():
        if target_case_id not in set(all_case_ids):
            raise ValueError(
                f"historical_case_id_resolutions apunta a case_id inexistente: {hid!r}->{target_case_id!r}"
            )
        if hid in case_id_alias and case_id_alias[hid] != target_case_id:
            raise ValueError(
                f"historical_case_id_resolutions choca con case_id_alias existente para {hid!r}: "
                f"{case_id_alias[hid]!r} vs {target_case_id!r}"
            )
    case_id_alias = {**case_id_alias, **historical_resolved_aliases}

    reference_analysis = analyze_historical_case_references(
        documentos_63, set(all_case_ids), case_id_alias, non_resolvable_historical_ids
    )
    all_topology_blockers = [
        *reference_analysis["topology_blockers"],
        *project_identity_blockers,
    ]
    report_analysis = {**reference_analysis, "topology_blockers": all_topology_blockers}
    preflight_report = build_historical_case_preflight_report(
        report_analysis, classified_path=CONFLICT_UNIT_REVIEW, warehouse_path=WAREHOUSE
    )
    preflight_report["n_confirmed_non_resolvable_historical_references"] = len(non_resolvable_historical_ids)
    preflight_report["project_identity_review_gate"] = {
        "status": "blocked" if project_identity_blockers else "clear",
        "policy": "cada par PROJECT sin decisión final bloquea la reconstrucción integral de CONFLICT",
        "n_unresolved_pairs": len(project_identity_blockers),
        "unresolved_pairs": project_identity_blockers,
    }
    atomic_write_json(HISTORICAL_CASE_PREFLIGHT_REPORT_PATH, preflight_report)
    if all_topology_blockers:
        print(json.dumps(preflight_report, ensure_ascii=False, indent=2), file=sys.stderr)
        conn.rollback()
        return 2
    historical_reference_rows = build_historical_case_reference_rows(
        documentos_63, set(all_case_ids), case_id_alias, non_resolvable_historical_ids
    )
    case_groups = build_case_groups(
        all_case_ids, documentos_63, case_id_alias=case_id_alias,
        non_resolvable_historical_ids=non_resolvable_historical_ids,
    )
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

        # Detector de respaldo: aplicado UNIFORMEMENTE, sin
        # excepcion para n_case_ids>1 -- ver docstring del modulo (Aeropuerto
        # Los Cerrillos y Aldea del Encuentro, ambos multi-case revisados,
        # resultaron error_grave en la validacion N=150).
        label, respaldo_evidencia, backing_rows = _build_conflict_backing(
            conflict_id, projects, case_id_by_project, mentions_by_project, included_by_doc, objeto_by_cm,
            verified_links_by_docid, adjudicated_cms
        )
        conflict_evidence_backing_rows.extend(backing_rows)
        backing_summary = _backing_summary(projects, backing_rows)

        conflict_rows.append(
            {
                "conflict_id": conflict_id,
                "label": label,
                "n_case_ids": len(members),
                "origen": "conflict_unit_review_evidence" if len(members) > 1 else "trivial_single_case",
                "confidence": "alta_revisado_manualmente" if len(members) > 1 else "baja_derivado_mecanicamente",
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

    conflict_relation_rows = build_conflict_relations(
        documentos_63, case_id_to_conflict, gate_status_by_document, case_id_alias=case_id_alias,
        non_resolvable_historical_ids=non_resolvable_historical_ids,
    )

    # role tenia 2 fallas: (1)
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
        for rel in doc.get("relaciones_case_groups", []):
            relacion = rel.get("relacion")
            if relacion == "mismo_proyecto":
                continue  # identidad de proyecto (alias), no evidencia de conflicto
            if relacion not in RELACIONES_CASE_CONOCIDAS:
                raise ValueError(f"relacion_case_groups desconocida: {relacion!r}")
            role = ROLE_BY_RELACION.get(relacion, "mentioned_unreviewed")
            remapped_case_ids, unresolved_case_ids = split_case_ids_for_projection(
                rel["case_ids"], set(case_id_to_conflict), case_id_alias
            )
            genuinely_unresolved = [
                cid for cid in unresolved_case_ids if cid not in non_resolvable_historical_ids
            ]
            if genuinely_unresolved and relacion not in RELACIONES_DE_MEMBRESIA_DOCUMENTAL:
                raise ValueError(
                    "referencia histórica no topológica no proyectable en document_conflict: "
                    f"{doc['document_id']} {relacion} {genuinely_unresolved}"
                )
            for cid in remapped_case_ids:
                cflt = case_id_to_conflict.get(cid)
                if cflt is None:
                    raise ValueError(f"case_id proyectable sin conflict_id: {cid}")
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
                        {"relaciones": info["evidence"], "justificacion": doc["justificacion"]},
                        ensure_ascii=False,
                    ),
                    "source": "conflict_unit_review",
                    "unidad_caso_tipo": gate_status_by_document.get(doc["document_id"], doc["unidad_caso_tipo"]),
                }
            )

    # usaba directamente
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
    reviewed_pairs = {(r["document_id"], r["conflict_id"]) for r in document_conflict_rows}
    for document_id, raw_nombre, project_id, case_id, nombre_proyecto_focal, unidad_caso_tipo in rows:
        cflt = case_id_to_conflict.get(case_id)
        if cflt is None:
            continue
        if document_id in documentos_63_ids:
            # La revision humana decide los roles de este documento. Un conflicto que la revision no toca igual
            # tiene al documento como fuente de sus menciones: se conserva el vinculo, nunca como focal.
            if (document_id, cflt) in reviewed_pairs:
                continue
            role = "mentioned_unreviewed"
        else:
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

    execute_sql_statements(
        conn,
        """
        DROP VIEW IF EXISTS actor_event_project_link_conflict_safe;
        DROP VIEW IF EXISTS actor_event_project_link_conflict_extended;
        DROP VIEW IF EXISTS conflict_conservative;
        DROP TABLE IF EXISTS conflict_scope;
        DROP VIEW IF EXISTS document_conflict_case_safe;
        DROP VIEW IF EXISTS document_conflict_case_extended;
        DROP TABLE IF EXISTS conflict_relation;
        DROP TABLE IF EXISTS historical_case_reference;
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
            n_documents_ambiguous_backing INTEGER NOT NULL CHECK (n_documents_ambiguous_backing >= 0),
            n_documents_mixed_duplicate_group_backing INTEGER NOT NULL CHECK (n_documents_mixed_duplicate_group_backing >= 0)
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

        -- Provenance completo del respaldo de
        -- evidencia -- nunca solo una bandera. Cada fila es una cita literal
        -- que justifica que un project_id (y por lo tanto el conflict_id que
        -- lo contiene) tiene un case_mention incluido y verificado detras.
        -- Ausencia de filas para un conflict_id = sin_respaldo_exact_quote_detectado.
        -- detector_version separado de match_method a proposito: manana puede
        -- existir otro detector textual con varios tipos de match, y la fila debe
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
            backing_scope TEXT NOT NULL CHECK (backing_scope IN ('document_level_case_mention_without_project_link', 'mention_level_verified_index')),
            document_case_mention_count INTEGER NOT NULL CHECK (document_case_mention_count >= 0),
            document_object_case_mention_count INTEGER NOT NULL CHECK (document_object_case_mention_count >= 0),
            ambiguous_multi_case_document INTEGER NOT NULL CHECK (ambiguous_multi_case_document IN (0, 1)),
            duplicate_group_mixed_decision INTEGER NOT NULL CHECK (duplicate_group_mixed_decision IN (0, 1)),
            PRIMARY KEY (conflict_id, project_id, document_id, case_mention_id, evidence_id)
        );
        CREATE INDEX idx_conflict_backing_conflict ON conflict_evidence_backing(conflict_id);
        CREATE INDEX idx_conflict_backing_project ON conflict_evidence_backing(project_id);
        CREATE INDEX idx_conflict_backing_case_mention ON conflict_evidence_backing(case_mention_id);
        CREATE INDEX idx_conflict_backing_document ON conflict_evidence_backing(document_id);

        -- la primera version
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

        -- Base para la red ACTOR<->CONFLICT (siguiente
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
        """,
    )
    create_historical_case_reference_table(conn)

    conn.executemany(
        "INSERT INTO conflict (conflict_id, label, n_case_ids, origen, confidence, respaldo_evidencia, "
        "n_projects_backed, n_projects_unbacked, coverage_backing, label_source_project_id, "
        "n_documents_ambiguous_backing, n_documents_mixed_duplicate_group_backing) "
        "VALUES (:conflict_id, :label, :n_case_ids, :origen, :confidence, :respaldo_evidencia, "
        ":n_projects_backed, :n_projects_unbacked, :coverage_backing, :label_source_project_id, "
        ":n_documents_ambiguous_backing, :n_documents_mixed_duplicate_group_backing)",
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
        "ambiguous_multi_case_document, duplicate_group_mixed_decision) "
        "VALUES (:conflict_id, :case_id, :project_id, :document_id, :case_mention_id, :evidence_id, "
        ":raw_nombre_proyecto, :quote_text, :quote_role, :detector_version, :match_method, "
        ":backing_scope, :document_case_mention_count, :document_object_case_mention_count, "
        ":ambiguous_multi_case_document, :duplicate_group_mixed_decision)",
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
    n_historical_references_persisted = persist_historical_case_reference_rows(conn, historical_reference_rows)
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
    historical_reference_scope_counts: dict[str, int] = defaultdict(int)
    for row in historical_reference_rows:
        historical_reference_scope_counts[row["impact_scope"]] += 1
    n_trivial_backed = sum(
        1 for c in conflict_rows if c["n_case_ids"] == 1 and c["respaldo_evidencia"] == "respaldo_exact_quote_detectado"
    )
    n_projects_total = len(case_id_by_project)
    n_projects_with_backing = sum(
        1 for pid in case_id_by_project
        if _project_backing_evidence(pid, mentions_by_project, included_by_doc, objeto_by_cm, verified_links_by_docid, adjudicated_cms)
    )
    backing_rows_by_detector: dict[str, int] = defaultdict(int)
    conflicts_with_backing_by_detector: dict[str, set] = defaultdict(set)
    for row in conflict_evidence_backing_rows:
        backing_rows_by_detector[row["detector_version"]] += 1
        conflicts_with_backing_by_detector[row["detector_version"]].add(row["conflict_id"])
    summary = {
        "n_conflicts_total": len(conflict_rows),
        "n_case_mention_eligibility_adjudications": len(eligibility_adjudications),
        "n_conflicts_multi_case": n_multi,
        "n_conflicts_trivial": n_trivial,
        "n_conflicts_evidence_backed": n_conflicts_backed,
        "n_conflicts_without_exact_backing": len(conflict_rows) - n_conflicts_backed,
        "n_conflicts_with_mixed_duplicate_group_backing": sum(
            1 for c in conflict_rows if c["n_documents_mixed_duplicate_group_backing"] > 0
        ),
        "n_conflict_project_links": len(conflict_project_rows),
        "n_document_conflict_links": len(document_conflict_rows),
        "n_document_conflict_from_review": sum(1 for r in document_conflict_rows if r["source"] == "conflict_unit_review"),
        "n_document_conflict_trivial": sum(1 for r in document_conflict_rows if r["source"] == "trivial_from_project_mention"),
        "n_historical_case_references_preserved_unprojected": n_historical_references_persisted,
        "historical_case_reference_impact_scope_counts": dict(historical_reference_scope_counts),
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
        "backing_rows_deduplicated": len(conflict_evidence_backing_rows) - n_backing_rows_persisted,
        "coverage_backing": {
            "total": sum(1 for c in conflict_rows if c["coverage_backing"] == "total"),
            "parcial": sum(1 for c in conflict_rows if c["coverage_backing"] == "parcial"),
            "ninguna": sum(1 for c in conflict_rows if c["coverage_backing"] == "ninguna"),
        },
        "conflicts_with_ambiguous_multi_case_backing": sum(
            1 for c in conflict_rows if c["n_documents_ambiguous_backing"] > 0
        ),
        "conflicts_with_mixed_duplicate_group_backing": sum(
            1 for c in conflict_rows if c["n_documents_mixed_duplicate_group_backing"] > 0
        ),
        "backing_rows_via_mixed_duplicate_group_decision": sum(
            1 for row in conflict_evidence_backing_rows if row["duplicate_group_mixed_decision"]
        ),
        "detector_versions": [DETECTOR_VERSION],
        "backing_rows_by_detector": dict(backing_rows_by_detector),
        "conflicts_with_backing_by_detector": {
            DETECTOR_VERSION: len(conflicts_with_backing_by_detector[DETECTOR_VERSION]),
        },
        "backing_method_note": "El respaldo usa el case_mention_index que el modelo eligio y el pipeline verifico; la asociacion se valido con dos rondas de revision ciega independiente (0 fabricaciones en 809 evaluaciones, ver audit/validation_summary.json). Un proyecto mencionado sin indice no tiene respaldo: no se adivina por texto.",
    }
    warehouse_hash = hash_committed_warehouse(conn, WAREHOUSE)
    audit_report["warehouse_sha256"] = warehouse_hash["sha256"]
    audit_report["sqlite_journal_mode"] = warehouse_hash["journal_mode"]
    audit_report["wal_checkpoint"] = warehouse_hash["wal_checkpoint"]
    AUDIT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # El reporte es otro recurso distinto de SQLite: el replace evita JSON
    # parcial, aunque un fallo aquí después del commit no puede revertir DB.
    atomic_write_json(AUDIT_REPORT_PATH, audit_report)
    # Solo un cierre de build posterior al commit y a la escritura del audit
    # habilita manifiesto/dashboard. Un preflight pasado pero una corrida
    # interrumpida permanece no publicable.
    preflight_report["status"] = "conflict_build_completed"
    preflight_report["n_topology_blockers"] = 0
    preflight_report["completed_conflict_topology_sha256"] = conflict_topology_fingerprint(conn)
    preflight_report["completed_warehouse_sha256"] = warehouse_hash["sha256"]
    preflight_report["completed_audit_report_sha256"] = _sha256_file_if_present(AUDIT_REPORT_PATH)
    atomic_write_json(HISTORICAL_CASE_PREFLIGHT_REPORT_PATH, preflight_report)
    summary["audit_report_path"] = str(AUDIT_REPORT_PATH.relative_to(PROJECT_ROOT))
    return summary


def main() -> int:
    conn = sqlite3.connect(WAREHOUSE)
    try:
        result = _build_conflicts(conn)
        # _build_conflicts returns an integer only for its explicit blocked
        # path; successful runs return the printed summary object. The CLI
        # contract is strictly an exit status, never SystemExit(dict).
        return result if isinstance(result, int) else 0
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
