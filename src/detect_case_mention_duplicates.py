"""Fix 1E (2026-09-24): detecta case_mentions duplicadas/casi-duplicadas
DENTRO del mismo documento, generadas por classify.py (Etapa 1) sin ningun
paso de deduplicacion. Confirmado leyendo classify.py completo: una sola
llamada LLM por documento genera la lista de case_mentions; nada compara una
mencion contra otra del mismo documento despues.

Causa raiz documentada en las 2 rondas de revision ciega de Sol sobre v3.3
(2026-09-24): la mayoria de los desacuerdos reales entre Sol y el modelo se
explicaban por esto, no por errores de v3.3. Ejemplo extremo real: el
humedal de Quilicura tiene 5 case_mentions identicas (mismo objeto, misma
comuna, mismo include), solo distinguidas por que frase del texto citan.

Este detector es 100% retroactivo y aditivo -- NUNCA borra, renumera ni
reescribe ningun case_mention_id/mention_index/evidence_id existente. Eso es
deliberado: renumerar romperia el hash sha256 pinneado en build_conflicts.py
(CLASSIFICATIONS_SHA256_EXPECTED) y cada case_mention_id ya referenciado por
evidence, por las 330 respuestas de v3.3 ya validadas por Sol, y por
conflict_evidence_backing. Solo agrega una tabla nueva
(case_mention_duplicate_link) que registra que grupos de case_mentions del
mismo documento describen, con alta confianza, el mismo objeto real.

Mismo principio "nunca fuzzy" ya congelado en build_conflicts.py (Fix 1A):
dos criterios deterministas, nunca similitud difusa/embeddings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_conflicts import _norm, UnionFind  # noqa: E402 -- reutiliza, no reimplementa

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
CLASSIFICATIONS_PATH = PROJECT_ROOT / "Auditoria" / "clasificacion" / "classifications.jsonl"
CLASSIFICATIONS_SHA256_EXPECTED = "fc96bf57a34e13a10016087efe856a30ce83b37e6a7af87631af57469d597af7"
AUDIT_REPORT_PATH = PROJECT_ROOT / "audit" / "case_mention_duplicates_report.json"

DETECTOR_VERSION = "exact_object_or_quote_substring_v1"
MIN_QUOTE_LEN = 8  # citas mas cortas que esto son demasiado genericas para un match seguro


def _stable_group_id(case_mention_ids: list[str]) -> str:
    return "cmdup:" + hashlib.sha256("|".join(sorted(case_mention_ids)).encode("utf-8")).hexdigest()[:24]


def compute_duplicate_groups(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Para un documento, devuelve 1 fila por case_mention (grupos de
    tamano 1 incluidos -- invariante: TODA case_mention tiene exactamente
    una fila). Nunca fuzzy: (a) tipo_objeto_raw normalizado identico, o
    (b) substring bidireccional de la primera evidencia_objeto_quotes no
    vacia (>= MIN_QUOTE_LEN caracteres) -- mismo patron exacto que
    _mention_has_case_backing en build_conflicts.py."""
    document_id = record.get("content_sha256")
    case_mentions = record.get("case_mentions") or []
    n = len(case_mentions)
    if n == 0:
        return []

    case_mention_ids = [f"{document_id}:{i}" for i in range(n)]
    objetos = [_norm(cm.get("tipo_objeto_raw")) for cm in case_mentions]
    quotes = []
    for cm in case_mentions:
        qs = cm.get("evidencia_objeto_quotes") or []
        quotes.append(_norm(qs[0]) if qs else "")

    uf = UnionFind(case_mention_ids)
    match_method_by_pair: dict[tuple[str, str], str] = {}
    for i in range(n):
        for j in range(i + 1, n):
            method = None
            if objetos[i] and objetos[i] == objetos[j]:
                method = "tipo_objeto_raw_exact"
            qi, qj = quotes[i], quotes[j]
            if qi and qj and len(qi) >= MIN_QUOTE_LEN and len(qj) >= MIN_QUOTE_LEN and (qi in qj or qj in qi):
                method = "ambos" if method else "quote_substring"
            if method:
                uf.union(case_mention_ids[i], case_mention_ids[j])
                match_method_by_pair[(case_mention_ids[i], case_mention_ids[j])] = method

    groups: dict[str, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(case_mention_ids[i])].append(i)

    rows = []
    for members in groups.values():
        member_ids = [case_mention_ids[i] for i in members]
        group_size = len(members)
        decisions = {case_mentions[i].get("decision") for i in members}
        decision_mixed = int(len(decisions) > 1)
        if group_size == 1:
            canonical = member_ids[0]
            method = "single"
        else:
            included = [i for i in members if case_mentions[i].get("decision") == "include"]
            pool = included or members
            canonical_idx = min(pool)
            canonical = case_mention_ids[canonical_idx]
            methods = {match_method_by_pair.get((case_mention_ids[a], case_mention_ids[b])) or match_method_by_pair.get((case_mention_ids[b], case_mention_ids[a])) for a in members for b in members if a < b}
            methods.discard(None)
            method = "ambos" if len(methods) > 1 else (next(iter(methods)) if methods else "tipo_objeto_raw_exact")
        group_id = _stable_group_id(member_ids)
        for i in members:
            rows.append({
                "case_mention_id": case_mention_ids[i],
                "document_id": document_id,
                "duplicate_group_id": group_id,
                "canonical_case_mention_id": canonical,
                "group_size": group_size,
                "match_method": method,
                "decision_mixed_in_group": decision_mixed,
            })
    return rows


