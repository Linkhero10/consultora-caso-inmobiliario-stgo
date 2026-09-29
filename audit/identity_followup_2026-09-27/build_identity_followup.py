#!/usr/bin/env python3
"""Build a deterministic, hash-pinned review of the 68 open project pairs."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BUNDLE = ROOT / "audit" / "identity_followup_2026-09-26" / "identity_review_bundle.json"
PREVIOUS = ROOT / "audit" / "identity_followup_2026-09-26" / "migration_review_original.json"
EXPECTED = {
    "bundle": "b1a793348667f34891dabfe5d305628e22bd3040e72a006e7f4eeedb28124dc5",
    "warehouse": "378bf7d7686d676dfb1e08cb5c141a2e5bea29b943ad0de6ef4f58d0900c09db",
    "fulltext_manifest": "4497b3856966f5d7fdd44a1dd5eb62ce36779b637923febaeab99ffdccd39b1a",
    "previous_review": "667159fe984484616b1d50499993ebc862af454729f81b16cdc94b5f0cb79499",
}
GENERIC_TOKENS = {
    "anteproyecto", "edificio", "edificios", "proyecto", "inmobiliario", "inmobiliaria",
    "iniciativa", "torre", "torres", "vivienda", "viviendas", "departamento",
    "departamentos", "loteo", "sector", "terreno", "terrenos", "plan", "maestro",
    "conjunto", "habitacional", "sociales", "social", "calle", "avenida", "numero",
    "ubicado", "ubicada", "ubicados", "ubicadas", "localizado", "localizada",
    "localizados", "localizadas", "situado", "situada", "situados", "situadas",
    "emplazado", "emplazada", "emplazados", "emplazadas", "instalado", "instalada",
    "instalados", "instaladas",
}

# class, confidence, canonical-side (only for same_identity), rationale, typed-relation suggestion.
# Frozen independently before the preliminary review is attached for comparison.
DECISIONS: list[tuple[str, str, str | None, str, str | None]] = [
    ("related_plan_or_instrument","alta",None,"Alameda 4499 es el predio; el anteproyecto que se quería ejecutar allí es una propuesta/instrumento distinto.","planned_on"),
    ("unresolved","media",None,"Alto Las Condes mezcla menciones de varios desarrollos; Cenco es una etiqueta corporativa. La evidencia no aísla qué activo representa cada ID.","possible_brand_or_asset_relation"),
    ("related_plan_or_instrument","alta",None,"El centro comercial complementario se conectaría al mall Alto Las Condes mediante un túnel; propuesta complementaria no es el activo existente.","complementary_to"),
    ("parent_component_phase","alta",None,"El campus USS es una unidad dentro de un ámbito Bellavista más amplio; no equivale al proyecto residencial de varias torres.","component_of"),
    ("unresolved","media",None,"Carlos Valdovinos aparece en un registro contaminado por otros proyectos; la mención SuKasa no prueba que el ID amplio sea ese proyecto.","possible_location_or_project_relation"),
    ("parent_component_phase","alta",None,"La casona patrimonial y la torre propuesta para reemplazarla son objetos/etapas diferentes aunque compartan predio.","replacement_proposal_for"),
    ("same_identity","alta","a","CNAC es el acrónimo explícito del Centro Nacional de Arte Contemporáneo de Cerrillos; nombre, recinto y función coinciden.","same_identity_alias"),
    ("unresolved","media",None,"Chaguay aparece dentro de un registro con otros proyectos precordilleranos. “Reserva La Dehesa, exChaguay” sugiere continuidad, pero no identifica una sola entidad del cluster.","possible_historical_rename"),
    ("parent_component_phase","alta",None,"El supermercado Líder está dentro de Ciudad de Los Valles; un local puntual no es el conjunto urbano completo.","located_within"),
    ("parent_component_phase","alta",None,"El loteo/sector industrial es parte del ámbito de Ciudad de Los Valles, no el desarrollo urbano mayor.","sector_of"),
    ("parent_component_phase","alta",None,"Ciudad del Niño es el sitio histórico; las 23 torres y viviendas son una iniciativa posterior sobre ese sitio.","proposed_on"),
    ("parent_component_phase","alta",None,"El megaproyecto privado de Maestra está en el predio Ciudad del Niño, pero no es la identidad del sitio histórico.","proposed_on"),
    ("related_plan_or_instrument","alta",None,"El Plan Urbano Habitacional es una intervención/programa posterior sobre el sitio, no un alias de Ciudad del Niño.","plan_for"),
    ("related_plan_or_instrument","alta",None,"Costanera Sur como parque/propuesta fluvial y la autopista son objetos y funciones distintos.","related_infrastructure"),
    ("same_identity","alta","a","Fuentes de Fundamenta usan Eco Egaña y Egaña Sustentable/Eco Egaña para la misma obra, titular y emplazamiento.","same_identity_alias"),
    ("same_identity","alta","a","La fuente de Corte Suprema identifica Egaña Sustentable de Fundamenta; La Tercera usa conjuntamente Egaña Sustentable/Eco Egaña para la misma obra. La mención en una nota de San Nicolás es contextual, no cambia la identidad del nombre.","same_identity_alias"),
    ("distinct_entities","alta",None,"Espacio Urbano El Rodeo está en Lo Barnechea; el Espacio Urbano de la otra fuente es de Estación Central. Cadena común no significa mismo activo.","same_operator_different_assets"),
    ("parent_component_phase","alta",None,"Las torres se proponen en terrenos del Estadio Santa Laura; el estadio y el proyecto inmobiliario son entidades distintas.","proposed_on"),
    ("same_identity","alta","a","TECHO describe Flor del Valle como proyecto de vivienda para 104 familias; la otra fuente lo nombra como condominio social Flor del Valle en Maipú.","same_identity_alias"),
    ("related_plan_or_instrument","alta",None,"El Sheraton es el activo existente; el anteproyecto posterior en sus terrenos es una propuesta diferente.","proposed_on"),
    ("related_plan_or_instrument","alta",None,"Las torres de 30/32 pisos tienen proyecto y permiso propios junto/al interior del perímetro del Sheraton; el hotel no es ese proyecto.","adjacent_or_on_hotel_land"),
    ("unresolved","baja",None,"Una fuente secundaria distingue Humedal San Luis y Humedal San Luis Norte, pero falta delimitación oficial para afirmar si son polígonos separados o subunidades.","possible_subarea_requires_official_polygon"),
    ("parent_component_phase","alta",None,"Lote B es una fracción/fase específica de la Villa Panamericana, no el conjunto completo.","component_of"),
    ("distinct_entities","alta",None,"Lote D-1 de La Reina y El Castillo en La Pintana tienen predio, comuna, titularidad y finalidad diferentes.",None),
    ("same_identity","alta","a","El Tribunal Ambiental usa Loteo de las 54 Casas y Proyecto de las 54 Casas para el mismo titular Miradores de La Dehesa SpA y la causa R-373-2022.","same_identity_alias"),
    ("same_identity","alta","a","Ambas menciones describen la Línea 3 de Metro de Santiago; tramo/etapa operativa no constituye otro activo.","same_identity_alias"),
    ("same_identity","alta","a","“Nueva Línea 3” nombra temporalmente la misma Línea 3 inaugurada en 2019, no una línea independiente.","same_identity_alias"),
    ("related_plan_or_instrument","media",None,"La Línea 7 completa y su extensión futura a Lo Barnechea son escalas/etapas de planificación relacionadas, no idénticas.","planned_extension_of"),
    ("parent_component_phase","alta",None,"Los talleres/cocheras de Renca son componente localizado de la Línea 7, no la línea completa.","component_of"),
    ("related_plan_or_instrument","alta",None,"Maestranza San Eugenio es el sitio; el proyecto de vivienda es una iniciativa asociada. Ukamau queda solo como mención descriptiva/actor, no alias.","housing_project_on_site"),
    ("unresolved","media",None,"El cluster Vital Apoquindo apunta a un desarrollo común, pero alterna conteos de 25/27 edificios y etiquetas competidoras; no fusionar una parte aisladamente.","possible_same_development_requires_cluster_resolution"),
    ("unresolved","media",None,"La mención coincide con el cluster Vital Apoquindo, pero las cifras 25/27 y los IDs competidores impiden cerrar este enlace por separado.","possible_same_development_requires_cluster_resolution"),
    ("same_identity","alta","a","NAP es el acrónimo explícito de Nueva Alameda Providencia; ambas fuentes describen la estrategia del mismo eje Alameda-Providencia.","same_identity_alias"),
    ("distinct_entities","alta",None,"El Plan Maestro Ciudad Parque Bicentenario es de Cerrillos; Parque Bicentenario sin calificativo refiere a otro parque en Vitacura.",None),
    ("distinct_entities","alta",None,"Ciudad Parque Bicentenario de Cerrillos y el proyecto habitacional de La Platina en La Pintana tienen ubicación y expediente diferentes.",None),
    ("related_plan_or_instrument","media",None,"El plan de reconstrucción es instrumento/intervención sobre el sector El Olivar; no es idéntico al territorio/conjunto.","plan_for_area"),
    ("same_identity","media_alta","a","La fuente local dice “Portal La Dehesa (Cencosud)” y el inventario corporativo “Cenco Portal La Dehesa”; corresponde al mismo centro comercial.","same_identity_alias"),
    ("parent_component_phase","alta",None,"La manzana/campus mixto USS incluye varios usos; el proyecto residencial DIB es un componente, no su alias.","component_of"),
    ("unresolved","media",None,"“Recreo” puede ser sector y el proyecto en calle Recreo un desarrollo puntual; falta rol/dirección o titular compartido que los conecte.","possible_location_or_project_relation"),
    ("unresolved","alta",None,"Reserva La Dehesa exChaguay y Reserva La Dehesa pueden compartir historia, pero falta vínculo verificable de predio, RCA, rol o titular; Chaguay además integra un cluster mixto.","possible_historical_rename_requires_parcel_link"),
    ("same_identity","alta","a","La sentencia del Segundo Tribunal Ambiental identifica San Nicolás en San Miguel; las otras referencias describen el mismo expediente, Delabase III y los efectos del fallo.","same_identity_alias"),
    ("distinct_entities","alta",None,"El Hotel Sheraton y las torres proyectadas junto a él son objetos distintos con permisos/controversias diferenciables.",None),
    ("same_identity","alta","a","Ambas fuentes identifican el local Líder San Francisco de Pudahuel; la segunda confirma operador Walmart e incendio del mismo local.","same_identity_alias"),
    ("same_identity","media_alta","a","El reportaje identifica tres torres Alameda de SuKsa y 5.600 departamentos; la segunda pieza reproduce literalmente esa descripción. Es una línea de evidencia reproducida, no corroboración independiente.","same_identity_alias"),
    ("distinct_entities","alta",None,"Ukamau es una organización/movimiento y Barrio Maestranza un conjunto habitacional. Ukamau solo queda como mención descriptiva/actor, nunca alias de proyecto.","organization_promotes_project"),
    ("parent_component_phase","media",None,"Block 73 es bloque/intervención dentro de Villa Olímpica, no el conjunto completo; la discrepancia del año de origen refuerza separar granularidad.","component_of"),
    ("parent_component_phase","alta",None,"Block 14 es componente específico de Villa San Luis, no el conjunto completo.","component_of"),
    ("unresolved","media",None,"El cluster Vital Apoquindo parece común, pero la fuente y los IDs mantienen discrepancias de alcance/conteo; no se propaga identidad desde otra pareja.","possible_same_development_requires_cluster_resolution"),
    ("same_identity","alta","a","Ambas fuentes hablan del Block 14 de Villa San Luis; el número y su condición de único bloque aún en pie identifican la misma unidad física.","same_identity_alias"),
    ("related_plan_or_instrument","alta",None,"El centro comercial complementario es una nueva propuesta conectada al mall existente, no el mall Alto Las Condes.","complementary_to"),
    ("unresolved","media",None,"Ambas menciones describen una colección de cuatro megaproyectos contiguos en Toro Mazzotte, no un proyecto individual; se conserva referencia agregada sin fusionar entidades singulares.","same_aggregate_reference_not_project_identity"),
    ("parent_component_phase","alta",None,"El edificio DIB es una torre/componente y Proyecto Bellavista el conjunto paraguas de tres torres; mismo titular/entorno no borra esa diferencia.","component_of"),
    ("same_identity","alta","a","La fuente dice expresamente “edificio UNCTAD III, hoy GAM”; ambos nombres refieren al mismo edificio histórico.","same_identity_alias"),
    ("parent_component_phase","alta",None,"La estación Copec es instalación puntual dentro de Ciudad de Los Valles, no el desarrollo urbano completo.","located_within"),
    ("distinct_entities","alta",None,"La iniciativa de 1.700 departamentos se ubica en Plaza Egaña; la otra mención refiere al topónimo/equipamiento comercial o estación.",None),
    ("unresolved","baja",None,"El acta COSOC y la mención Plaza Egaña no aportan dirección, titular, permiso ni atributos para identificarla con la iniciativa de 1.700 viviendas.","possible_alias_requires_project_identifier"),
    ("distinct_entities","media_alta",None,"Cencosud/Cenco administra malls distintos; las referencias apuntan a ubicaciones diferentes, no a un mismo activo.","same_operator_different_assets"),
    ("unresolved","media",None,"El proyecto detallado y el ID genérico parecen del cluster Vital Apoquindo, pero hay desacuerdo 25/27 y canonicals competidores; no merge aislado.","possible_same_development_requires_cluster_resolution"),
    ("same_identity","alta","a","Le Monde identifica el proyecto de Rotonda Atenas; Hogar de Cristo describe 85 viviendas sociales en el mismo sector y finalidad, el mismo desarrollo.","same_identity_alias"),
    ("same_identity","alta","b","Le Monde describe el proyecto de Rotonda Atenas; La Tercera identifica el condominio Rotonda Atenas y sus 85 unidades, la misma torre/proyecto.","same_identity_alias"),
    ("unresolved","media",None,"La columna de 2018 habla de viviendas sociales anunciadas en la Rotonda Atenas, pero no aporta dirección/unidades para probar que esa mención sea la torre construida después.","possible_announcement_to_built_project"),
    ("unresolved","baja",None,"Las fuentes difieren entre dos torres de 30 y una de 32, versus dos torres de 30 y 32; sin titular/ubicación coincidentes, no merge.","possible_same_development_requires_primary_project_record"),
    ("same_identity","alta","b","Pauta y La Tercera describen el desarrollo de DIB en Recoleta como tres torres de 19 pisos y la misma disputa en Dardignac.","same_identity_alias"),
    ("unresolved","media",None,"Bellavista puede referir al desarrollo DIB de Dardignac 44, pero el ID es amplio y el cluster incluye campus, edificio y torres de distinta granularidad; falta delimitarlo.","possible_same_identity_requires_cluster_resolution"),
    ("unresolved","media",None,"Ambos registros apuntan a Fundamenta en Ñuñoa, pero difieren entre tres residenciales más una oficina y cuatro torres de 32; falta identificación predial/RCA inequívoca.","possible_same_identity_requires_project_identifier"),
    ("distinct_entities","alta",None,"El proyecto SuKsa en calle Placilla y el de Santolaya/Conde del Maule son desarrollos distintos; Placilla funciona como homónimo/topónimo.",None),
    ("parent_component_phase","alta",None,"La segunda torre habitacional es componente/etapa del Conjunto Armónico Bellavista, no el proyecto paraguas.","component_of"),
    ("parent_component_phase","alta",None,"La segunda torre CAB es una torre específica del proyecto Bellavista de tres torres; se preserva relación parte–todo.","component_of"),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    for i, char in enumerate(text):
        expanded = unicodedata.normalize("NFKD", char).casefold()
        for item in expanded:
            if unicodedata.combining(item):
                continue
            if item.isalnum():
                chars.append(item)
                offsets.append((i, i + 1))
            elif chars and chars[-1] != " ":
                chars.append(" ")
                offsets.append((i, i + 1))
    return "".join(chars).strip(), offsets


def find_fragment(text: str, raw_mention: str, canonical_name: str) -> tuple[int, int, str, str]:
    normalized, offsets = normalize_map(text)
    for candidate in (raw_mention, canonical_name):
        wanted, _ = normalize_map(candidate)
        pos = normalized.find(wanted) if wanted else -1
        if pos >= 0:
            start, end = offsets[pos][0], offsets[pos + len(wanted) - 1][1]
            return start, end, text[start:end], "normalized_full_mention"
    candidates: list[tuple[tuple[int, int, int], int, int]] = []
    for candidate in (raw_mention, canonical_name):
        wanted, _ = normalize_map(candidate)
        tokens = wanted.split()
        for size in range(len(tokens), 0, -1):
            for offset in range(len(tokens) - size + 1):
                phrase = " ".join(tokens[offset:offset + size])
                pos = normalized.find(phrase)
                informative = [
                    token for token in tokens[offset:offset + size]
                    if len(token) >= (5 if size == 1 else 4) and token not in GENERIC_TOKENS
                ]
                if pos >= 0 and informative:
                    start, end = offsets[pos][0], offsets[pos + len(phrase) - 1][1]
                    score = (len(informative), size, len(phrase))
                    candidates.append((score, start, end))
    if candidates:
        _, start, end = max(candidates)
        return start, end, text[start:end], "normalized_literal_subphrase"
    raise ValueError(f"no literal name fragment: {raw_mention!r} / {canonical_name!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-project-root", type=Path, required=True,
                        help="raíz que contiene Fuentes/fulltext y data/warehouse.sqlite")
    args = parser.parse_args()
    source_root = args.source_project_root.resolve()
    fulltext = source_root / "Fuentes" / "fulltext"
    content_dir = fulltext / "content"
    manifest_path = fulltext / "fulltext_manifest.jsonl"
    warehouse_path = source_root / "data" / "warehouse.sqlite"
    bundle_raw = BUNDLE.read_bytes()
    manifest_raw = manifest_path.read_bytes()
    input_hashes = {
        "bundle": sha(bundle_raw),
        "warehouse": sha(warehouse_path.read_bytes()),
        "fulltext_manifest": sha(manifest_raw),
        "previous_review": sha(PREVIOUS.read_bytes()),
    }
    for name, actual in input_hashes.items():
        if actual != EXPECTED[name]:
            raise SystemExit(f"{name} SHA mismatch: {actual}; no output written")
    pairs = json.loads(bundle_raw.decode("utf-8"))["unresolved_pairs"]
    previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))["relation_review"]["unresolved_pairs"]
    if len(pairs) != 68 or len(previous) != 68 or len(DECISIONS) != 68:
        raise SystemExit("expected exactly 68 source pairs, prior rows and frozen decisions")
    manifest_by_url: dict[str, list[dict[str, Any]]] = {}
    for line in manifest_raw.decode("utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            manifest_by_url.setdefault(item.get("url"), []).append(item)

    old_class = {"alias":"same_identity", "parent-child-fase":"parent_component_phase",
                 "distintos":"distinct_entities", "irresoluble":"unresolved"}
    counts: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    adjudications: list[dict[str, Any]] = []
    for idx, (pair, prior, decision) in enumerate(zip(pairs, previous, DECISIONS, strict=True)):
        a, b = pair["project_a"], pair["project_b"]
        ids = [a["project_id"], b["project_id"]]
        if (prior["id_a"], prior["id_b"]) != tuple(ids):
            raise SystemExit(f"old review identity mismatch at pair index {idx}")
        identity_class, confidence, canonical_side, rationale, relation = decision
        action = "merge_case" if identity_class == "same_identity" else "no_new_merge"
        canonical = ids[0 if canonical_side == "a" else 1] if canonical_side else None
        evidence: list[dict[str, Any]] = []
        literal_evidence_sides: set[str] = set()
        for side, project in (("a", a), ("b", b)):
            examples = project.get("source_examples") or []
            if not examples:
                raise SystemExit(f"pair {pair['pair_id']} side {side} has no evidence URLs")
            for n, example in enumerate(examples):
                url = example.get("url")
                records = manifest_by_url.get(url, [])
                if not records:
                    raise SystemExit(f"source URL missing from manifest: {url}")
                located = None
                for manifest_record in records:
                    candidate = content_dir / Path(str(manifest_record.get("content_file") or "")).name
                    if not candidate.is_file():
                        continue
                    content_bytes = candidate.read_bytes()
                    try:
                        record = json.loads(content_bytes.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if record.get("url") == url and isinstance(record.get("text"), str):
                        located = (candidate, content_bytes, record)
                        break
                if located is None:
                    raise SystemExit(f"fulltext source missing or invalid: {url}")
                path, content_bytes, record = located
                text = record["text"]
                text_hash = sha(text.encode("utf-8"))
                if text_hash != example.get("document_id"):
                    raise SystemExit(f"document_id/text hash mismatch for {url}")
                ref = {
                    "evidence_ref_id": f"{pair['pair_id']}:{side}:{n}",
                    "side": side,
                    "project_id": project["project_id"],
                    "project_name": project["canonical_name"],
                    "raw_project_mention": example.get("raw_project_mention"),
                    "document_id": example["document_id"],
                    "title": example.get("title"),
                    "url": url,
                    "linked_case_mention_id": example.get("linked_case_mention_id"),
                    "linked_case_decision": example.get("linked_case_decision"),
                    "linked_case_comuna": example.get("linked_case_comuna"),
                    "content_file": f"Fuentes/fulltext/content/{path.name}",
                    "source_text_sha256": text_hash,
                    "content_record_sha256": sha(content_bytes),
                }
                try:
                    start, end, fragment, match_method = find_fragment(
                        text, str(example.get("raw_project_mention") or ""), project["canonical_name"]
                    )
                except ValueError:
                    ref.update({
                        "evidence_status": "no_discriminative_literal_anchor",
                        "quote": None,
                        "matched_fragment": None,
                        "match_method": None,
                        "evidence_role": "source_record_checked_but_not_used_as_identity_evidence",
                    })
                else:
                    # Keep only the minimum literal anchor in the public
                    # artifact. Fulltext is excluded from the repository;
                    # offsets and hashes preserve local reproducibility
                    # without republishing long copyrighted passages.
                    quote = fragment
                    ref.update({
                        "evidence_status": "literal_anchor_verified",
                        "quote": quote,
                        "matched_fragment": fragment,
                        "match_method": match_method,
                        "offset_start": start,
                        "offset_end": end,
                        "evidence_role": "minimum_literal_anchor_not_identity_proof_by_itself",
                    })
                    methods[match_method] += 1
                    literal_evidence_sides.add(side)
                evidence.append(ref)
        if literal_evidence_sides != {"a", "b"} and identity_class != "unresolved":
            raise SystemExit(f"non-unresolved pair {pair['pair_id']} lacks a distinctive literal anchor on one side")
        counts[identity_class] += 1
        previous_class = old_class.get(prior.get("relation"))
        alignment = "coincide" if previous_class == identity_class else "difiere_o_es_mas_especifica"
        adjudications.append({
            "pair_id": pair["pair_id"],
            "project_ids": ids,
            "project_names": {a["project_id"]: a["canonical_name"], b["project_id"]: b["canonical_name"]},
            "identity_class": identity_class,
            "resolver_action": action,
            "canonical_project_id": canonical,
            "confidence": confidence,
            "rationale": rationale,
            "typed_relation_candidate": relation,
            "typed_relation_persisted": False,
            "production_promoted": False,
            "case_mention_eligibility_overridden": False,
            "preliminary_review_comparison": {
                "relation": prior.get("relation"),
                "evidence_text": prior.get("evidence"),
                "confidence": prior.get("confidence"),
                "urls_count": len(prior.get("urls") or []),
                "external_evidence_count": len(prior.get("external_evidence") or []),
                "alignment": alignment,
                "note": "attached only after freezing this source-first decision; not used as evidence",
            },
            "source_evidence": evidence,
        })

    old_alignment = sum(x["preliminary_review_comparison"]["alignment"] == "coincide" for x in adjudications)
    source_ref_count = sum(len(x["source_evidence"]) for x in adjudications)
    literal_quote_count = sum(
        ref["evidence_status"] == "literal_anchor_verified"
        for item in adjudications for ref in item["source_evidence"]
    )
    unanchored_count = source_ref_count - literal_quote_count
    quote_words_by_url: Counter[str] = Counter()
    for item in adjudications:
        for ref in item["source_evidence"]:
            quote = ref.get("quote")
            if isinstance(quote, str) and quote:
                quote_words_by_url[str(ref["url"])] += len(quote.split())
    total_quote_words = sum(quote_words_by_url.values())
    max_quote_words_per_url = max(quote_words_by_url.values(), default=0)
    artifact = {
        "schema_version": "project_identity_adjudications_v1",
        "artifact_id": "project_identity_adjudications_2026-09-27_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "review_method": {
            "scope": "68 exact project_id pairs in the frozen bundle",
            "source_first_decisions_frozen_before_comparison": True,
            "source_basis": "local fulltext source records, exact URL/document/text hashes and literal excerpts; read-only multi-agent case review synthesized by Codex",
            "quote_policy": "publish only the minimum literal anchor; do not copy surrounding article passages",
            "external_urls_live_checked": False,
            "identity_does_not_change_eligibility": True,
            "case_mention_include_exclude_uncertain_preserved": True,
            "project_ids_deleted_or_rewritten": 0,
            "user_constraints": [
                "preserve unresolved historical references without forced aliases",
                "keep full publication blocked while topology-affecting cases remain unresolved",
                "UKAMAU remains a descriptive mention/actor, not a project alias",
            ],
        },
        "source_bundle_sha256": input_hashes["bundle"],
        "source_warehouse_sha256": input_hashes["warehouse"],
        "source_fulltext_manifest_sha256": input_hashes["fulltext_manifest"],
        "source_preliminary_review_sha256": input_hashes["previous_review"],
        "adjudications": adjudications,
    }
    out_json = HERE / "identity_adjudications_v1.json"
    out_report = HERE / "identity_review_report.md"
    out_simulation = HERE / "identity_topology_simulation.json"
    json_bytes = (json.dumps(artifact, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    out_json.write_bytes(json_bytes)

    # Exercise the exact production resolver purely in memory against a
    # read-only connection. This is a simulation, not a production rebuild.
    sys.path.insert(0, str(ROOT / "src"))
    import resolve_project_review as resolver

    warehouse_uri = f"file:{warehouse_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(warehouse_uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        queue_rows = [tuple(row) for row in conn.execute(
            "SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b "
            "FROM project_review_queue ORDER BY rowid"
        )]
        projects = dict(conn.execute("SELECT project_id, canonical_name FROM project ORDER BY project_id"))
        partitions = dict(conn.execute(
            "SELECT project_id, homonym_partition FROM project WHERE homonym_partition IS NOT NULL"
        ))
        baseline, baseline_sha = resolver.load_case_baseline(projects)
        loaded = resolver.load_project_identity_adjudications(out_json, BUNDLE)
        resolver.validate_project_identity_adjudication_scope(projects, queue_rows, loaded)
        plan = resolver.resolve_case_components(
            projects, queue_rows, partitions, baseline, resolver.classify_with_provenance,
            pair_classifier=lambda pa, na, pb, nb: resolver.classify_project_pair_with_adjudications(
                pa, na, pb, nb, loaded
            ),
        )
        evidence_validation = resolver.validate_project_identity_adjudication_evidence(loaded, source_root)
        topology_validation = resolver.validate_project_identity_adjudication_topology(
            plan.project_to_case, baseline, loaded
        )
        queue_decisions = Counter(
            "merged" if decision[0] is True else "kept_separate" if decision[0] is False else "needs_human_review"
            for decision in plan.row_decisions.values()
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    finally:
        conn.close()
    if sha(warehouse_path.read_bytes()) != input_hashes["warehouse"]:
        raise SystemExit("warehouse changed during read-only simulation; refusing to report success")
    simulation = {
        "schema_version": "project_identity_topology_simulation_v1",
        "artifact_id": "identity_topology_simulation_2026-09-27",
        "identity_adjudications_sha256": sha(json_bytes),
        "warehouse_sha256_before_after": input_hashes["warehouse"],
        "sqlite_open_mode": "read-only",
        "sqlite_modified": False,
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_key_errors),
        "projects": len(projects),
        "queue_rows": len(queue_rows),
        "baseline_project_count": len(baseline),
        "baseline_mapping_sha256": baseline_sha,
        "evidence_references_validated": evidence_validation["valid_references"],
        "verified_literal_quotes": evidence_validation["verified_literal_quotes"],
        "unanchored_references": evidence_validation["unanchored_references"],
        "topology_validation": topology_validation,
        "queue_decisions_simulated": dict(sorted(queue_decisions.items())),
        "case_groups_before": len(set(baseline.values())),
        "case_groups_after": len(set(plan.project_to_case.values())),
        "homonym_vetoes": plan.homonym_vetoes,
        "production_promoted": False,
    }
    if integrity != "ok" or foreign_key_errors:
        raise SystemExit("read-only SQLite integrity checks failed")
    simulation_bytes = (json.dumps(simulation, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    out_simulation.write_bytes(simulation_bytes)

    merges = [x for x in adjudications if x["resolver_action"] == "merge_case"]
    unresolved = [x for x in adjudications if x["identity_class"] == "unresolved"]
    differences = [x for x in adjudications if x["preliminary_review_comparison"]["alignment"] != "coincide"]
    lines = [
        "# Adjudicación source-first de las 68 parejas de identidad — 2026-09-27", "",
        "## Alcance, método y límites", "",
        "Se revisaron los 68 pares del bundle congelado por `project_id`, usando los fulltexts locales adjuntos a ambos lados. La tabla de recomendaciones preliminares se incorporó **después** de congelar la primera pasada; sus 68 filas no tenían URLs ni evidencia externa y no se usaron como fuente.",
        f"Se verificaron **{source_ref_count}** referencias locales por URL y hashes. **{literal_quote_count}** tienen ancla literal discriminante; **{unanchored_count}** se conservaron con hashes sin cita si no apareció un ancla útil. El JSON publica solo la frase mínima —{total_quote_words} palabras en {len(quote_words_by_url)} fuentes, máximo {max_quote_words_per_url} por URL—, no pasajes circundantes. El contexto completo se puede volver a comprobar localmente con URL, hashes y offsets. Un ancla prueba aparición literal, no identidad entre IDs. Métodos: `{dict(methods)}`.",
        "No se revalidó en vivo el estado de los sitios externos; los registros del corpus local y sus hashes son los objetos auditados. El cruce de identidad no cambia la elegibilidad `include/exclude/uncertain`, no elimina ni reescribe `project_id` y no modifica SQLite.",
        "Todas las filas conservan `production_promoted=false`; no se reconstruyó el warehouse. Las relaciones tipadas son sugerencias, no se persistieron. El gate de publicación completa sigue bloqueado por los asuntos históricos/topológicos pendientes.",
        f"Simulación del resolver real (SQLite read-only): {simulation['projects']} proyectos, {simulation['queue_rows']} filas de cola; {simulation['evidence_references_validated']} referencias verificadas ({simulation['verified_literal_quotes']} citas literales, {simulation['unanchored_references']} sin ancla); {simulation['topology_validation']['transitive_reconnections']} reconexiones transitivas; grupos case_id {simulation['case_groups_before']}→{simulation['case_groups_after']}; integridad `{integrity}`, FK errors={len(foreign_key_errors)}. Detalle en `identity_topology_simulation.json`.",
        "", "## Distribución", "", "| Clase | N |", "|---|---:|",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"| `{key}` | {value} |")
    lines += [f"| **Total** | **{len(adjudications)}** |", "",
              f"Recomendación preliminar alineada: **{old_alignment}/68**. Diferente o más específica: **{len(differences)}/68**. Ver comparación individual y evidencia en el JSON.",
              "", "## Identidades propuestas para merge exacto", "", "| pair_id | canonical_project_id |", "|---|---|"]
    for x in merges:
        lines.append(f"| `{x['pair_id']}` | `{x['canonical_project_id']}` |")
    lines += ["", "## Parejas conservadas como unresolved", "",
              "No se completaron por obligación numérica; requieren más evidencia y quedan con `no_new_merge`.", ""]
    for x in unresolved:
        ids = x["project_ids"]
        names = x["project_names"]
        lines.append(f"- `{x['pair_id']}` — {names[ids[0]]} ↔ {names[ids[1]]}: {x['rationale']}")
    lines += ["", "## Decisiones de límite", "",
              "- Ukamau se conserva como organización/mención descriptiva; no se fusiona con Barrio Maestranza ni con un proyecto habitacional.",
              "- Los grupos Vital Apoquindo y Bellavista se mantienen parcialmente abiertos para evitar propagación transitiva mientras haya discrepancias de alcance/granularidad.",
              "- Los pares de componente, predio, plan, tienda, torre o infraestructura quedan separados; las relaciones sugeridas no se guardan hasta definir el contrato tipado.",
              "- El artefacto no promueve ni aplica decisiones. Una reconstrucción posterior debe pasar sus gates de evidencia/topología y el gate histórico de publicación.", ""]
    out_report.write_text("\n".join(lines), encoding="utf-8")
    report_bytes = out_report.read_bytes()
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    package = {
        "schema_version": "identity_followup_build_manifest_v1",
        "artifact_id": "identity_followup_2026-09-27_build_manifest",
        "repository_head_at_build": commit,
        "source_hashes": input_hashes,
        "generator_sha256": sha(Path(__file__).read_bytes()),
        "source_project_root_stored": False,
        "counts": {"pairs": 68, "source_references_checked": source_ref_count, "literal_quotes_verified": literal_quote_count, "references_without_discriminative_anchor": unanchored_count, "minimum_anchor_quote_words_total": total_quote_words, "sources_with_anchor_quotes": len(quote_words_by_url), "maximum_anchor_quote_words_per_source": max_quote_words_per_url, "merge_case_candidates": len(merges), "unresolved": len(unresolved), "preliminary_aligned": old_alignment, "preliminary_different_or_more_specific": len(differences)},
        "class_counts": dict(sorted(counts.items())),
        "files": {
            out_json.name: {"sha256": sha(json_bytes), "bytes": len(json_bytes)},
            out_report.name: {"sha256": sha(report_bytes), "bytes": len(report_bytes)},
            out_simulation.name: {"sha256": sha(simulation_bytes), "bytes": len(simulation_bytes)},
        },
        "release_boundary": {"sqlite_modified": False, "project_ids_deleted_or_rewritten": 0, "eligibility_overrides": 0, "production_promoted": False, "full_release_gate": "blocked_pending_historical_and_topology_resolution"},
    }
    (HERE / "package_manifest.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pairs": 68, "source_references": source_ref_count, "class_counts": dict(sorted(counts.items())), "merge_case_candidates": len(merges), "unresolved": len(unresolved), "preliminary_aligned": old_alignment, "preliminary_different_or_more_specific": len(differences), "simulation": simulation, "identity_json_sha256": sha(json_bytes), "report_sha256": sha(report_bytes)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
