"""Actor Identity Resolution v1 -- siguiente cuello de botella senalado
por la revisión tras cerrar la comparacion CASE vs CONFLICT (2026-09-18): "la
identidad de CONFLICT ya esta bastante estabilizada; la identidad de
ACTOR sigue fragmentada" (ej. 'Servicio de Evaluacion Ambiental (SEA)'
vs 'Servicio de Evaluacion Ambiental' contados como 2 actores distintos).

Encargo explicito de la revisión para esta v1: construir un actor_registry/
actor_alias CONSERVADOR y AUDITABLE, no fuzzy matching global. Primero
instituciones con identidad verificable (SEA, Contraloria, ministerios,
municipalidades, tribunales con jurisdiccion clara), dejando personas,
organizaciones locales ambiguas y terminos genericos para rondas
posteriores. GENERIC_ACTOR_TERMS (los vecinos, municipio, la
inmobiliaria...) NUNCA se tocan aqui -- siguen ancladas a su unidad de
agrupacion (conflict_id/case_id), exactamente como ya funciona en
build_actor_network_comparison_v1.py, porque esos terminos no son la
misma entidad entre casos distintos.

## Esquema

- actor_registry: entity_id [CORREGIDO 2026-09-18, hallazgo bloqueante
  de la revisión] = hash estable de entity_key (una clave inmutable elegida a
  mano, NUNCA del conjunto de alias -- antes derivaba de los alias y
  agregar uno nuevo cambiaba el entity_id de una entidad ya publicada),
  canonical_label, n_alias.
- actor_alias: nombre_norm (nombre normalizado tal como aparece en el
  corpus) -> entity_id, mas 'fuente' (manual_v1) y 'confirmado_por'.
  Cualquier nombre normalizado que NO aparezca en actor_alias sigue
  usandose tal cual (su propia identidad, sin resolver) -- este registro
  es aditivo, nunca fuerza una identidad para nombres no revisados.

## Criterio de fusion v1 (deliberadamente estrecho)

Se fusionan ÚNICAMENTE pares donde la evidencia es no-ambigua por
construccion: la forma con sigla entre parentesis "X (SIGLA)" y la forma
sin sigla "X" son LITERALMENTE la misma expansion del mismo acronimo (no
hay ninguna lectura alternativa posible), mas un par adicional donde se
verifico contra citas reales del corpus que el nombre corto no tiene
lectura ambigua a nivel nacional (Contraloria, Ministerio de Vivienda).

Deliberadamente NO se fusiona en v1 (queda para rondas posteriores, con
mas evidencia por caso):
- 'Corte de Apelaciones' / 'Tribunal Ambiental' sin calificador de sede:
  Chile tiene 17 Cortes de Apelaciones y 3 Tribunales Ambientales:
  aunque este corpus es mayoritariamente de Santiago, fusionar sin
  verificar caso por caso repetiria el error de homonimo/generalizacion
  que ya se corrigio en la capa PROJECT (San Isidro, Costanera Center).
  la revisión lo senalo explicitamente como el caso que "requiere mucho mas
  cuidado".
- 'Direccion de Obras Municipales' / 'DOM' sin comuna: es un ROL que
  existe en cada una de las ~52 comunas del corpus, no una institucion
  nacional unica -- mezclarlas fusionaria DOMs de comunas distintas.
- SEREMI de Vivienda y variantes ('SEREMI MINVU', 'Secretaria
  Ministerial Metropolitana de Vivienda y Urbanismo'): tecnicamente
  regional (cada region tiene su SEREMI); aunque este corpus es
  mayoritariamente Region Metropolitana, no se verifico caso por caso.
- Nombres de municipalidades especificas (Municipalidad de Las Condes,
  de Ñuñoa, etc.): ya son consistentes en el corpus, no tienen variantes
  de escritura detectadas -- no requieren resolucion en v1.
- Personas, organizaciones locales/vecinales, y todo lo cubierto por
  GENERIC_ACTOR_TERMS.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import build_actor_network_comparison_v1 as net

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2_bridge.sqlite"
OUTPUT = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "actor_registry_v1_export.json"

# [ESTRUCTURA CORREGIDA 2026-09-18, hallazgo bloqueante de la revisión] Cada
# entidad tiene un 'entity_key' INMUTABLE elegido a mano (nunca deriva de
# la lista de alias). entity_id = hash('actor', entity_key) -- agregar,
# quitar o corregir un alias NUNCA cambia el entity_id de una entidad ya
# publicada, que es precisamente el comportamiento esperado de un
# registry (los alias crecen con el tiempo, la identidad no).
# Los alias se normalizan igual que
# build_actor_network_comparison_v1.normalize_actor_name (lower +
# espacios colapsados) antes de compararse.
ACTOR_ENTITIES: list[dict] = [
    {
        "entity_key": "cl_sea",
        "canonical_label": "Servicio de Evaluación Ambiental (SEA)",
        "aliases": [
            "servicio de evaluación ambiental (sea)",
            "servicio de evaluación ambiental",
            "sea",
            "servicio de evaluación ambiental, sea",
            "servicio de evaluación ambiental sea",
        ],
        "razon": (
            "Expansion literal de sigla -- '(SEA)' es la explicacion parentetica del mismo "
            "nombre, sin lectura alternativa posible. [Ronda 2, hallazgo de Sol] agregadas 2 "
            "variantes de puntuacion verificadas contra el corpus real (2 ocurrencias cada una): "
            "'Servicio de Evaluacion Ambiental, SEA' y '... SEA' (sin coma) -- mismo patron de "
            "nombre completo seguido de sigla, sin ambiguedad."
        ),
    },
    {
        "entity_key": "cl_cmn",
        "canonical_label": "Consejo de Monumentos Nacionales (CMN)",
        "aliases": [
            "consejo de monumentos nacionales (cmn)",
            "consejo de monumentos nacionales",
            "cmn",
            "consejo de monumentos",
            "consejo nacional de monumentos (cmn)",
        ],
        "razon": (
            "Expansion literal de sigla, organismo nacional unico (no existe otro CMN regional). "
            "[Ronda 2, hallazgo de Sol] agregadas 'Consejo de Monumentos' (forma corta, verificada "
            "contra cita real: 'El Consejo de Monumentos, en distintos periodos de gobierno siempre "
            "se nego a proteger...') y 'Consejo Nacional de Monumentos (CMN)' (variante de orden de "
            "palabras con la misma sigla explicita)."
        ),
    },
    {
        "entity_key": "cl_cde",
        "canonical_label": "Consejo de Defensa del Estado (CDE)",
        "aliases": ["consejo de defensa del estado (cde)", "consejo de defensa del estado", "cde"],
        "razon": "Expansion literal de sigla, organismo nacional unico.",
    },
    {
        "entity_key": "cl_sma",
        "canonical_label": "Superintendencia del Medio Ambiente (SMA)",
        "aliases": [
            "superintendencia del medio ambiente (sma)",
            "superintendencia del medio ambiente",
            "sma",
            "superintendencia de medio ambiente (sma)",
        ],
        "razon": (
            "Expansion literal de sigla, organismo nacional unico. [Ronda 2, hallazgo de Sol] "
            "agregada 'Superintendencia de Medio Ambiente (SMA)' (sin 'del', con 'de') -- variante "
            "de preposicion con 23 ocurrencias en el corpus real, verificada contra citas ('lo que "
            "fue denunciado ante la Superintendencia de Medio Ambiente (SMA)') que confirman que es "
            "la misma SMA nacional, no una entidad distinta."
        ),
    },
    {
        "entity_key": "cl_minvu",
        "canonical_label": "Ministerio de Vivienda y Urbanismo (MINVU)",
        "aliases": [
            "ministerio de vivienda y urbanismo (minvu)",
            "ministerio de vivienda y urbanismo",
            "minvu",
            "ministerio de vivienda",
            "ministerio de vivienda (minvu)",
            "el minvu",
        ],
        "razon": (
            "Expansion literal de sigla + verificado contra citas reales del corpus: 'Ministerio de "
            "Vivienda' sin calificador aparece siempre referido al MINVU nacional (ej. 'la mediacion "
            "del Ministerio de Vivienda', 'Division de Desarrollo Urbano (DDU) del Ministerio de "
            "Vivienda'), sin lectura alternativa en el corpus. [Ronda 2, hallazgo de Sol] agregadas "
            "'Ministerio de Vivienda (MINVU)' y 'el MINVU' -- mismo patron verificado, sin lectura "
            "alternativa (ej. 'el Minvu esta impulsando una consulta ciudadana...')."
        ),
    },
    {
        "entity_key": "cl_contraloria",
        "canonical_label": "Contraloría General de la República",
        "aliases": [
            "contraloría general de la república",
            "contraloría",
            "contraloría general de la república (cgr)",
            "contraloría general",
            "la contraloría",
            "contraloria general de la republica",
        ],
        "razon": (
            "Verificado contra citas reales del corpus: 'Contraloria' sin calificador se usa "
            "siempre para el organismo nacional (dictamenes, investigaciones sobre permisos), sin "
            "otro organismo llamado 'Contraloria' en el corpus. [Ronda 2, hallazgo de Sol] agregadas "
            "'Contraloria General de la Republica (CGR)' (sigla alternativa explicita), 'Contraloria "
            "General' y 'la Contraloria' (formas cortas, verificadas contra citas: 'esta Contraloria "
            "General manifesto...', 'se debera concurrir a la contraloria') y "
            "'contraloria general de la republica' (variante sin tildes, mismo texto)."
        ),
    },
]

# Terminos deliberadamente NO incluidos en ACTOR_ENTITIES, documentados
# para que quede explicito que se evaluaron y se descartaron para v1 (no
# simplemente "no se pensaron"): 'Corte de Apelaciones' y 'Tribunal
# Ambiental' sin sede (ambiguos a nivel nacional), 'Direccion de Obras
# Municipales'/DOM sin comuna (rol replicado en cada comuna), SEREMI de
# Vivienda y variantes (regional, no verificado caso por caso).


def _normalize(raw: str) -> str:
    return " ".join(raw.strip().split()).lower()


def _stable_entity_id(entity_key: str) -> str:
    """[CORREGIDO 2026-09-18, hallazgo bloqueante de la revisión] Antes derivaba
    del conjunto de alias -- agregar/quitar un alias (el uso normal de un
    registry con el tiempo) cambiaba el entity_id de una entidad ya
    publicada. Ahora deriva SOLO de entity_key, una clave inmutable
    elegida a mano que nunca cambia aunque los alias crezcan."""
    return "entity:" + hashlib.sha256(f"actor|{entity_key}".encode("utf-8")).hexdigest()[:24]


def build_registry() -> tuple[list[dict], list[dict]]:
    registry_rows = []
    alias_rows = []
    seen_alias = set()
    seen_entity_key = set()
    for entity in ACTOR_ENTITIES:
        entity_key = entity["entity_key"]
        if entity_key in seen_entity_key:
            raise ValueError(f"entity_key duplicada: '{entity_key}'")
        seen_entity_key.add(entity_key)

        alias_norm_list = sorted({_normalize(a) for a in entity["aliases"]})
        colision = set(alias_norm_list) & net.GENERIC_ACTOR_TERMS
        if colision:
            raise ValueError(
                f"'{entity['canonical_label']}': alias {colision} colisiona con GENERIC_ACTOR_TERMS -- "
                "esos terminos nunca deben fusionarse globalmente, solo quedar anclados a su "
                "unidad de agrupacion (ver build_actor_network_comparison_v1.py)."
            )
        entity_id = _stable_entity_id(entity_key)
        registry_rows.append(
            {
                "entity_id": entity_id,
                "entity_key": entity_key,
                "canonical_label": entity["canonical_label"],
                "n_alias": len(alias_norm_list),
                "tipo": "institucion_nacional_verificada",
            }
        )
        for alias_norm in alias_norm_list:
            if alias_norm in seen_alias:
                raise ValueError(f"alias '{alias_norm}' aparece en mas de una entidad de ACTOR_ENTITIES")
            seen_alias.add(alias_norm)
            alias_rows.append(
                {
                    "nombre_norm": alias_norm,
                    "entity_id": entity_id,
                    "fuente": "manual_v1",
                    "razon": entity["razon"],
                }
            )
    return registry_rows, alias_rows


def main():
    registry_rows, alias_rows = build_registry()

    conn = sqlite3.connect(WAREHOUSE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        DROP TABLE IF EXISTS actor_alias;
        DROP TABLE IF EXISTS actor_registry;

        CREATE TABLE actor_registry (
            entity_id TEXT PRIMARY KEY,
            entity_key TEXT NOT NULL UNIQUE,
            canonical_label TEXT NOT NULL,
            n_alias INTEGER NOT NULL,
            tipo TEXT NOT NULL
        );
        CREATE TABLE actor_alias (
            nombre_norm TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL REFERENCES actor_registry(entity_id),
            fuente TEXT NOT NULL,
            razon TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO actor_registry (entity_id, entity_key, canonical_label, n_alias, tipo) "
        "VALUES (:entity_id, :entity_key, :canonical_label, :n_alias, :tipo)",
        registry_rows,
    )
    conn.executemany(
        "INSERT INTO actor_alias (nombre_norm, entity_id, fuente, razon) "
        "VALUES (:nombre_norm, :entity_id, :fuente, :razon)",
        alias_rows,
    )
    conn.commit()

    # [CORREGIDO 2026-09-18, hallazgo real de la revisión] La cobertura anterior
    # solo contaba enrichment_institucion_v3_2, pero la red ACTOR<->CONFLICT
    # consume 3 fuentes (enrichment_actor_v3_2, enrichment_institucion_v3_2,
    # actor_second_pass_v2, todas unificadas en actor_event_project_link).
    # Se separan explicitamente 2 preguntas distintas:
    #   cobertura_corpus: "donde aparece este alias en TODO el corpus" ->
    #     actor_event_project_link (sin gate de conflicto).
    #   cobertura_network_safe: "a que conflictos queda vinculado este
    #     alias en la red conservadora" -> actor_event_project_link_conflict_safe,
    #     que preserva el vinculo EXACTO actor->project_id->conflict_id por fila.
    # [CORREGIDO 2026-09-18, bug real de la revisión] la primera version de esta
    # correccion calculaba conflictos_unicos_safe agregando TODOS los
    # conflictos del documento (via doc_to_conflicts_safe), no solo el
    # conflicto al que esa fila de actor especifica estaba enlazada --
    # sobreconteo real, confirmado por la revisión contra el SQLite: Contraloria
    # reportaba 25, el valor exacto es 17; MINVU reportaba 22, exacto 14.
    # SEA daba 12 en ambos calculos por coincidencia (sus documentos no
    # tenian el patron problematico), no porque la logica fuera correcta.
    # Se usa _normalize() en Python (no solo lower() en SQL) para que la
    # cobertura use exactamente la misma normalizacion que la resolucion
    # de identidad (strip + colapso de espacios, no solo minusculas).
    alias_a_entity = {a["nombre_norm"]: a["entity_id"] for a in alias_rows}
    stats_por_entidad: dict[str, dict] = {
        row["entity_id"]: {
            "n_rows_actor_v3_2": 0,
            "n_rows_institucion_v3_2": 0,
            "n_rows_second_pass": 0,
            "documentos_unicos_corpus": set(),
            "documentos_unicos_safe": set(),
            "conflictos_unicos_safe": set(),
        }
        for row in registry_rows
    }

    for nombre, source_table, document_id in conn.execute(
        "SELECT nombre, source_table, document_id FROM actor_event_project_link"
    ).fetchall():
        entity_id = alias_a_entity.get(_normalize(nombre))
        if entity_id is None:
            continue
        s = stats_por_entidad[entity_id]
        if source_table == "enrichment_actor_v3_2":
            s["n_rows_actor_v3_2"] += 1
        elif source_table == "enrichment_institucion_v3_2":
            s["n_rows_institucion_v3_2"] += 1
        elif source_table == "actor_second_pass_v2":
            s["n_rows_second_pass"] += 1
        s["documentos_unicos_corpus"].add(document_id)

    # Vinculo EXACTO fila-a-fila actor->conflict_id, no via documento.
    for nombre, document_id, conflict_id in conn.execute(
        "SELECT nombre, document_id, conflict_id FROM actor_event_project_link_conflict_safe"
    ).fetchall():
        entity_id = alias_a_entity.get(_normalize(nombre))
        if entity_id is None:
            continue
        s = stats_por_entidad[entity_id]
        s["documentos_unicos_safe"].add(document_id)
        s["conflictos_unicos_safe"].add(conflict_id)

    cobertura = []
    for row in registry_rows:
        alias_de_esta_entidad = [a["nombre_norm"] for a in alias_rows if a["entity_id"] == row["entity_id"]]
        s = stats_por_entidad[row["entity_id"]]
        cobertura.append(
            {
                "canonical_label": row["canonical_label"],
                "entity_key": row["entity_key"],
                "alias": alias_de_esta_entidad,
                "cobertura_corpus": {
                    "n_rows_actor_v3_2": s["n_rows_actor_v3_2"],
                    "n_rows_institucion_v3_2": s["n_rows_institucion_v3_2"],
                    "n_rows_second_pass": s["n_rows_second_pass"],
                    "n_documentos_unicos": len(s["documentos_unicos_corpus"]),
                },
                "cobertura_network_safe": {
                    "n_documentos_unicos": len(s["documentos_unicos_safe"]),
                    "n_conflictos_unicos": len(s["conflictos_unicos_safe"]),
                },
            }
        )

    summary = {
        "n_entidades": len(registry_rows),
        "n_alias_totales": len(alias_rows),
        "cobertura": cobertura,
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_check_issues": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    OUTPUT.write_text(
        json.dumps(
            {
                "contexto": (
                    "actor_registry/actor_alias v1 -- resolucion conservadora de identidad de "
                    "actor para instituciones nacionales con identidad verificable. Ver docstring "
                    "de build_actor_registry_v1.py para el criterio de fusion y lo que "
                    "deliberadamente queda sin resolver (Corte de Apelaciones/Tribunal Ambiental "
                    "sin sede, DOM/SEREMI sin comuna/region, personas, terminos genericos)."
                ),
                "resumen": summary,
                "registry": registry_rows,
                "alias": alias_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nEscrito: {OUTPUT.relative_to(PROJECT_ROOT)}")

    conn.close()
    return summary


if __name__ == "__main__":
    main()
