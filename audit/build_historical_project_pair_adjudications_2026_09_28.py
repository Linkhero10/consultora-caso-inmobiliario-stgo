"""Create the exact-project-ID adjudication for 26 legacy pairs plus CAB row 209.

Read-only inputs: the source warehouse/fulltext. Output: a pinned JSON artifact.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, sqlite3
from pathlib import Path

# rowid, id_a, id_b, identity_class, canonical_id, confidence, rationale,
# typed relation candidate, preferred source document A, preferred source B.
ROWS = [
(8,"e64cb33f7422d75ed07769f9","13720e94b943ba21eff3a93f","same_identity","e64cb33f7422d75ed07769f9","high","Misma iniciativa de renovación del eje Alameda-Providencia; el primer ID conserva el nombre de la iniciativa y el segundo la denomina por su corredor.","same_identity_alias","1a75b79973e4560e188274cba95d2b0aac4443a7d90b0424a86b002da1d0111e","80ec1f6cf060d5d09cbe156af1bbf7443a5049e82e18a2312266fe0c0bacc7bf"),
(47,"a65856c564c7d8db3a296cdc","13720e94b943ba21eff3a93f","same_identity","a65856c564c7d8db3a296cdc","high","La fuente define explícitamente NAP como Nueva Alameda Providencia; la contraparte describe la misma iniciativa y corredor.","same_identity_alias","c4f4c30018eeca10587a52b88020b34b43cf8f928786b8f7618e4b8b97dbb1fa","80ec1f6cf060d5d09cbe156af1bbf7443a5049e82e18a2312266fe0c0bacc7bf"),
(61,"14537e43f763c717791c5b90","00a49b2fac5c7887f0c4f628","unresolved",None,"medium","Una fuente identifica un edificio PAZ Corp. en Santa Petronila; la otra describe una megatorre de 30 pisos y 1.053 departamentos. El material no prueba que sean el mismo inmueble y la calle tiene más de un proyecto. Sin permiso o predio común, no se fusiona ni se afirma diferencia.","possible_same_building_requires_parcel_or_permit_link","76d46c4f3b20fb21668670dbb467288657ba88a2e5d21e9d84190a90b05d53ec","55dae700063cebc780630f0ed7e15fb33ee8a59bfb8c84c1577739c937265e6e"),
(67,"aef943251b1be918370edf5d","292f9bb1df57d22136828aac","parent_component_phase",None,"high","Villa Olímpica es el conjunto; Block 73 en Los Jazmines 1506 es una unidad física específica con trayectoria propia, no alias del conjunto.","component_of","00bf0ba8d43fd72891bfa2ea1aff46f0cebb5e05fa4fbd84b7c7864e58606b0a","1f120a939cb5b7d109238c9e7fe98212957bbe7fd36020f072d0da9b49ea9cb3"),
(69,"ea5d8ac70a737f8dbcdcb939","673b9377522a40c8d769dc34","parent_component_phase",None,"high","Lo Aguirre es la instalación existente; su ampliación es una intervención posterior con autorización y controversia propias. Relacionados no significa misma identidad.","expansion_of","f3c06a7485b8d3eeb2e2cbe3e276a05bc903740283417a24b33f7d67893d4085","7a8cb892d9050b3f145ee59005cc3b7e9e5ec66366dbb237530ea067bf060059"),
(79,"e8fd7b147a07358cd8e129e9","d18b439c5be31864ad8f1e21","unresolved",None,"medium","Una fuente usa Costanera Center para el activo santiaguino y la otra llama a Cenco Costanera su denominación anterior; pero el ID fuente mezcla menciones del activo con referencias a iniciativas Cencosud. No se asegura que la relación sea exclusivamente alias y no una mención de proyecto/expansión; queda pendiente hasta separar menciones.","possible_same_asset_or_mixed_project_cluster","4ff897052e01ad8510fda07459b38cdfa5b1bdcd43e453c751ad2b1443b9ff83","415ddc301212a5f3478237b33d46344a30ccc9d8de8ac6d6a4bebebd0e5c8200"),
(86,"06cac2c4b094ac1ed38ac40b","7e66e9745e63138bdbdf2c76","same_identity","06cac2c4b094ac1ed38ac40b","high","Misma iniciativa de viviendas sociales de Rotonda Atenas en Las Condes y misma oposición vecinal; coinciden objeto, lugar y controversia.","same_identity_alias","3ce1ba0d8539eadeaf05abb82dcdb4608b73a14e1264e1dafa7aecb6b3f7396f","2df46157fb12b6e884595e61a04f87658b5c27665ba58f73125bed8c3e13a0e6"),
(87,"06cac2c4b094ac1ed38ac40b","2e8579a96f08a3329f336707","distinct_entities",None,"high","La primera es la iniciativa histórica de integración en Rotonda Atenas; la segunda es el proyecto social de 2023 próximo a Parque Arauco/Cerro Colorado. Etiqueta geográfica amplia compartida no demuestra identidad.","same_area_different_project","3ce1ba0d8539eadeaf05abb82dcdb4608b73a14e1264e1dafa7aecb6b3f7396f","e13ebc73d5ad05757b72964d91d52766915808d6d1cb5d906f8a10557829711e"),
(89,"06cac2c4b094ac1ed38ac40b","623ed9e19dc274ad6b3ae8dd","same_identity","06cac2c4b094ac1ed38ac40b","high","Ambas fuentes describen el desarrollo social de Rotonda Atenas, incluidas las 85 unidades y la controversia de integración.","same_identity_alias","3ce1ba0d8539eadeaf05abb82dcdb4608b73a14e1264e1dafa7aecb6b3f7396f","c4648a2fede26afe94e74edcaea515bbb8822b998e7356838a8ac05f8b337a83"),
(98,"3ce6d0d030381374a3c026f7","7805069a696198e3d8e2b964","related_plan_or_instrument",None,"high","Ciudad Parque Bicentenario es el desarrollo urbano de Cerrillos; el Plan Maestro es un instrumento que lo ordena. Relacionados, no aliases.","plan_for","e0b6c752c9d0070e77b69e77d5a84f0b8a0694c7eda40fe2eb47fcca20b85851","4d8b75d5425a487ad7f7ae6464cd5c03c3b151bb4913f0567a2343d9b027fc33"),
(101,"bc91dff975e756ec1d964ec3","6802eb97ec3f72e304b12592","related_plan_or_instrument",None,"high","Proyecto La Platina refiere al proceso del predio; Seccional La Platina es un instrumento de planificación con función propia. Compartir territorio no los hace la misma entidad.","plan_for","e1a87347d0ba6ad709467fd3515b118e3fe2b5c986807b7de8c1730a7ed42866","a4cd2d245e49890d11a883828e3bcf229dd0a1c8f77a380b6a1d69d3524c2340"),
(103,"6bf348ffa4baa30fed8272e9","adfb19558de9f772aad491a5","distinct_entities",None,"high","Moneda Bicentenario está en el centro de Santiago; Proyecto Bicentenario refiere al desarrollo habitacional de La Platina en La Pintana. Ubicación y objeto difieren.","homonymous_distinct_entities","f5906b8c14e8d3c3534b3691660e15a3e3e70bb1a1cba38b637334b1e00d74a4","a4cd2d245e49890d11a883828e3bcf229dd0a1c8f77a380b6a1d69d3524c2340"),
(115,"204b2c71ae4be039388f2703","044c20f0e13a1bae6c68978c","same_identity","044c20f0e13a1bae6c68978c","high","Edificio de 38 pisos en General Amengual 480 corresponde al Edificio General Amengual del mismo corredor/dirección; el 480 es numeración predial, no fase.","same_identity_alias","b3285315e92b4c7b946eaf2aa6c1a59e51f62414ffd5ef7b5463652b7a6e169b","b83e45226eb0060d383463a61625896bc60bbfcd8c75e176e08c42a133774d5f"),
(173,"44598b79177f378212cf10e4","20559eb9ca09be77598a685e","related_plan_or_instrument",None,"high","Bosque Panul es el territorio/ecosistema; la subdivisión para urbanizarlo es una intervención dentro del territorio. Se relacionan, no son la misma entidad.","proposed_on","bfde5aff348348b1f0e732ca5d32faad6e65e96b47700fad992b24b01ca04cbf","c141978e8ce2dfd6140f0eb2bfa7be67ddf5facce254afd2561590933f5fe266"),
(177,"708353b6e07226824317b02d","a71127327712c32eb584b209","same_identity","a71127327712c32eb584b209","high","Las fuentes describen el proyecto Nueva El Golf de Peñalolén y la misma suspensión/controversia. Inmobiliaria identifica al titular, no otro proyecto en este par.","same_identity_alias","b2c7eb3570a011f9ddec399b957b1d5e0541052c69426fb26db4901947cb1ff5","38f2aceddabfb351ce03d11617cd2bf8fdf00b26ecf9cf7ad862aa7bb877afaf"),
(182,"5fc1929629635e3c71603bda","7a4072da49c6decfd6df3f01","distinct_entities",None,"high","El mall atribuido al Fondo Cimenta en Bellavista no es el desarrollo residencial de DIB. Bellavista es topónimo compartido; difieren titular y tipo de desarrollo.","homonymous_distinct_entities","aca5f3a115e4e590d1b004005544952791afb942548aee08273c503399a360ab","a0b1574b06453ad2f13f71f27a3cc4f6b93f23e9a93d6995e2115247caa9d3f0"),
(197,"6adefbac34725abb9c46b40c","b5da5dadfd479fed61b36726","same_identity","6adefbac34725abb9c46b40c","high","Proyecto Sierra Bella corresponde a la adquisición/transformación de la ex clínica por la Municipalidad de Santiago; la fuente distingue ese caso de otro paño en Las Condes.","same_identity_alias","0fd4d36006981af6b409e05703a60493fd6ddd63b47aad6c5a430123d0b56023","a67c3d4db0900541c2e12748ed9b6dd2b210a4bc8dcbeee7594dca08cb03ebec"),
(200,"17f3b690577f9fd996b9c4bd","69daf84c98731696f403b9da","parent_component_phase",None,"high","La laguna artificial es una obra propuesta dentro del Parque Padre Hurtado; el parque es el activo territorial mayor. No se colapsa la obra en el parque.","component_of","4fcfcc8a52b64677db91bc53e43a6f3004af221776a5734bd0a442b17c31fcb8","da7e89cccde1f06e5a2ba86948bd746e926a49bd8ff16d2a91db2490c4ea4a16"),
(209,"6787fa6cc302091a8ea27645","a812c5dd74897808e543d008","parent_component_phase",None,"high","Dardignac 44 es la segunda torre habitacional del Conjunto Armónico Bellavista; la torre es componente, no alias del conjunto.","component_of","6cd3486f60f58854776ee05893fd08cb43a117a6cd200c1c2594acbc658e81dd","a381f0fbb2ff994f7d4752a0091693889e37c479625d5819b953de43c8845fe2"),
(215,"a812c5dd74897808e543d008","a7582eea55bbe9571084de75","parent_component_phase",None,"high","La fuente llama a la torre una de las tres del conjunto. Una torre con controversia propia no es alias del conjunto completo.","component_of","7bebe40d8f6e53e560dae50e5d6f4b8c64aa1801d4f06c07aad125ca52058271","7b92ddd66f08f49ad68e8c7cd965edc804064f5bdd136d122569b5da751a5184"),
(221,"8bd124387f08d8b887d706ca","13720e94b943ba21eff3a93f","same_identity","8bd124387f08d8b887d706ca","high","Mismo proyecto de recuperación/remodelación del eje Alameda-Providencia y mismo corredor desde Estación Central a Providencia.","same_identity_alias","fb61a0bd62fe3358b6ec432fd00d6e9862771ec5087c2a12d9dc55e4eb01f9ca","80ec1f6cf060d5d09cbe156af1bbf7443a5049e82e18a2312266fe0c0bacc7bf"),
(228,"79bd439d4af500f5546d2af6","7fd73e29b6a6ccea8a40eb76","same_identity","79bd439d4af500f5546d2af6","high","Las fuentes identifican el conjunto Barrio Maestranza/Maestranza Ukamau, 424 familias, entre Santiago Watt y Exposición. Ukamau sigue como actor/mención descriptiva: no se crea project_id para la organización ni se fusiona la organización con el conjunto.","same_identity_alias","3481c3fabb032ada5a77f04a5921ce73493067a65a52f6fec0cd7f7a8312f8b8","63ea00793d12cb9496497f5f265dfef10dc306d5d0bf341bd9600dae77d42b88"),
(232,"5f4d9617fe0e8aed5c2a5413","07f2e2ce4fe660358aba5d28","parent_component_phase",None,"high","La ampliación es intervención con alcance/autorización propios; Mall Sport es el centro existente. No son la misma unidad analítica.","expansion_of","100557d4b03bbf7288bbfd09e11d08d8b08bb2acf8bf3211c23dc8c5b9276be1","b3a2fae1a87f3d2685503be60364ab7277ce38263b629a866ea57eec12033268"),
(234,"993cffe9909379cb2878c651","d836b79f2a3c8c188c918018","same_identity","d836b79f2a3c8c188c918018","high","Vitacura identifica el proyecto Cenco Malls; Ex-Ante individualiza el centro comercial en Vitacura/terreno Holy Cross y el desistimiento tras el trámite municipal. Sitio e iniciativa coinciden.","same_identity_alias","1bd916626bb14a82b5dc9b2cc55a51684e77550c425bdba1c35564f4f48dee56","697c6c830ccd231f467c40580ecb9646100262280141b4ec3b4a609407f1899b"),
(246,"a7582eea55bbe9571084de75","7a4072da49c6decfd6df3f01","parent_component_phase",None,"high","La torre del Conjunto Armónico Bellavista no es el proyecto paraguas de tres torres DIB; titular/barrio común no elimina la diferencia de granularidad.","component_of","7b92ddd66f08f49ad68e8c7cd965edc804064f5bdd136d122569b5da751a5184","a0b1574b06453ad2f13f71f27a3cc4f6b93f23e9a93d6995e2115247caa9d3f0"),
(247,"a7582eea55bbe9571084de75","3c3c53234cbce2dea5c38efc","parent_component_phase",None,"high","BioBioChile vincula una torre al conjunto; T13 usa Proyecto Armónico Bellavista para Dardignac 44. No hay base para alias torre↔conjunto ni cierre transitivo entre paraguas.","component_of_or_project_name_variant_unresolved","7b92ddd66f08f49ad68e8c7cd965edc804064f5bdd136d122569b5da751a5184","d9deccc9edb441bfdd91cf90a108dbcb88416ac2a8325be68ad8500520c94e74"),
(250,"f8ddadd1807ecdd4188c0847","69daf84c98731696f403b9da","related_plan_or_instrument",None,"high","El plan de mejoramiento/laguna es intervención sobre el Parque Padre Hurtado; el parque es activo territorial mayor, no el mismo proyecto.","plan_for","b11119c57a8d14d9e4db1c4f0804596f3904303bdc163320acc99be72332c372","da7e89cccde1f06e5a2ba86948bd746e926a49bd8ff16d2a91db2490c4ea4a16"),
]

def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()

def resolve_source_paths(source_root: Path, warehouse: Path | None = None, fulltext_root: Path | None = None) -> dict[str, Path]:
    """Resolve a warehouse snapshot and its fulltext evidence independently.

    Keeping the two roots separate is useful for isolated Git worktrees, where
    the LFS warehouse is checked in but the large, local fulltext corpus is not.
    """
    source_root = source_root.resolve()
    return {
        "warehouse": warehouse.resolve() if warehouse else source_root / "data" / "warehouse.sqlite",
        "fulltext_root": fulltext_root.resolve() if fulltext_root else source_root / "Fuentes" / "fulltext",
    }

def find_fragment(repo_root: Path):
    p=repo_root/"audit/identity_followup_2026-09-27/build_identity_followup.py"
    spec=importlib.util.spec_from_file_location("identity_followup_builder",p)
    if not spec or not spec.loader: raise RuntimeError(f"cannot load anchor helper {p}")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod.find_fragment

def build(source_root: Path, repo_root: Path, warehouse: Path | None = None, fulltext_root: Path | None = None) -> dict:
    paths=resolve_source_paths(source_root, warehouse=warehouse, fulltext_root=fulltext_root)
    db=paths["warehouse"]
    mp=paths["fulltext_root"] / "fulltext_manifest.jsonl"; content=paths["fulltext_root"] / "content"
    if not db.is_file() or not mp.is_file() or not content.is_dir(): raise SystemExit("source root lacks warehouse/fulltext")
    manifest_raw=mp.read_bytes(); manifest={}
    for line in manifest_raw.decode("utf-8").splitlines():
        if line.strip():
            x=json.loads(line); manifest.setdefault(x.get("url"),[]).append(x)
    conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
    projects={r["project_id"]:dict(r) for r in conn.execute("select project_id,canonical_name from project")}
    finder=find_fragment(repo_root); entries=[]; seen=set()
    for rowid, aid, bid, cls, canonical, confidence, rationale, relation, doc_a, doc_b in ROWS:
        ids=tuple(sorted((aid,bid)))
        if ids in seen: raise SystemExit(f"duplicate IDs {ids}")
        seen.add(ids)
        q=conn.execute("select rowid,project_id_a,canonical_name_a,project_id_b,canonical_name_b from project_review_queue where rowid=?",(rowid,)).fetchone()
        if not q or tuple(sorted((q["project_id_a"],q["project_id_b"])))!=ids: raise SystemExit(f"queue pair changed at {rowid}")
        names={pid:projects[pid]["canonical_name"] for pid in ids}
        if {names[q["project_id_a"]],names[q["project_id_b"]]}!={q["canonical_name_a"],q["canonical_name_b"]}: raise SystemExit(f"queue names changed at {rowid}")
        pair_id="historical_pair:"+sha("\0".join(ids).encode())[:20]
        refs=[]
        for side,pid,docid in (("a",aid,doc_a),("b",bid,doc_b)):
            linked=conn.execute("select pm.document_id,d.url,pm.raw_nombre_proyecto from project_mention_resolved pm join document d using(document_id) where pm.project_id=? and pm.document_id=?",(pid,docid)).fetchone()
            if not linked: raise SystemExit(f"preferred source {docid} not linked to project {pid}")
            located=None
            for m in manifest.get(linked["url"],[]):
                fp=content/Path(str(m.get("content_file") or "")).name
                if not fp.is_file(): continue
                raw=fp.read_bytes()
                try: record=json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError,json.JSONDecodeError): continue
                if record.get("url")==linked["url"] and isinstance(record.get("text"),str): located=(fp,raw,record); break
            if not located: raise SystemExit(f"fulltext unavailable {linked['url']}")
            fp,raw,record=located; text=record["text"]; text_sha=sha(text.encode())
            if text_sha!=linked["document_id"]: raise SystemExit(f"text hash mismatch {linked['url']}")
            raw_name=str(linked["raw_nombre_proyecto"] or names[pid]); start,end,fragment,method=finder(text,raw_name,names[pid])
            refs.append({"evidence_ref_id":f"{pair_id}:{side}:0","side":side,"project_id":pid,"project_name":names[pid],"raw_project_mention":raw_name,"document_id":linked["document_id"],"url":linked["url"],"content_file":f"Fuentes/fulltext/content/{fp.name}","source_text_sha256":text_sha,"content_record_sha256":sha(raw),"evidence_status":"literal_anchor_verified","quote":fragment,"matched_fragment":fragment,"match_method":method,"offset_start":start,"offset_end":end,"evidence_role":"literal_project_mention_anchor_not_identity_proof_by_itself"})
        entries.append({"pair_id":pair_id,"source_queue_rowid":rowid,"project_ids":[aid,bid],"project_names":names,"identity_class":cls,"resolver_action":"merge_case" if cls=="same_identity" else "no_new_merge","canonical_project_id":canonical,"canonical_selection_note":"explicit exact-ID representative, not chosen by name completeness" if canonical else None,"confidence":confidence,"rationale":rationale,"typed_relation_candidate":relation,"typed_relation_persisted":False,"production_promoted":False,"decision_source":"historical_pair_adjudication_2026-09-28","source_evidence":refs})
    conn.close()
    snapshot=[{"project_ids":e["project_ids"],"project_names":e["project_names"],"source_queue_rowid":e["source_queue_rowid"]} for e in entries]
    return {"schema_version":"historical_project_pair_adjudications_v1","artifact_id":"historical_project_pair_adjudications_2026-09-28_v1","generated_on":"2026-09-28","source_warehouse_sha256":sha(db.read_bytes()),"source_fulltext_manifest_sha256":sha(manifest_raw),"source_pair_snapshot_sha256":sha(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()),"scope":{"historical_name_only_decisions_re_adjudicated":26,"additional_exact_pair_outside_historical_set":1,"pair_count":len(entries),"lookup_key":"exact unordered project_id pair; never canonical-name substring","production_promoted":False,"rule":"merge only source-supported same_identity without topology contradiction; explicit non-identity is no_new_merge; unresolved remains pending"},"adjudications":entries}

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--source-project-root",type=Path,required=True); p.add_argument("--warehouse",type=Path,help="warehouse snapshot (defaults under --source-project-root)"); p.add_argument("--fulltext-root",type=Path,help="fulltext corpus root (defaults under --source-project-root)"); p.add_argument("--output",type=Path,default=Path(__file__).with_name("historical_project_pair_adjudications_v1.json")); p.add_argument("--stdout",action="store_true",help="emit canonical JSON to stdout without writing files"); a=p.parse_args()
    payload=build(a.source_project_root,Path(__file__).resolve().parents[1],warehouse=a.warehouse,fulltext_root=a.fulltext_root)
    rendered=json.dumps(payload,ensure_ascii=False,indent=2)+"\n"
    if a.stdout:
        print(rendered,end="")
    else:
        a.output.write_text(rendered,encoding="utf-8",newline="\n")
        print(json.dumps({"output":str(a.output.resolve()),"artifact_sha256":sha(a.output.read_bytes()),"pair_count":len(payload["adjudications"]),"classes":{c:sum(e["identity_class"]==c for e in payload["adjudications"]) for c in sorted({e["identity_class"] for e in payload["adjudications"]})},"warehouse_sha256":payload["source_warehouse_sha256"],"manifest_sha256":payload["source_fulltext_manifest_sha256"]},ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