def main() -> int:
    if not CLASSIFICATIONS_PATH.exists():
        print(f"No existe {CLASSIFICATIONS_PATH}", file=sys.stderr)
        return 1
    actual_sha256 = hashlib.sha256(CLASSIFICATIONS_PATH.read_bytes()).hexdigest()
    if actual_sha256 != CLASSIFICATIONS_SHA256_EXPECTED:
        print(
            f"{CLASSIFICATIONS_PATH} cambio de contenido (sha256 actual={actual_sha256}, "
            f"esperado={CLASSIFICATIONS_SHA256_EXPECTED}). Abortando -- ver mismo guardrail en "
            "build_conflicts.py::load_v3_3_verified_links().",
            file=sys.stderr,
        )
        return 1

    all_rows: list[dict[str, Any]] = []
    for line in CLASSIFICATIONS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        all_rows.extend(compute_duplicate_groups(record))

    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        DROP TABLE IF EXISTS case_mention_duplicate_link;
        CREATE TABLE case_mention_duplicate_link (
            case_mention_id TEXT NOT NULL PRIMARY KEY REFERENCES case_mention(case_mention_id),
            document_id TEXT NOT NULL,
            duplicate_group_id TEXT NOT NULL,
            canonical_case_mention_id TEXT NOT NULL REFERENCES case_mention(case_mention_id),
            group_size INTEGER NOT NULL CHECK (group_size >= 1),
            match_method TEXT NOT NULL CHECK (match_method IN ('single', 'tipo_objeto_raw_exact', 'quote_substring', 'ambos')),
            decision_mixed_in_group INTEGER NOT NULL CHECK (decision_mixed_in_group IN (0, 1))
        );
        CREATE INDEX idx_cmdl_group ON case_mention_duplicate_link(duplicate_group_id);
        CREATE INDEX idx_cmdl_canonical ON case_mention_duplicate_link(canonical_case_mention_id);
        """
    )

    known_case_mention_ids = {row[0] for row in conn.execute("SELECT case_mention_id FROM case_mention")}
    n_skipped_unknown = 0
    inserted = 0
    for row in all_rows:
        if row["case_mention_id"] not in known_case_mention_ids:
            # documento en classifications.jsonl que no llego al warehouse
            # (ej. filtrado antes de build_entity_tables_v1.py) -- se omite,
            # nunca se inserta una fila que violaria la FK.
            n_skipped_unknown += 1
            continue
        conn.execute(
            "INSERT INTO case_mention_duplicate_link (case_mention_id, document_id, duplicate_group_id, "
            "canonical_case_mention_id, group_size, match_method, decision_mixed_in_group) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["case_mention_id"], row["document_id"], row["duplicate_group_id"],
                row["canonical_case_mention_id"], row["group_size"], row["match_method"], row["decision_mixed_in_group"],
            ),
        )
        inserted += 1
    conn.commit()

    n_case_mentions_total = len(all_rows)
    n_groups_total = len({r["duplicate_group_id"] for r in all_rows})
    dup_rows = [r for r in all_rows if r["group_size"] > 1]
    n_groups_duplicadas = len({r["duplicate_group_id"] for r in dup_rows})
    n_case_mentions_en_duplicados = len(dup_rows)
    n_documentos_afectados = len({r["document_id"] for r in dup_rows})
    n_grupos_decision_mixta = len({r["duplicate_group_id"] for r in dup_rows if r["decision_mixed_in_group"]})

    report = {
        "detector_version": DETECTOR_VERSION,
        "fuente": str(CLASSIFICATIONS_PATH.relative_to(PROJECT_ROOT)),
        "classifications_sha256": actual_sha256,
        "n_case_mentions_total": n_case_mentions_total,
        "n_grupos_total": n_groups_total,
        "n_grupos_duplicados_tamano_mayor_a_1": n_groups_duplicadas,
        "n_case_mentions_en_grupos_duplicados": n_case_mentions_en_duplicados,
        "n_documentos_afectados": n_documentos_afectados,
        "n_grupos_con_decision_mixta": n_grupos_decision_mixta,
        "n_filas_insertadas": inserted,
        "n_filas_omitidas_case_mention_no_en_warehouse": n_skipped_unknown,
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_check_issues": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        "warehouse_sha256": None,  # se completa abajo tras cerrar la conexion
    }
    conn.close()
    report["warehouse_sha256"] = hashlib.sha256(WAREHOUSE.read_bytes()).hexdigest()
    AUDIT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
