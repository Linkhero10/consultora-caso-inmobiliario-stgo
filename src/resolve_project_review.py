#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resuelve la cola de revision de proyectos (project_review_queue) --
revision humana pedida por el diseno del puente, ejecutada por Claude a
peticion explicita del usuario ("revisa los 253 candidatos... corrige y
arregla todo"), con criterio auditable y explicito, NUNCA fusion silenciosa.

Reglas aplicadas, en orden, a cada par (nombre_a, nombre_b, comunas_a,
comunas_b):

1. Diferenciador de numero/etapa/fase [ACTUALIZADO 2026-09-18, hallazgo de
   la revisión -- este parrafo describia la regla vieja, el codigo ya cambio y el
   comentario habia quedado desactualizado]. Ya NO es una regla unica: se
   separo en dos senales de confianza distinta (ver has_explicit_stage_
   conflict / has_bare_trailing_numeral_conflict mas abajo). Una "Etapa N"/
   "Fase N" EXPLICITA en el texto SI sigue siendo una senal fuerte que
   bloquea la fusion automaticamente (ej. "Mall Vivo Santiago" vs "Mall Vivo
   Santiago Etapa II" -- distinto NUMERO de etapa bloquea; el MISMO numero
   de etapa no bloquea). Un numeral SUELTO sin la palabra etapa/fase (ej.
   "General Amengual 480", "Pajaritos 4600", "Alto Las Condes 2") ya NO se
   decide automaticamente -- casi siempre es una direccion, no una fase, y
   manda a revision humana/decision manual explicita en vez de asumir
   kept_separate. NUNCA leer este parrafo como "un numeral distinto siempre
   separa" -- eso ya no es cierto para numerales sueltos.
2. Lista de nombres genericos que NUNCA se fusionan solos porque aparecen
   como termino generico/de marca en MULTIPLES proyectos distintos del
   corpus real (verificado antes de listar, no supuesto): "data center",
   "vespucio", "ciudad empresarial", "lo aguirre", "las americas",
   "supermercado lider".
3. Todo lo demas requiere revision de caso -- las decisiones especificas
   (fusionar / mantener separado / incierto) quedan en `DECISIONS` abajo,
   basadas en revision manual de nombre + comuna + urls de cada
   documento real (nunca solo el nombre). Los casos de "mantener separado
   por ser sub-instalacion de un complejo mayor" (ej. una cancha de hockey
   DENTRO del Estadio Nacional, un taller DE la Linea 7 del Metro) tambien
   quedan explicitos aqui, no como regla generica (demasiado dificil de
   detectar de forma fiable con regex).

Cada decision queda registrada en `project_review_queue.resolved` +
`project_review_queue.decision` + `project_review_queue.decision_reason`
-- ninguna fila se borra, todas quedan auditables. Las fusiones se aplican
como un nuevo campo `project.case_id` (varios project_id pueden compartir
un case_id) -- el project_id original de cada mencion NUNCA se reescribe,
se preserva la granularidad fina para quien la necesite.

No llama a la API.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from build_project_relations import rebuild_project_relations


def _stable_phase_id(*parts: str) -> str:
    return "phase:" + hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:24]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = PROJECT_ROOT / "data" / "warehouse.sqlite"
CASE_BASELINE = PROJECT_ROOT / "config" / "project_case_baseline_v1.json"

GENERIC_BLOCKLIST = {"data center", "vespucio", "ciudad empresarial", "lo aguirre", "las americas", "supermercado lider"}

_NUMERAL_RE = re.compile(r"\b(i{1,3}|iv|v|vi{0,3}|\d+)\b", re.IGNORECASE)
_ETAPA_RE = re.compile(r"\b(etapa|fase)\s+([ivx\d]+)\b", re.IGNORECASE)
HISTORICAL_PAIR_ADJUDICATION_SHA256 = "ee6d0736cff9a69f8d4fab56826caeaa7d46075878164e6a1f7060f2c5f517f1"
PROJECT_IDENTITY_BASE_ADJUDICATION_SHA256 = "78d67ffed64e4b45d913a69d38c7ed664a8031007253e88a3a35a1d3748d358f"
PROJECT_IDENTITY_OVERRIDE_SHA256 = "1dc0cedb34e95a24bcb6d756d56a5be25f913742d0e3405ca400b04f9abd00c4"
PROJECT_IDENTITY_OVERRIDE_SOURCE = "project_identity_adjudication_override_2026-09-28"


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii").lower()


def _etapa_tokens(name: str) -> set[str]:
    n = _norm(name)
    return {f"{m.group(1)}_{m.group(2)}" for m in _ETAPA_RE.finditer(n)}


def _trailing_numeral_tokens(name: str) -> set[str]:
    n = _norm(name)
    trailing = re.search(r"\b(i{1,3}|iv|\d+)\s*$", n.strip())
    return {trailing.group(1)} if trailing else set()


def has_explicit_stage_conflict(name_a: str, name_b: str) -> bool:
    """True si un nombre tiene una "Etapa N"/"Fase N" EXPLICITA que el otro no
    tiene, o ambos tienen una pero distinta -- NUNCA aplica si ninguno usa la
    palabra etapa/fase, o si ambos comparten exactamente la misma. Esta senal
    es fuerte (la palabra etapa/fase es explicita en el texto), se sigue
    resolviendo automaticamente como kept_separate."""
    ta, tb = _etapa_tokens(name_a), _etapa_tokens(name_b)
    if not ta and not tb:
        return False
    return ta != tb


def has_bare_trailing_numeral_conflict(name_a: str, name_b: str) -> bool:
    """True si un nombre termina en un numero/numeral romano SUELTO (sin la
    palabra etapa/fase) que el otro no tiene, o ambos tienen uno distinto.
    [Hallazgo real de la revisión, segunda auditoria 2026-09-18, y confirmado por
    Claude contra evidencia real: un numeral suelto casi siempre es una
    DIRECCION (ej. "General Amengual 480", "Pajaritos 4600", "Vital
    Apoquindo 1400-1500"), no una fase de construccion -- la version anterior
    de esta regla trataba ambos casos igual y bloqueaba fusiones correctas.
    Por eso esta senal, a diferencia de has_explicit_stage_conflict, YA NO se
    usa para decidir kept_separate automaticamente en classify() -- solo
    dispara needs_human_review, salvo que un par especifico ya tenga una
    entrada en MANUAL_DECISIONS."""
    ta, tb = _trailing_numeral_tokens(name_a), _trailing_numeral_tokens(name_b)
    if not ta and not tb:
        return False
    return ta != tb


def has_conflicting_numeral(name_a: str, name_b: str) -> bool:
    """Retenida por compatibilidad con llamadores/tests existentes: es la
    union de las dos senales de arriba. classify() ya NO la usa directamente
    -- usa has_explicit_stage_conflict (bloquea) y
    has_bare_trailing_numeral_conflict (manda a revision) por separado."""
    return has_explicit_stage_conflict(name_a, name_b) or has_bare_trailing_numeral_conflict(name_a, name_b)


# [REDISENADO 2026-09-18, hallazgo conceptual de la revisión -- ver active-context.md
# ronda 11] La primera version de este modelo trataba "fase" como una unica
# relacion simetrica (union-find): "Urbanya" y "Urbanya Etapa I" terminaban
# en el MISMO phase_family_id, como si fueran 2 alias de la misma fase. Eso
# esta invertido -- "Urbanya" es el proyecto MATRIZ y "Urbanya Etapa I" es
# UNA fase especifica DENTRO de el (relacion asimetrica matriz->fase, no una
# equivalencia). Y el caso inverso real ("Fase IV" vs "...Enea Fase IV...",
# donde AMBOS nombres SI son la misma fase, solo redactada distinto) nunca
# se capturaba porque no existia una relacion para "estos 2 nombres son la
# misma fase" separada de "este nombre es una fase de aquel proyecto".
#
# Modelo corregido, con 3 relaciones explicitas en vez de una union unica
# [ACTUALIZADO 2026-09-18, deuda documental senalada por la revisión: esta seccion
# seguia diciendo "2 relaciones" y "phase_of" despues del refinamiento que
# agrego represents_phase y renombro phase_of a has_phase -- el summary de
# main() ya estaba al dia, solo este comentario inicial habia quedado atras]
# (ver tablas project_phase / project_phase_link mas abajo en main()):
#   - has_phase: project_id de la MATRIZ -> phase_id de una fase especifica
#     dentro de ella. Asimetrica: la matriz nunca es "la misma fase" que su
#     propia fase.
#   - same_phase_alias: 2+ project_id que son, literalmente, la MISMA fase
#     descrita con redaccion distinta (ej. "Fase IV" y "...Enea Fase IV...").
#   - represents_phase: UN SOLO project_id que representa una fase sin tener
#     ningun alias real (ej. "Urbanya Etapa I", que nadie mas nombra igual).
#
# Los 26 pares de la revisión externa (2026-09-18) se dividen asi:
#   - 5 fase_real -> PHASE_OF_PAIRS_BY_SOL (orden: matriz, fase)
#   - 2 de los "otra_razon_no_es_fase" (Mall Vivo Santiago Etapa II vs
#     Centro Comercial Mall Vivo Santiago Etapa II; Fase IV vs Enea Fase IV)
#     -> SAME_PHASE_ALIAS_PAIRS_BY_SOL
#   - 18 mismo_referente_numero_no_es_fase + 1 otra_razon (Lote 18/18-A1,
#     subdivision de lote, no relacion de fase) -> ninguna relacion de fase.
PHASE_OF_PAIRS_BY_SOL: list[tuple[str, str]] = [
    ("Urbanya", "Urbanya Etapa I"),
    ("Mall Vivo", "Mall Vivo Santiago Etapa II"),
    ("Mall Vivo Santiago", "Mall Vivo Santiago Etapa II"),
    ("Mall Vivo", "Centro Comercial Mall Vivo Santiago Etapa II"),
    ("Mall Vivo Santiago", "Centro Comercial Mall Vivo Santiago Etapa II"),
]

SAME_PHASE_ALIAS_PAIRS_BY_SOL: list[tuple[str, str]] = [
    ("Mall Vivo Santiago Etapa II", "Centro Comercial Mall Vivo Santiago Etapa II"),
    ("Fase IV", "Radial Aeropuerto Nº 14080, Enea Fase IV, Lote 3E-2"),
]


def is_generic_bare_name(name: str, other_name: str) -> bool:
    n = _norm(name).strip()
    return n in GENERIC_BLOCKLIST and _norm(other_name).strip() not in GENERIC_BLOCKLIST


# Decisiones explicitas por par (name_a, name_b) tal como aparecen en
# project_review_queue -- revisadas a mano contra comuna + urls reales de
# cada documento (ver Auditoria/integracion_v1/project_review_queue.json
# y el analisis registrado en la bitacora FARO, turn correspondiente a
# 2026-09-17 noche, resolucion de la cola de revision).
MANUAL_DECISIONS: dict[tuple[str, str], tuple[bool, str]] = {
    ("Parque Padre Hurtado", "laguna artificial en el Parque Padre Hurtado"): (True, "misma laguna dentro del mismo parque, mismas fechas 2018-10"),
    ("Conjunto Armónico Portezuelo", "Portezuelo"): (True, "mismo proyecto, Vitacura"),
    ("Rotonda Atenas", "proyecto de viviendas sociales en Las Condes, en Rotonda Atenas"): (True, "descripcion del mismo proyecto Rotonda Atenas"),
    ("torre Bellavista", "proyecto Bellavista"): (True, "mismo complejo Universidad San Sebastian, Recoleta -- ya investigado a fondo antes en esta sesion"),
    ("cementerio Parque Santiago de Huechuraba", "Cementerio Parque Santiago"): (True, "mismo cementerio, Huechuraba"),
    ("El Rincón", "loteo El Rincón"): (True, "mismo loteo"),
    ("Lomas de Peñalolén", "Condominio Lomas de Peñalolén"): (True, "mismo condominio"),
    ("Conjunto Armónico Bellavista", "proyecto Bellavista"): (True, "mismo complejo Universidad San Sebastian"),
    ("Conjunto Armónico Bellavista", "Proyecto Armónico Bellavista"): (True, "variante de escritura del mismo nombre"),
    ("Conjunto Armónico Bellavista", "Conjunto Armónico Bellavista (CAB)"): (True, "sigla del mismo nombre"),
    ("Conjunto Armónico Bellavista (CAB)", "segunda torre habitacional del proyecto Conjunto Armónico Bellavista (CAB)"): (False, "[hallazgo 2026-09-28, validate_project_identity_adjudication_topology detecto una reconexion transitiva incorrecta] 'segunda torre habitacional...' describe una torre/fase especifica dentro del complejo, no el complejo completo; la reconexion por substring normalizado encontraba un unico candidato -- la decision de sigla 'Conjunto Armónico Bellavista'/'Conjunto Armónico Bellavista (CAB)' -- e ignoraba que el nombre completo describe un componente, no la matriz. Coincide con la adjudicacion source-first de Codex/Luna (2026-09-27, pair_id 675fac8049249f80d63d): parent_component_phase, no_new_merge."),
    ("Proyecto Armónico Bellavista", "segunda torre habitacional del proyecto Conjunto Armónico Bellavista (CAB)"): (False, "[hallazgo 2026-09-28, misma logica que la entrada anterior] Componente/fase especifica, no identidad con la matriz. Coincide con la adjudicacion source-first de Codex/Luna (2026-09-27, pair_id 675fac8049249f80d63d): parent_component_phase, no_new_merge."),
    ("proyecto Bellavista", "segunda torre habitacional del proyecto Conjunto Armónico Bellavista (CAB)"): (False, "[hallazgo 2026-09-28, misma logica] Componente/fase especifica, no identidad con la matriz. Coincide con la adjudicacion source-first de Codex/Luna (2026-09-27, pair_id f123b7c3132c33fe6135): parent_component_phase, no_new_merge."),
    ("subdivisión del resto del Lote C", "resto del Lote C"): (True, "mismo lote"),
    ("Ciudad del Niño", "megaproyecto de 23 torres en Ciudad del Niño"): (True, "descripcion del mismo desarrollo"),
    ("Ciudad del Niño", "ex Ciudad del Niño"): (True, "mismo sitio, nombre historico"),
    ("Eco Egaña Comunidad Sustentable", "Egaña Comunidad Sustentable"): (True, "mismo proyecto Ñuñoa, prefijo Eco- opcional"),
    ("Eco Egaña Comunidad Sustentable", "Eco Egaña"): (True, "mismo proyecto, forma corta"),
    ("Bosque Panul", "proyecto de subdivisión del Bosque Panul"): (True, "misma subdivision"),
    ("Estadio Nacional", "Estadio Nacional Julio Martínez Pradanos"): (True, "nombre oficial completo del mismo estadio"),
    ("Estadio Nacional", "Parque Deportivo Estadio Nacional"): (False, "instalacion especifica dentro del complejo, no el estadio mismo"),
    ("Estadio Nacional", "Centro de Entrenamiento de Hockey Césped del Estadio Nacional"): (False, "instalacion especifica dentro del complejo"),
    ("Helipuerto Santiago SpA", "Helipuerto Santiago"): (True, "mismo helipuerto, sufijo de razon social"),
    ("Ciudad Portal Bicentenario", "Portal Bicentenario"): (True, "mismo proyecto"),
    ("Centro Cívico del Portal Bicentenario", "Portal Bicentenario"): (False, "componente especifico dentro del proyecto mayor"),
    ("Villa Panamericana", "Villa Panamericana de Cerrillos"): (True, "mismo proyecto, comuna agregada"),
    ("Villa Panamericana", "Villa Panamericana-Lote B"): (False, "lote especifico dentro del proyecto mayor, probable permiso distinto"),
    ("Villa Panamericana de Cerrillos", "Lote B de la Villa Panamericana de Cerrillos"): (False, "[hallazgo 2026-09-28, validate_project_identity_adjudication_topology detecto una reconexion transitiva incorrecta] Lote B es un lote especifico dentro del proyecto mayor (misma logica que 'Villa Panamericana'/'Villa Panamericana-Lote B' ya decidida arriba); la reconexion por substring normalizado encontraba un unico candidato -- la decision generica de 'Villa Panamericana'/'Villa Panamericana de Cerrillos' (comuna agregada) -- e ignoraba que el nombre completo describe un lote, no la matriz. Coincide con la adjudicacion source-first de Codex/Luna (2026-09-27, pair_id 178854a4dd1ca649a3b4): parent_component_phase, no_new_merge."),
    ("Hotel Sheraton", "Hotel Sheraton Santiago"): (True, "mismo hotel"),
    ("Hotel Sheraton", "proyecto de construcción en perímetro del Hotel Sheraton Santiago"): (False, "proyecto de construccion distinto, adyacente al hotel"),
    ("Reserva La Dehesa", "Reserva La Dehesa (ex Chaguay)"): (True, "mismo sitio, nombre anterior entre parentesis"),
    ("Desnitrificador SCR para Caldera de Ciclo Combinado de Central Nueva Renca", "Nueva Renca"): (True, "obra especifica en la misma central"),
    ("Chaguay", "Habilitación de caminos de acceso e instalaciones complementarias de la subdivisión agrícola Chaguay"): (True, "misma subdivision Chaguay"),
    ("Chaguay", "Reserva La Dehesa (ex Chaguay)"): (True, "Chaguay es el nombre anterior del mismo sitio"),
    ("Eco Egaña Sustentable", "Eco Egaña"): (True, "mismo proyecto"),
    ("Eco Egaña Sustentable", "Egaña Sustentable"): (True, "mismo proyecto"),
    ("Eco Egaña", "Egaña Sustentable / Eco Egaña"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] Fuentes de Fundamenta usan Eco Egaña y Egaña Sustentable/Eco Egaña para la misma obra, titular y emplazamiento."),
    ("Egaña Sustentable", "Egaña Sustentable / Eco Egaña"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] La fuente de Corte Suprema identifica Egaña Sustentable de Fundamenta; La Tercera usa conjuntamente Egaña Sustentable/Eco Egaña para la misma obra."),
    ("Lo Aguirre", "Izarra de Lo Aguirre"): (False, "Lo Aguirre es un sector con multiples desarrollos distintos, no un solo proyecto"),
    ("Lo Aguirre", "PDUC Ciudad Lo Aguirre"): (False, "sector con multiples desarrollos distintos"),
    ("Lo Aguirre", "Centro de Distribución Lo Aguirre"): (False, "desarrollo especifico dentro del sector"),
    ("Lo Aguirre", "Lomas de Lo Aguirre"): (False, "desarrollo especifico dentro del sector"),
    ("Lo Aguirre", "Centro Logístico Lo Aguirre de Bodegas San Francisco"): (False, "desarrollo especifico dentro del sector"),
    ("Vespucio", "Jardines de Vespucio"): (False, "Vespucio es nombre de avenida/sector, no un proyecto especifico"),
    ("globos de televigilancia", "globos de televigilancia en Las Condes y Lo Barnechea"): (True, "misma iniciativa"),
    ("Ciudad de Los Valles", "supermercado Express de Líder en Ciudad de Los Valles"): (False, "tienda especifica dentro del desarrollo mayor"),
    ("Ciudad de Los Valles", "Líder de Ciudad de Los Valles"): (False, "tienda especifica dentro del desarrollo mayor"),
    ("Mina Panales 1/54", "Explotación de la Mina Panales 1 a 54"): (True, "misma mina"),
    ("Mina Panales 1/54", "Panales"): (True, "misma mina, forma corta"),
    ("Recreo", "Recreo N° 321"): (True, "mismo desarrollo, direccion especifica"),
    ("Recreo", "Recreo 321"): (True, "mismo desarrollo, direccion especifica"),
    ("PDUC Urbanya", "Urbanya"): (True, "PDUC es el instrumento de planificacion del mismo proyecto Urbanya"),
    ("Data Center de Google", "Data Center"): (False, "Data Center es termino generico, multiples proyectos distintos en el corpus"),
    ("Data Center de Google", "data center de Google Chile en Cerrillos"): (True, "[revision 2026-09-26, reconciliacion v3.2->v3.3 tras hallazgo de Codex/Luna, aprobado por el usuario -- ver audit/project_identity_reconciliation_v3_2_v3_3_2026-09-26.json] la separacion generica heredada de ('Data Center de Google', 'Data Center') no aplica a este par especifico: ex-ante.cl confirma que 'Data Center de Google' es el proyecto entre Cerrillos y San Bernardo (no el de Quilicura), y La Tercera confirma que 'data center de Google Chile en Cerrillos' es ese mismo proyecto propuesto en Cerrillos -- distinto del centro operativo de Quilicura (2015) citado por Google. Mismo proyecto."),
    ("Mall Vivo Santiago Etapa II", "Centro Comercial Mall Vivo Santiago Etapa II"): (True, "misma etapa II, nombre completo"),
    ("supermercado Lider", "supermercado Líder San Francisco"): (False, "Lider es cadena generica con multiples locales distintos en el corpus"),
    ("estacionamientos de Alonso de Córdova", "Concesionaria de Estacionamientos Alonso de Córdova (Zoccalo)"): (True, "misma concesion de estacionamientos"),
    ("Autopista Vespucio Oriente (AVO)", "Vespucio Oriente"): (True, "misma autopista, sigla"),
    ("Autopista Vespucio Oriente (AVO)", "Autopista Vespucio Oriente"): (True, "mismo nombre sin sigla"),
    ("proyecto Bellavista", "Proyecto Armónico Bellavista"): (True, "mismo complejo Universidad San Sebastian"),
    ("proyecto Bellavista", "Conjunto Armónico Bellavista (CAB)"): (True, "mismo complejo"),
    ("proyecto Bellavista", "proyecto de Inmobiliaria Bellavista en calle Dardignac"): (True, "mismo complejo, calle Dardignac coincide con la investigacion previa"),
    ("proyecto Bellavista", "Proyecto de la Universidad San Sebastián en la manzana delimitada por las calles Bellavista, Ernesto Pinto Lagarrigue, Dardignac y Pío Nono"): (True, "descripcion completa del mismo complejo ya investigado a fondo"),
    ("proyecto Bellavista", "Conjunto Inmobiliario Bellavista"): (True, "mismo complejo"),
    ("Hotel Sheraton Santiago", "proyecto de construcción en perímetro del Hotel Sheraton Santiago"): (False, "proyecto de construccion distinto, adyacente"),
    ("Villa Olímpica", "Block 73 de Villa Olímpica"): (False, "bloque especifico dentro del complejo historico, caso propio de demolicion"),
    ("Tranque La Poza", "Humedal Urbano Tranque La Poza"): (True, "mismo humedal, designacion oficial agregada"),
    ("El Castillo", "Plan de regeneración urbana para la población El Castillo"): (True, "mismo caso, el plan describe la misma poblacion"),
    ("una cochera y un taller para la Línea 7 del Metro", "Línea 7 del Metro"): (False, "instalacion especifica de la linea, no la linea completa"),
    ("Remodelación San Borja", "Remodelacion San Borja de Santiago"): (True, "mismo proyecto, variante de acento y comuna agregada"),
    ("Costanera Center", "mall Costanera Center"): (True, "mismo mall"),
    ("Villa San Luis", "Villa San Luis de Las Condes"): (True, "mismo caso historico Villa San Luis"),
    ("Villa San Luis", "Villa Ministro Carlos Cortés (Villa San Luis de Las Condes)"): (True, "Villa Ministro Carlos Cortes es el nombre oficial original del mismo caso"),
    ("Villa San Luis", "Museo Memorial Villa San Luis"): (True, "museo sobre el mismo caso historico, parte de la misma narrativa"),
    ("Villa San Luis", "ex Villa San Luis"): (True, "mismo sitio, prefijo ex-"),
    ("Villa San Luis de Las Condes", "Villa Ministro Carlos Cortés (Villa San Luis de Las Condes)"): (True, "mismo caso"),
    ("Mall Sport", "Mall Sport de Las Condes"): (True, "mismo mall, comuna agregada"),
    ("Línea 8", "linea 8 del metro"): (True, "misma linea, variante de mayusculas"),
    ("Línea 7 del Metro", "Talleres de la Línea 7 del Metro"): (False, "instalacion especifica (talleres), no la linea completa"),
    ("Línea 7 del Metro", "Línea 7 Metro de Santiago"): (True, "misma linea, variante de orden de palabras"),
    ("Línea 3 del Metro", "Línea 3 del Metro de Santiago"): (True, "misma linea, comuna/ciudad agregada"),
    ("Proyecto Armónico Bellavista", "Conjunto Armónico Bellavista (CAB)"): (True, "mismo complejo"),
    ("nuevo edificio de la Cámara Chilena de la Construcción en Las Condes", "nuevo edificio de la Cámara Chilena de la Construcción"): (True, "mismo edificio, comuna agregada"),
    ("Centro Comercial Cencosud Shopping en Vitacura", "Cencosud Shopping Vitacura"): (True, "mismo centro comercial"),
    ("Alto Las Condes", "Alto Las Condes 2"): (False, "expansion numerada, fase distinta"),
    ("Alto Las Condes", "mall Alto Las Condes"): (True, "mismo mall, sin numeral"),
    ("Alto Las Condes", "Alto Las Condes II"): (False, "expansion numerada, fase distinta"),
    ("Villa Ministro Carlos Cortés (Villa San Luis de Las Condes)", "Villa Ministro Carlos Cortés"): (True, "mismo nombre, sin la aclaracion parentetica"),
    ("Las Pircas Norte", "Condominio El Pórtico Las Pircas Norte"): (True, "mismo condominio en el mismo sector"),
    ("Mall Vivo Santiago", "Mall Vivo Santiago: Etapa de Demolición, Excavación y Socalzados"): (True, "describe una actividad del mismo proceso, no una etapa numerada distinta"),
    ("Espacio Riesco", "Centro de Eventos Espacio Riesco"): (True, "mismo recinto, nombre completo"),
    ("nuevo teleférico", "nuevo teleférico que unirá Huechuraba con Providencia"): (True, "misma iniciativa, descripcion agregada"),
    ("Cerrillos Data Center", "Modificación del Proyecto Cerrillos Data Center"): (True, "modificacion del mismo proyecto especifico"),
    ("Cerrillos Data Center", "Data Center"): (False, "Data Center es termino generico"),
    ("Modificación del Proyecto Cerrillos Data Center", "Data Center"): (False, "Data Center es termino generico"),
    ("Vespucio Oriente", "Vespucio Oriente II"): (False, "expansion numerada, fase distinta"),
    ("Parque Cousiño Macul", "Parque Cousiño Macul, Loteo S1 y S2"): (True, "mismo parque, lotes especificos del mismo proyecto"),
    ("Los Damascos", "Nueva los Damascos"): (True, "mismo sitio, version actualizada del nombre"),
    ("Block 73 de Villa Olímpica", "Block 73"): (True, "mismo bloque, forma corta"),
    ("La Cumbre", "La Cumbre Oriente"): (False, "sub-sector especifico, incierto si es el mismo proyecto"),
    ("Hacienda Guay Guay", "Guay Guay"): (True, "mismo sitio, forma corta"),
    ("Seccional La Platina", "La Platina"): (True, "mismo sitio, instrumento de planificacion en el nombre largo"),
    ("Curtidos BAS", "Curtidos Bas S.A."): (True, "misma empresa/sitio, razon social completa"),
    ("Zoccalo", "Concesionaria de Estacionamientos Alonso de Córdova (Zoccalo)"): (True, "Zoccalo es el nombre corto de la misma concesionaria"),
    ("Hospital Militar", "Hospital Metropolitano, ex Hospital Militar"): (True, "mismo hospital, renombrado"),
    ("Centro de Estudios Nucleares", "Centro de Estudios Nucleares de La Reina"): (True, "mismo centro, comuna agregada"),
    ("Explotación de la Mina Panales 1 a 54", "Panales"): (True, "misma mina, forma corta"),
    ("Distrito Cordillera I", "Distrito Cordillera II"): (False, "etapas numeradas distintas"),
    ("La Maestranza I", "La Maestranza II"): (False, "etapas numeradas distintas"),
    ("primer data center de América Latina", "Data Center"): (False, "Data Center es termino generico"),
    ("Conjunto Inmobiliario Portezuelo", "Portezuelo"): (True, "mismo proyecto Portezuelo"),
    ("Carpa de Ciudad Empresarial", "Ciudad Empresarial"): (False, "Ciudad Empresarial es un parque de negocios con multiples edificios, no un proyecto unico"),
    ("supermercado Líder San Francisco", "Líder San Francisco"): (True, "misma tienda, forma corta"),
    ("supermercado Express de Líder en Ciudad de Los Valles", "Líder de Ciudad de Los Valles"): (True, "misma tienda especifica"),
    ("proyecto de 25 edificios en la calle Vital Apoquindo", "Proyecto de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500"): (True, "mismo proyecto, direccion especifica agregada"),
    ("Villa Panamericana-Lote B", "Lote B"): (True, "mismo lote, forma corta"),
    ("torre C del complejo Puerto de Palos", "Puerto de Palos"): (False, "torre especifica dentro del complejo mayor"),
    ("construcciones Antígona", "Antígona"): (True, "mismo proyecto, forma corta"),
    ("Lote 18", "Lote 18-A1"): (True, "mismo lote, sub-parcela especifica"),

    # Segunda ronda: pares de las bolsas "insuficiente informacion de
    # ubicacion" y "sin traslape de comuna" -- revisados con nombre + dato
    # de ubicacion cuando existia. Patron nuevo identificado aqui:
    # "Bicentenario", "Mall Vivo", "Fundamenta" (la empresa), "Parque
    # Forestal", "La Florida" (la comuna), "Vital Apoquindo" (la calle,
    # con multiples proyectos distintos encima) funcionan como
    # marca/cadena/comuna/calle GENERICA que aparece sobre MULTIPLES
    # proyectos especificos y genuinamente distintos en este mismo corpus
    # -- nunca se fusionan solos con un nombre generico de esa lista.
    ("edificio de 13 pisos", "torre de oficinas de 13 pisos, con 107 estacionamientos"): (False, "ubicaciones distintas (La Florida vs Viña del Mar/Vitacura/Santiago)"),
    ("edificio de 13 pisos", "edificio de 13 pisos junto al pasaje El Almendral"): (False, "sin evidencia de ser el mismo edificio de La Florida"),
    ("Rotonda Atenas", "edificio con 85 viviendas sociales en plena rotonda Atenas"): (True, "mismo proyecto Rotonda Atenas"),
    ("Rotonda Atenas", "departamentos de Rotonda Atenas"): (True, "mismo proyecto Rotonda Atenas"),
    ("proyecto de Rotonda Atenas", "85 departamentos de viviendas sociales en el sector de Rotonda Atenas"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] Le Monde Diplomatique identifica el proyecto de Rotonda Atenas; Hogar de Cristo describe 85 viviendas sociales en el mismo sector y finalidad -- el mismo desarrollo historico de Rotonda Atenas (no el proyecto distinto de 2023 en Cerro Colorado 4661)."),
    ("proyecto de Rotonda Atenas", "condominio Rotonda Atenas"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] Le Monde Diplomatique describe el proyecto de Rotonda Atenas; La Tercera identifica el condominio Rotonda Atenas y sus 85 unidades -- la misma torre/proyecto historico."),
    ("Centro Comunitario Padre Hurtado", "Edificación Centro Comunitario Padre Hurtado"): (True, "mismo centro"),
    ("Teleférico Bicentenario", "Proyecto Bicentenario"): (False, "Bicentenario es marca generica usada en multiples proyectos distintos del corpus"),
    ("El Rincón", "Central Hidroeléctrica de Pasada El Rincón"): (False, "tipo de proyecto distinto, sin evidencia de ser el mismo sitio"),
    ("El Rincón", "Habilitación Corredor de Transporte Público Eje Vial Rinconada Maipú"): (False, "Rinconada Maipu es un lugar distinto a El Rincon"),
    ("Canal El Bollo", "Parque Canal El Bollo"): (True, "mismo canal/parque"),
    ("Cenco Malls", "Centro Comercial Cenco Malls en Vitacura y acceso terreno Holy Cross"): (True, "mismo mall"),
    ("Edificio ilegal de la Universidad San Sebastián", "Universidad San Sebastián"): (False, "Universidad San Sebastian es la institucion (actor), no un nombre de proyecto especifico por si solo"),
    ("Plaza Egaña", "Torres Plaza Egaña"): (False, "Plaza Egaña es un lugar/interseccion generica con multiples desarrollos distintos"),
    ("Plaza Egaña", "Mega Proyecto Plaza Egaña"): (False, "Plaza Egaña generico"),
    ("Plaza Egaña", "Mall Plaza Egaña"): (False, "Plaza Egaña generico, posible desarrollo distinto"),
    ("Plaza Egaña", "nueva Plaza Egaña"): (False, "Plaza Egaña generico"),
    ("Liceo Javiera Carrera", "Proyecto de Conservación Liceo Javiera Carrera"): (True, "mismo liceo"),
    ("proyecto de 4 torres de la Inmobiliaria Fundamenta", "Fundamenta"): (False, "Fundamenta es la empresa (actor), no un proyecto especifico por si sola"),
    ("Parque Bicentenario Cerrillos", "Proyecto Bicentenario"): (False, "Bicentenario generico"),
    ("Ciudad Portal Bicentenario", "Proyecto Bicentenario"): (False, "Bicentenario generico"),
    ("Centro Cívico del Portal Bicentenario", "Proyecto Bicentenario"): (False, "Bicentenario generico + sub-instalacion"),
    ("dos torres en los terrenos del Hotel Sheraton", "Hotel Sheraton"): (False, "proyecto de construccion nuevo distinto al hotel existente"),
    ("Hotel Sheraton", "Hotel Sheraton San Cristóbal"): (False, "posible hotel/torre especifica distinta, sin evidencia suficiente"),
    ("Intercontinental", "Hotel Intercontinental Santiago"): (True, "mismo hotel"),
    ("Crowne Plaza", "Galería de los Músicos del Crowne Plaza"): (False, "instalacion especifica dentro del hotel"),
    ("Alameda-Providencia", "Nueva Alameda Providencia"): (True, "mismo proyecto de corredor"),
    ("Nueva Alameda Providencia", "Nueva Alameda Providencia (NAP)"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] NAP es el acronimo explicito de Nueva Alameda Providencia; ambas fuentes describen la estrategia del mismo eje Alameda-Providencia."),
    ("Alameda-Providencia", "Eje Alameda-Providencia"): (True, "mismo corredor"),
    ("La Farfana", "Planta de Tratamiento de Aguas Servidas en La Farfana"): (True, "misma planta"),
    ("ex Escuela Rebeca Catalán Vargas", "ex Escuela Rebeca Catalán"): (True, "misma escuela, nombre truncado"),
    ("Edificio Pajaritos", "Habilitación del corredor de transporte público Pedro Aguirre Cerda — Tramo Alameda Pajaritos"): (False, "tipo de proyecto distinto: edificio vs corredor de transporte"),
    ("Hospital del Salvador", "hospital El Salvador de Providencia"): (True, "mismo hospital"),
    ("La Florida", "Florida Center"): (False, "La Florida es la comuna, demasiado generico"),
    ("La Florida", "Automac de McDonald’s en La Florida"): (False, "comuna generica"),
    ("La Florida", "Portal La Florida"): (False, "comuna generica"),
    ("La Florida", "inmueble de La Florida (ubicado en calle Millalongo)"): (False, "comuna generica"),
    ("Monjitas 565", "torre de 13 pisos en la calle Monjitas 565"): (True, "misma direccion exacta"),
    ("Centro de Eventos", "Centro de Eventos Espacio Riesco"): (False, "Centro de Eventos es termino generico"),
    ("proyecto Bellavista", "casa de dos pisos de calle Bellavista"): (False, "propiedad pequeña sin relacion evidente con el proyecto de torres"),
    ("proyecto Bellavista", "torres en el barrio Bellavista"): (True, "coincide con las tres torres del complejo Universidad San Sebastian"),
    ("proyecto Bellavista", "edificio de Desarrollo Inmobiliario Bellavista"): (True, "Desarrollo Inmobiliario Bellavista S.A. es la empresa del mismo proyecto, ya identificada en esta sesion"),
    ("proyecto Bellavista", "proyecto del terreno en Bellavista"): (True, "descripcion generica del mismo proyecto"),
    ("proyecto Bellavista", "una especie de mall del Fondo de Inversión Inmobiliaria Cimenta en el barrio Bellavista"): (False, "desarrollador y tipo de proyecto distintos (Fondo Cimenta, no Desarrollo Inmobiliario Bellavista)"),
    ("ex clínica Sierra Bella", "Sierra Bella"): (True, "mismo sitio"),
    ("Villa Bicentenario", "Proyecto Bicentenario"): (False, "Bicentenario generico"),
    ("Edificio Parque San Cristóbal", "Edificio San Cristóbal"): (True, "mismo edificio"),
    ("San Cristóbal Tower", "Edificio San Cristóbal"): (True, "mismo edificio, nombre en ingles"),
    ("proyecto de la Inmobiliaria Mirador Oriente S.A. a emplazarse en su terreno de calle Vital Apoquindo", "Vital Apoquindo"): (False, "Vital Apoquindo es la calle, con multiples proyectos distintos encima"),
    ("Ciudad Parque Bicentenario", "Proyecto Bicentenario"): (False, "Bicentenario generico"),
    ("Ciudad Parque Bicentenario", "Parque Bicentenario"): (False, "Ciudad Parque Bicentenario (Huechuraba) y Parque Bicentenario Cerrillos son desarrollos distintos y conocidos"),
    ("Unidad Vecinal Providencia", "Proyecto Vecinal"): (False, "Proyecto Vecinal es termino generico"),
    ("Proyecto de las 54 Casas", "Loteo 54 casas"): (True, "mismo proyecto de 54 casas"),
    ("Proyecto de las 54 Casas", "54 casas del Cerro del Medio"): (True, "mismo proyecto de 54 casas"),
    ("Loteo de las 54 Casas", "Proyecto de las 54 Casas"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] El Tribunal Ambiental usa 'Loteo de las 54 Casas' y 'Proyecto de las 54 Casas' para el mismo titular Miradores de La Dehesa SpA y la causa R-373-2022."),
    ("El Castillo", "Castillo Hidalgo"): (False, "nombres distintos, sin evidencia de ser el mismo sitio"),
    ("Granja Educativa Terra Viva", "La Granja"): (False, "La Granja es la comuna, generico"),
    ("el pique que se hará en el Parque Forestal", "Parque Forestal"): (False, "Parque Forestal es un lugar con multiples intervenciones especificas distintas"),
    ("Villa San Luis", "Villa Compañero Ministro Carlos Cortés (Villa San Luis)"): (True, "mismo caso historico Villa San Luis"),
    ("Vespucio 345", "Switch Vespucio 345"): (True, "misma direccion"),
    ("Mall Vivo", "Mall Vivo Los Trapenses"): (False, "local distinto de la misma cadena"),
    ("La Molina", "Población Abate Molina"): (False, "nombres distintos, sin evidencia de ser el mismo sitio"),
    ("Portal Bicentenario", "Proyecto Bicentenario"): (False, "Bicentenario generico"),
    ("Fundamenta", "proyecto inmobiliario de Fundamenta en Ñuñoa"): (False, "Fundamenta es la empresa, no un proyecto especifico por si sola"),
    ("Fundamenta", "proyecto inmobiliario de Fundamenta"): (False, "Fundamenta es la empresa"),
    ("Fundamenta", "megaproyecto de 4 torres de viviendas, oficinas y locales comerciales de la Inmobiliaria Fundamenta"): (False, "Fundamenta es la empresa"),
    ("Fundamenta", "4 torres de Fundamenta en Ñuñoa"): (False, "Fundamenta es la empresa"),
    ("edificio de la estrecha calle Santa Petronila", "edificio Santa Petronila"): (True, "mismo edificio"),
    ("Alto Las Condes 2", "Mall Alto Las Condes 2"): (True, "misma expansion, ambos comparten el numeral 2"),
    ("Vespucio Oriente", "Autopista Vespucio Oriente"): (True, "misma autopista"),
    ("Vespucio Oriente", "Américo Vespucio Oriente (AVO)"): (True, "misma autopista, nombre oficial completo"),
    ("Villa Compañero Ministro Carlos Cortés (Villa San Luis)", "Villa Compañero Ministro Carlos Cortés"): (True, "mismo nombre sin la aclaracion parentetica"),
    ("Edificio Capital", "Parque Capital"): (False, "nombres y tipo de desarrollo distintos, incierto"),
    ("La Cumbre", "Cumbre Mirador"): (False, "nombre distinto, incierto"),
    ("Proyecto Zoccalo de Vitacura", "Zoccalo"): (True, "misma concesionaria/proyecto"),
    ("Proyecto Bicentenario", "clínica Bicentenario"): (False, "Bicentenario generico"),
    ("Proyecto Bicentenario", "Parque Bicentenario"): (False, "Bicentenario generico"),
    ("Proyecto Bicentenario", "Moneda Bicentenario"): (False, "Bicentenario generico"),
    ("Parque Cerro Colorado", "El Colorado"): (False, "El Colorado es un centro de ski conocido, no el mismo sitio"),
    ("Hotel Sheraton San Cristóbal", "Edificio San Cristóbal"): (False, "edificios distintos"),
    ("nuevo proyecto para el Museo de Arte Contemporáneo y ensanche del Parque Forestal", "Parque Forestal"): (False, "Parque Forestal generico, multiples intervenciones distintas"),
    ("Rancagua Express", "Proyecto Metro Tren Santiago-Nos (Rancagua Express)"): (True, "mismo proyecto de tren"),
    ("Edificio San Cristóbal", "Túnel San Cristóbal"): (False, "tipo de proyecto distinto: edificio vs tunel"),
    ("Parque Forestal", "“Castillito” Parque Forestal"): (False, "Parque Forestal generico, Castillito es una instalacion especifica"),
    ("Aldea del Encuentro", "El encuentro"): (False, "nombres distintos, incierto"),
    ("proyecto en calle Cerro Colorado", "El Colorado"): (False, "El Colorado es el centro de ski, no la calle Cerro Colorado"),
    ("Desarrollo Urbano Habitacional Maratué de Puchuncaví", "Maratué"): (True, "mismo proyecto"),
    ("Vicuña Mackenna 385", "edificio de 14 pisos en Vicuña Mackenna 385"): (True, "misma direccion exacta"),
    ("Vital Apoquindo números 1.400, 1450 y 1.500", "Proyecto de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500"): (True, "mismas direcciones exactas, mismo proyecto de 25 edificios"),

    # [CORRECCION 2026-09-18] Los 31 pares siguientes fueron auditados de forma
    # independiente por la revisión (GPT-5.6) sobre el paquete completo de 253 pares con
    # evidencia real (project_review_queue_para_revision_sol.json), y CADA UNO fue
    # reverificado por Claude contra la evidencia real (comuna/direccion/URL) antes
    # de aplicar la correccion -- no se acepto el veredicto de la revisión a ciegas. Las 31
    # entradas de abajo SOBRESCRIBEN una decision anterior (ya sea de una regla
    # automatica o de una entrada manual anterior en este mismo diccionario) --
    # Python usa el ultimo valor de una clave duplicada en un dict literal, asi que
    # estas entradas ganan sobre cualquier definicion anterior con la misma clave.
    # Patron de error real encontrado y corregido: has_conflicting_numeral() trataba
    # numeros de DIRECCION ("General Amengual 480", "Pajaritos 4600", "Vital
    # Apoquindo 1400-1500") igual que numeros de ETAPA/FASE, bloqueando fusiones
    # correctas; y el principio "nombre de empresa/institucion != proyecto" (ya
    # aplicado bien a Fundamenta en general) no se aplico consistentemente a Nueva
    # El Golf ni a Universidad San Sebastian.
    ("General Amengual", "edificio de 38 pisos y más de 300 departamentos ubicado en calle General Amengual 480"): (True, "[Sol+Claude 2026-09-18, idx original 4] Debería ser 'merged'. La evidencia apunta al mismo edificio: en proyecto A aparece 'Edificio General Amengual' y la ubicación exacta calle General Amengual 480; proyecto B describe el edificio de 38 pisos en esa misma dirección. El 480 es una dirección, no una etapa o fase."),
    ("Rotonda Atenas", "proyecto social de 2023 de la rotonda Atenas"): (False, "[Sol+Claude 2026-09-18, idx original 6] Debería ser 'kept_separate'. La evidencia distingue dos proyectos de vivienda social en Las Condes: el caso histórico Rotonda Atenas/Manquehue-Nueva Delhi y otro proyecto de 2023 en Cerro Colorado 4661, cerca de Parque Arauco. No deben fusionarse por compartir la referencia genérica a Rotonda Atenas."),
    ("Edificio Pajaritos", "Pajaritos 4600"): (True, "[Sol+Claude 2026-09-18, idx original 13] Debería ser 'merged'. Edificio Pajaritos y Pajaritos 4600 son el mismo proyecto: varias fuentes de A lo ubican explícitamente en Avenida Pajaritos 4600, junto a Metro Monte Tabor, que coincide con B. El numeral es la dirección."),
    ("Mall Vivo Santiago Etapa II", "Mall Vivo"): (True, "[Sol+Claude 2026-09-18, idx original 28] Debería ser 'merged'. La evidencia del nombre genérico 'Mall Vivo' en el corpus lo sitúa en Ñuñoa, Vicuña Mackenna/Carlos Dittborn, y la contraparte corresponde al mismo proyecto Mall Vivo Santiago/Etapa II. En este corpus la mención genérica está contextualizada al mismo caso."),
    ("Mall Vivo Santiago Etapa II", "Mall Vivo Santiago"): (True, "[Sol+Claude 2026-09-18, idx original 30] Debería ser 'merged'. Mall Vivo Santiago y Mall Vivo Santiago Etapa II remiten al mismo proyecto en Ñuñoa, en los ex terrenos de Copesa/Vicuña Mackenna-Carlos Dittborn, y al mismo conflicto ambiental. 'Etapa II' funciona aquí como denominación formal/fase del mismo caso, no como proyecto independiente."),
    ("Urbanya Etapa I", "Urbanya"): (True, "[Sol+Claude 2026-09-18, idx original 36] Debería ser 'merged'. Urbanya Etapa I y Urbanya corresponden al mismo desarrollo en El Noviciado, Pudahuel, y al mismo conflicto. La etiqueta de etapa no justifica separar el caso de su proyecto matriz en esta capa de resolución de casos."),
    ("Mall Vivo", "Mall Vivo Ñuñoa"): (True, "[Sol+Claude 2026-09-18, idx original 37] Debería ser 'merged'. El 'Mall Vivo' genérico de la evidencia está contextualizado en Ñuñoa y coincide con el mismo Mall Vivo Santiago. Separarlo solo por el uso abreviado del nombre fragmenta un mismo caso."),
    ("Mall Vivo", "Centro Comercial Mall Vivo Santiago Etapa II"): (True, "[Sol+Claude 2026-09-18, idx original 38] Debería ser 'merged'. La fase 'Etapa de Demolición, Excavación y Socalzados' pertenece al mismo Mall Vivo Santiago en Ñuñoa; es una fase constructiva del mismo proyecto/caso, no un proyecto autónomo."),
    ("Mall Vivo", "Mall Vivo Santiago: Etapa de Demolición, Excavación y Socalzados"): (True, "[Sol+Claude 2026-09-18, idx original 39] Debería ser 'merged'. El 'Mall Vivo' genérico está contextualizado en el mismo emplazamiento de Ñuñoa; la denominación formal de Etapa II no constituye evidencia suficiente de un proyecto distinto."),
    ("Mall Vivo", "Mall Vivo Santiago"): (True, "[Sol+Claude 2026-09-18, idx original 41] Debería ser 'merged'. Mall Vivo y Mall Vivo Santiago, dentro de la evidencia disponible, apuntan al mismo proyecto de Ñuñoa en Vicuña Mackenna/Carlos Dittborn. La separación por nombre genérico produciría duplicación del mismo caso."),
    ("Edificio Capital", "Condominio Eco Capital"): (True, "[Sol+Claude 2026-09-18, idx original 55] Debería ser 'merged'. Edificio Capital y Condominio Eco Capital aparecen en el mismo artículo y en la misma dirección, Conde de Maule N°4106. La evidencia favorece fuertemente que sean variantes del mismo proyecto."),
    ("Eco Egaña", "Eco Egaña Poniente"): (True, "[Sol+Claude 2026-09-18, idx original 60] Debería ser 'merged'. Eco Egaña y Eco Egaña Poniente aparecen como variantes del mismo conflicto/proyecto de Fundamenta en el entorno de Plaza Egaña. La evidencia no documenta dos proyectos independientes."),
    ("Centro de Salud Familiar (Cesfam)", "tercer Centro de Salud Familiar (Cesfam) de Las Condes"): (True, "[Sol+Claude 2026-09-18, idx original 61] Debería ser 'merged'. El CESFAM genérico está ubicado en calle Nueva Delhi y el 'tercer CESFAM de Las Condes' en Manquehue con Nueva Delhi, dentro del mismo conflicto por el inmueble/paño. La coincidencia espacial y contextual apoya la fusión."),
    ("calle Vital Apoquindo 1.400-1.450-1.500", "Vital Apoquindo"): (True, "[Sol+Claude 2026-09-18, idx original 68] Debería ser 'merged'. Vital Apoquindo y la variante con numeración corresponden al mismo desarrollo: la evidencia ubica el proyecto en el tramo 1400-1500 de Vital Apoquindo. Los números son direcciones, no fases."),
    ("Las Américas", "Colegio Las Américas"): (True, "[Sol+Claude 2026-09-18, idx original 69] Debería ser 'merged'. Las Américas y Colegio Las Américas refieren al mismo inmueble/proyecto en el sector Larraín-María Monvel/Aldea del Encuentro. La forma corta queda suficientemente contextualizada por ubicación."),
    ("proyecto de Inmobiliaria Nueva El Golf", "proyecto que impulsa la inmobiliaria Nueva El Golf"): (False, "[Sol+Claude 2026-09-18, idx original 85] Debería ser 'kept_separate'. La relación común es la inmobiliaria Nueva El Golf, no necesariamente el mismo proyecto. La evidencia contiene proyectos en ubicaciones distintas; fusionarlos convertiría identidad del desarrollador en identidad del proyecto."),
    ("proyecto de Inmobiliaria Nueva El Golf", "Nueva El Golf"): (False, "[Sol+Claude 2026-09-18, idx original 86] Debería ser 'kept_separate'. 'Nueva El Golf' funciona como nombre de la inmobiliaria/desarrollador y no como un proyecto único. La evidencia abarca desarrollos distintos, por lo que no debe usarse como alias de un caso específico."),
    ("planta de tratamiento de aguas servidas de la Empresa San Isidro", "San Isidro"): (False, "[Sol+Claude 2026-09-18, idx original 101] Debería ser 'kept_separate'. 'San Isidro' es ambiguo. Un lado refiere a una planta de tratamiento de aguas servidas/Empresa San Isidro y el otro contiene menciones que no prueban que se trate de esa misma planta. No hay evidencia suficiente para fusionar."),
    ("calle Toro Mazotte", "cuatro megaedificios ubicados en calle Toro Mazotte"): (False, "[Sol+Claude 2026-09-18, idx original 104] Debería ser 'kept_separate'. 'Toro Mazotte' es una calle/sector y no identifica por sí solo un proyecto. Compartir la calle con cuatro megaedificios no prueba que las menciones sean el mismo caso."),
    ("Carlos Valdovinos", "tres torres de 15 pisos y dos subterráneos, cada uno en un sector de avenida Carlos Valdovinos"): (False, "[Sol+Claude 2026-09-18, idx original 121] Debería ser 'kept_separate'. Hay una contradicción geográfica fuerte: la evidencia de B sitúa las torres en Presidente Errázuriz/El Golf, Las Condes, mientras A corresponde al proyecto Carlos Valdovinos en otro contexto. Deben mantenerse separados."),
    ("proyecto inmobiliario de Fundamenta en Ñuñoa", "proyecto inmobiliario de Fundamenta"): (False, "[Sol+Claude 2026-09-18, idx original 124] Debería ser 'kept_separate'. La coincidencia es principalmente el desarrollador Fundamenta. La evidencia de B identifica un proyecto en Simón Bolívar/Suecia/José Artigas/Sucre, y el corpus contiene otros proyectos de Fundamenta; no basta para fusionar con un proyecto genérico de Ñuñoa."),
    ("Universidad San Sebastián", "Proyecto de la Universidad San Sebastián en la manzana delimitada por las calles Bellavista, Ernesto Pinto Lagarrigue, Dardignac y Pío Nono"): (False, "[Sol+Claude 2026-09-18, idx original 139] Debería ser 'kept_separate'. 'Universidad San Sebastián' es una institución/actor; el otro nombre es un proyecto físico específico de la USS en Bellavista. No conviene fusionar la entidad institucional con el proyecto."),
    ("Nueva El Golf", "proyecto que impulsa la inmobiliaria Nueva El Golf"): (False, "[Sol+Claude 2026-09-18, idx original 140] Debería ser 'kept_separate'. 'Nueva El Golf' es la inmobiliaria/desarrollador, mientras el otro nombre refiere a un proyecto impulsado por esa empresa. Actor y proyecto deben mantenerse separados."),
    ("Barrio Maestranza 1", "barrio Maestranza"): (False, "[Sol+Claude 2026-09-18, idx original 145] Debería ser 'kept_separate'. 'Barrio Maestranza' es demasiado genérico y la evidencia apunta a sectores distintos (Santiago Watt/Exposición versus San Eugenio y eje Santiago-Pedro Aguirre Cerda). No hay identidad de proyecto demostrada."),
    ("Barrio Parque", "Barrio Parque de Quinta Normal"): (False, "[Sol+Claude 2026-09-18, idx original 192] Debería ser 'kept_separate'. Las ubicaciones corresponden a barrios/proyectos distintos: uno en el entorno Alameda-San Alberto Hurtado/Las Rejas y otro en Quinta Normal (Carrascal/Poeta Pedro Prado). El nombre genérico 'Barrio Parque' no basta para fusionarlos."),
    ("Parque Bicentenario Cerrillos", "Parque Bicentenario"): (False, "[Sol+Claude 2026-09-18, idx original 194] Debería ser 'kept_separate'. Parque Bicentenario Cerrillos y el Parque Bicentenario de Vitacura son espacios distintos. La evidencia de B lo ubica en la ribera sur del Mapocho/Tabancura, incompatible con el ex aeropuerto de Cerrillos."),
    ("Hospital del Salvador", "nuevo Hospital del Salvador"): (False, "[Sol+Claude 2026-09-18, idx original 212] Debería ser 'kept_separate'. La evidencia disponible no sostiene que el 'nuevo Hospital del Salvador' de B sea el mismo proyecto de A; B lo ubica en Grecia/Los Jardines en un contexto distinto. La fusión es demasiado agresiva."),
    ("Mall Vivo Santiago", "Centro Comercial Mall Vivo Santiago Etapa II"): (True, "[Sol+Claude 2026-09-18, idx original 248] Debería ser 'merged'. Mall Vivo Santiago y Centro Comercial Mall Vivo Santiago Etapa II comparten emplazamiento y conflicto en Ñuñoa. La denominación de Etapa II no justifica un case_id separado en esta capa."),
    ("Vital Apoquindo", "Proyecto de 25 edificios en calle Vital Apoquindo números 1.400, 1450 y 1.500"): (True, "[Sol+Claude 2026-09-18, idx original 250] Debería ser 'merged'. Vital Apoquindo y la variante 1400 corresponden al mismo desarrollo en el tramo 1400-1500. El numeral es dirección."),
    ("Vital Apoquindo", "Vital Apoquindo números 1.400, 1450 y 1.500"): (True, "[Sol+Claude 2026-09-18, idx original 251] Debería ser 'merged'. Vital Apoquindo y la variante 1450/1500 corresponden al mismo desarrollo; la evidencia espacial las integra en el mismo proyecto/caso."),
    ("Vital Apoquindo", "proyecto de 25 edificios en la calle Vital Apoquindo"): (True, "[Sol+Claude 2026-09-18, idx original 252] Debería ser 'merged'. La descripción 'proyecto de 25 edificios en la calle Vital Apoquindo' pertenece al mismo conjunto de aliases Vital Apoquindo ya enlazado por direcciones 1400-1500. Mantenerlo separado rompería la coherencia transitiva del cluster."),

    # [CORRECCION 2026-09-18, segunda ronda] la revisión senalo (punto 6 de su segunda
    # revision) que has_conflicting_numeral() seguia decidiendo automaticamente
    # 9 pares mediante un numeral SUELTO (sin la palabra etapa/fase), el mismo
    # patron de bug ya corregido para otros pares -- la regla general no se
    # habia corregido, solo se habian agregado excepciones manuales puntuales.
    # Se corrigio la regla general (ver has_bare_trailing_numeral_conflict: ya
    # NO decide kept_separate automaticamente, manda a needs_human_review) y
    # estos 9 pares se revisaron uno por uno contra comuna/direccion real
    # antes de decidir -- 8 confirman kept_separate (evidencia geografica
    # incompatible o insuficiente), 1 se corrige a merged (hallazgo real
    # adicional de Claude durante esta verificacion, no reportado por la revisión: la
    # regla habia bloqueado por error la fusion de "Fase IV" con su propia
    # descripcion completa).
    ("edificio de 13 pisos", "torre de 13 pisos en la calle Monjitas 565"): (False, "[Claude 2026-09-18] kept_separate confirmado: A esta en avenida Lo Ovalle, B en un batiburrillo de ubicaciones (Las Condes/Monjitas 565/Barrio Yungay/V Region) que no coincide con Lo Ovalle. Coincidencia de '13 pisos' es casual, no de ubicacion."),
    ("Alto Las Condes", "Mall Alto Las Condes 2"): (False, "[Claude 2026-09-18] kept_separate confirmado: decision original deliberada (numero '2' indica fase/expansion distinta del mall existente, documentado ya en el patron 'Alto Las Condes vs Alto Las Condes 2' de la primera ronda de revision), B sin evidencia de ubicacion propia que la contradiga."),
    ("mall Alto Las Condes", "Mall Alto Las Condes 2"): (False, "[Claude 2026-09-18] kept_separate confirmado, mismo razonamiento que 'Alto Las Condes' vs 'Mall Alto Las Condes 2'."),
    ("Carlos Valdovinos", "Carlos Valdovinos 3017"): (False, "[Claude 2026-09-18] kept_separate confirmado: la evidencia de A (Parque Las Moscas; Alonso de Cordoba, Vitacura/Estacion Central) nunca confirma que A este realmente en la calle Carlos Valdovinos -- coherente con el hallazgo ya verificado en el par 'Carlos Valdovinos' vs 'tres torres...' (contradiccion geografica fuerte, El Golf/Las Condes). B (3017/3015/3005, sector Especial E2 del PRC de Santiago) es un desarrollo real y especifico distinto."),
    ("Carlos Valdovinos", "Carlos Valdovinos 3015"): (False, "[Claude 2026-09-18] kept_separate confirmado, mismo razonamiento que Carlos Valdovinos 3017."),
    ("Carlos Valdovinos", "Carlos Valdovinos 3005"): (False, "[Claude 2026-09-18] kept_separate confirmado, mismo razonamiento que Carlos Valdovinos 3017."),
    ("Cerro Colorado 4661", "El Colorado"): (False, "[Claude 2026-09-18] kept_separate confirmado: 'El Colorado' es el centro de ski (ya establecido en 2 decisiones manuales previas de esta misma lista), 'Cerro Colorado 4661' es una direccion real en Las Condes (el proyecto social 2023 de la rotonda Atenas, ya identificado en el par 'Rotonda Atenas' vs 'proyecto social de 2023')."),
    ("Edificio de viviendas de siete pisos en Toledo Nº 1950, 1960 y 1966", 'Toledo\u200b￼?'): (False, "[Claude 2026-09-18] kept_separate confirmado: el nombre B esta corrupto (texto basura con caracteres invisibles/de reemplazo, mismo patron de degeneracion de texto ya diagnosticado en otras partes del pipeline) y su evidencia real (Balmaceda/Santiago/Hualpen/Concepcion/Vina del Mar/Macul/Maipu) no tiene relacion con Toledo/Providencia de A."),
    ("Fase IV", "Radial Aeropuerto Nº 14080, Enea Fase IV, Lote 3E-2"): (True, "[Claude 2026-09-18] merged -- hallazgo real adicional (no reportado por Sol, encontrado por Claude al reverificar los pares gobernados por la regla de numeral suelto): A esta en 'Sector de ENEA (Pudahuel)', B es literalmente 'Enea Fase IV' -- mismo sector, misma fase. La regla anterior los separaba por error porque el numeral romano 'iv' de A no coincidia token a token con el resto de numeros de B (14080, 3E-2)."),

    # [AGREGADO 2026-09-18] KNOWN_HOMONYM_SPLITS en build_case_project_bridge.py
    # separo el project_id "San Isidro" (que antes mezclaba 2 ubicaciones
    # reales distintas, hallazgo del punto 8 de la revisión) en dos: "San Isidro"
    # (Toro Mazotte/Estacion Central) y "proyecto San Isidro" (Quilicura,
    # Estero Las Cruces). Esto genera un par NUEVO en la cola de 253 (ahora
    # 254) que no existia antes con esta granularidad: "planta de
    # tratamiento..." vs "proyecto San Isidro" (Quilicura). Se decide con la
    # misma evidencia ya verificada para el par original.
    ("planta de tratamiento de aguas servidas de la Empresa San Isidro", "proyecto San Isidro"): (True, "[Claude 2026-09-18, tras split del homonimo San Isidro] merged: 'proyecto San Isidro' quedo, tras separar el homonimo de Toro Mazotte, unicamente con el documento de Quilicura/Estero Las Cruces -- mismo emplazamiento que la planta de tratamiento de aguas servidas de la Empresa San Isidro."),

    # [AGREGADO 2026-09-18, tras aplicar la correccion completa de la revisión sobre
    # los 934 documentos] la revisión corrigio proyectos_mencionados del documento
    # de Cencosud en Argentina (el mismo ya identificado como
    # caso_focal_fuera_del_universo) de ["ex colegio Nuestra Senora del
    # Pilar", "Costanera Center"] a ["Proyecto de Cencosud en San Isidro"] --
    # nombre mas preciso, pero que ahora tiene relacion de substring con
    # los otros 2 "San Isidro" chilenos (Toro Mazotte/Estacion Central y
    # Quilicura/Estero Las Cruces, ya separados como homonimos). Un TERCER
    # "San Isidro" real: el barrio de Buenos Aires, Argentina -- nada que
    # ver con ninguno de los 2 anteriores. Mantener separado de ambos.
    ("Proyecto de Cencosud en San Isidro", "San Isidro"): (False, "[Claude 2026-09-18] kept_separate: 'San Isidro' aqui es un barrio de Buenos Aires, Argentina (proyecto de Cencosud) -- geograficamente incompatible con 'San Isidro' de Toro Mazotte/Estacion Central, Chile."),
    ("Proyecto de Cencosud en San Isidro", "proyecto San Isidro"): (False, "[Claude 2026-09-18] kept_separate: mismo razonamiento -- San Isidro, Buenos Aires, Argentina no tiene relacion con 'proyecto San Isidro' (planta de tratamiento de aguas servidas, Quilicura, Chile)."),

    # [AGREGADO 2026-09-18] Los 5 pares alias encontrados por la revisión al
    # clasificar los 63 documentos 'caso_unico' con >1 case_id (ver
    # MANUAL_EXTRA_REVIEW_PAIRS en build_case_project_bridge.py y
    # Auditoria/integracion_v1/candidatos_project_review_queue_desde_conflict_unit_63.json
    # para el provenance/evidencia completos con citas). Decisiones
    # tomadas por Claude releyendo directamente las citas verificadas de
    # cada par (no solo la justificacion resumida de la revisión) antes de
    # marcar merged.
    ("Villa San Luis", "Villa Carlos Cortés"): (True, "[Claude 2026-09-18, conflict_unit_63] merged: 2 documentos independientes (The Clinic, El Mostrador) describen a 'Villa Carlos Cortes'/'Villa Ministro Carlos Cortes' como el nombre historico original del mismo conjunto habitacional que hoy se conoce como Villa San Luis -- mismos actores (Miguel Lawner, CORMU, Ejercito, Inmobiliaria Parque San Luis), misma ubicacion Las Condes, misma trayectoria de demolicion/proteccion patrimonial. Ademas ya existian en el project_review_queue original 5 pares 'merged' que fusionan variantes con 'Ministro'/'Compañero Ministro' Carlos Cortes -- esta bare 'Villa Carlos Cortes' es la misma familia de alias que esas, solo que find_review_candidates() no la detecto por no compartir substring con 'Villa San Luis'."),
    ("Club de Golf Hacienda Santa Martina Nature - Lo Barnechea", "Hacienda Santa Martina, Nature Club & Golf"): (True, "[Claude 2026-09-18, conflict_unit_63] merged: ambos nombres refieren al mismo proyecto sujeto a la misma denuncia ambiental ante la Superintendencia del Medio Ambiente -- mismo actor (Inmobiliaria Santa Martina S.A.), misma Municipalidad de Lo Barnechea. Es la misma resolucion exenta citando el proyecto con 2 formas de titulo distintas."),
    ("Egaña Eco Sustentable", "Eco Egaña"): (True, "[Claude 2026-09-18, conflict_unit_63] merged: mismo actor (Inmobiliaria Fundamenta, Pablo Medina), misma causa judicial de recusacion contra el ministro Sergio Muñoz por intervencion de su hija -- 'Eco Egaña' es la forma abreviada de 'Egaña Eco Sustentable' dentro del mismo articulo/caso."),
    ("LA PLANTA DE CACA", "Solución transitoria para la provisión de los servicios de tratamiento y disposición de Aguas Servidas"): (True, "[Claude 2026-09-18, conflict_unit_63] merged: 'LA PLANTA DE CACA' es el apodo coloquial que la comunidad (Accion Vecinal, Resistencia Socioambiental Quilicura) usa para la misma planta de tratamiento de aguas servidas cuyo nombre formal en el SEA es 'Solucion transitoria para la provision de los servicios de tratamiento y disposicion de Aguas Servidas' -- mismo emplazamiento, mismos actores comunitarios opositores, mismo tramite ante el SEA."),
    ("Alto Las Condes 2", "Alto Norte"): (True, "[Claude 2026-09-18, conflict_unit_63] merged: la nota de Diario Financiero es explicita en que el desarrollo se denomina 'Alto Las Condes 2' en la prensa/negocio pero el litigio y el permiso municipal lo refieren como 'Alto Norte' -- mismo actor (Cencosud Shopping), mismo permiso impugnado ante la Municipalidad de Vitacura y la Corte Suprema."),

    # Las adjudicaciones de este bloque se apoyan en fulltexts locales hash-pinned,
    # no en similitud del nombre ni en transferencias desde casos vecinos.
    # Portal La Dehesa es el mall existente; el proyecto de ampliación "Alto Las
    # Condes 2" sigue separado de la entidad del mall existente.
    ("Portal La Dehesa", "Cenco Portal La Dehesa"): (True, "La Tercera nombra el centro existente como 'Portal La Dehesa (Cencosud)' e Infobae documenta la marca 'Cenco Portal La Dehesa'; se conserva la referencia a ambos textos locales y no se usa la URL externa anterior como si fuera el documento de La Tercera."),
    ("Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)", "Centro Nacional de Arte Contemporáneo Cerrillos"): (True, "Misma institución cultural ubicada en el antiguo edificio del aeropuerto de Cerrillos: una fuente desarrolla el nombre y su sigla CNAC; otra usa el mismo nombre sin la preposición. No se transfiere ninguna decisión de casos vecinos."),
    ("Flor del Valle", "proyecto de condominio de viviendas sociales Flor del Valle"): (True, "Mismo proyecto de vivienda social para familias de Maipú: TECHO lo identifica como 'proyecto de vivienda Flor del Valle' y una fuente local lo denomina 'proyecto de condominio de viviendas sociales Flor del Valle'."),
    ("Línea 3 de Metro", "Línea 3 del Metro de Santiago"): (True, "Misma línea de transporte: la SMA identifica el proyecto de Línea 3 de Metro y Emol describe la Línea 3 del Metro de Santiago en marcha blanca en La Reina."),
    ("Línea 3 de Metro", "nueva Línea 3 del Metro"): (True, "VCM Emol describe la nueva Línea 3, su extensión y estaciones; la SMA identifica el mismo proyecto de infraestructura como Línea 3 de Metro. Se reemplaza la antigua referencia a una página genérica de etiquetas USACH."),
    ("San Nicolás", "proyecto inmobiliario San Nicolás"): (True, "Mismo proyecto residencial de Delabase III en San Miguel: el Segundo Tribunal Ambiental identifica el proyecto San Nicolás y Ex-Ante atribuye el proyecto inmobiliario San Nicolás a Delabase III en esa comuna."),
    ("Supermercado Líder San Francisco", "supermercado Líder San Francisco de Walmart Chile"): (True, "Mismo supermercado de Pudahuel: Radio Universidad de Chile lo identifica como el supermercado Líder San Francisco de Walmart Chile; el otro registro usa el nombre abreviado del mismo activo."),
    ("Torres Alameda", "tres torres Alameda"): (True, "Mismo desarrollo de Su Ksa junto a Alameda Plaza: dos artículos de La Tercera repiten la descripción literal 'tres torres Alameda de la inmobiliaria Su Ksa'."),
    ("block 14 de la Villa San Luis", "block 14"): (True, "Mismo bloque físico de Villa San Luis: Radio JGM lo nombra como 'block 14 de la Villa San Luis'; La Tercera indica que el block 14 es el único edificio del conjunto que permanece en pie."),
    ("edificio de la UNCTAD III (hoy GAM)", "edificio UNCTAD III"): (True, "Mismo edificio histórico UNCTAD III; el primer nombre añade su denominación y uso actual como GAM, no otro inmueble."),
    ("proyecto de tres torres de 19 pisos cada una", "tres torres de 19 pisos"): (True, "[revision 2026-09-27, adjudicacion source-first de Codex/Luna] Pauta y La Tercera describen el desarrollo de DIB en Recoleta como tres torres de 19 pisos y la misma disputa en Dardignac."),
}


# Cada adjudicacion positiva incorporada en 2026-09-26 tiene dos referencias
# locales, una por cada project_id. Los hashes distinguen texto fuente e
# instancia JSON; no se interpretan por el nombre del archivo ni por una URL
# ajena al documento. El preflight valida estas referencias antes de escribir.
MANUAL_DECISION_EVIDENCE: dict[tuple[str, str], dict[str, Any]] = {
    ("Portal La Dehesa", "Cenco Portal La Dehesa"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "378e8d25e8e3edf01183be0f", "project_name": "Portal La Dehesa", "raw_mention": "Portal La Dehesa", "document_id": "05e34b61d5c8ea47f96c686fb249ad34395e81113cc82c457f36eb8f078445ce", "url": "https://www.latercera.com/la-tercera-pm/noticia/14-edificios-y-dos-centros-comerciales-el-megaproyecto-inmobiliario-de-schiess-en-pausa-en-lo-barnechea/7WFDO7MBGVH7TNTLWJJ7NH3W6M/", "content_file": "Fuentes/fulltext/content/daac0305347d918de647e225877ec0f7691562932c1c7ca5559d645b7241ed1b.json", "source_text_sha256": "05e34b61d5c8ea47f96c686fb249ad34395e81113cc82c457f36eb8f078445ce", "content_record_sha256": "aca259f4e384f1753ec4242b667f6a674fd570e9607dc446ed4969aba9f9f530", "quote": "Esto, si se considera a Portal La Dehesa (Cencosud)"},
            {"project_id": "d345a25ce92499d24ad13a08", "project_name": "Cenco Portal La Dehesa", "raw_mention": "Cenco Portal La Dehesa", "document_id": "415ddc301212a5f3478237b33d46344a30ccc9d8de8ac6d6a4bebebd0e5c8200", "url": "https://www.infobae.com/peru/2025/12/04/cencosud-cancela-la-construccion-de-uno-de-sus-centros-comerciales-mas-ambiciosos/", "content_file": "Fuentes/fulltext/content/b11ecb98e7a1105e6f9b8ae3dd372aac0a01e839c4c70f648462b5c97fb50a10.json", "source_text_sha256": "415ddc301212a5f3478237b33d46344a30ccc9d8de8ac6d6a4bebebd0e5c8200", "content_record_sha256": "575d85ed16a0cae4709889108477e134cb719f12f95cf809ddc59b194be3db22", "quote": "Cenco Portal La Dehesa"},
        ],
    },
    ("Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)", "Centro Nacional de Arte Contemporáneo Cerrillos"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "7118b7a4dde32efbb6d1a4b5", "project_name": "Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)", "raw_mention": "Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)", "document_id": "e0b6c752c9d0070e77b69e77d5a84f0b8a0694c7eda40fe2eb47fcca20b85851", "url": "https://artishockrevista.com/2019/05/17/centro-nacional-de-arte-cerrillos-tomas-fontecilla/", "content_file": "Fuentes/fulltext/content/a5fa37ec650ead32792f7f1c56c75523d73ece8b0a8b42537f6722136de194af.json", "source_text_sha256": "e0b6c752c9d0070e77b69e77d5a84f0b8a0694c7eda40fe2eb47fcca20b85851", "content_record_sha256": "a3ae9c1763077102d306a9b87c05f162cf318d505d5db685130fcff9194df579", "quote": "Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)"},
            {"project_id": "58301ba7dde63dc4c91fbb38", "project_name": "Centro Nacional de Arte Contemporáneo Cerrillos", "raw_mention": "Centro Nacional de Arte Contemporáneo Cerrillos", "document_id": "f1428060a0cd9a8749e6ccb86993e4f4f2fa4814769e5ac51d4140758294badd", "url": "https://urbano.wikiexplora.com/Parque_Bicentenario_Cerrillos", "content_file": "Fuentes/fulltext/content/b3b8d229294944cc976a7455bb2e27678896b71353645191072677b6c7ff52ea.json", "source_text_sha256": "f1428060a0cd9a8749e6ccb86993e4f4f2fa4814769e5ac51d4140758294badd", "content_record_sha256": "4ec1a6ed8716a1ff5c8f4b9d7d3ec2513181fdf1dbec90339155ccf2fb6efd2b", "quote": "Estación 2: Centro Nacional de Arte Contemporáneo Cerrillos"},
        ],
    },
    ("Flor del Valle", "proyecto de condominio de viviendas sociales Flor del Valle"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "cc06d5ea5e77c8c4e0bbee16", "project_name": "Flor del Valle", "raw_mention": "Flor del Valle", "document_id": "54cb746fcbf382396bfe15118afcc796553cc39991b1192489f85a0b2c4a152a", "url": "https://cl.techo.org/entrega-de-proyecto-flor-del-valle/", "content_file": "Fuentes/fulltext/content/d6c8f2b1f6f0d782fd70fda0331283b549258304320f7f12bb19829992218afe.json", "source_text_sha256": "54cb746fcbf382396bfe15118afcc796553cc39991b1192489f85a0b2c4a152a", "content_record_sha256": "20f4d555ea05bfa32d9ec29eccddcca42ed59d4783087b69556f567a457f749f", "quote": "entregamos el proyecto de vivienda Flor del Valle, para 104 familias de los campamentos La Isla y Pueblito la Farfana de Maipú"},
            {"project_id": "1306ef2f8017be09c7a6591e", "project_name": "proyecto de condominio de viviendas sociales Flor del Valle", "raw_mention": "proyecto de condominio de viviendas sociales Flor del Valle", "document_id": "1db5406b237c5d2f53dd5c987323ee7db803c8570e982b4fb303af19d500dd42", "url": "https://www.labatalla.cl/conociendo-a-carlos-carvacho-candidato-a-concejal-de-maipu/", "content_file": "Fuentes/fulltext/content/0fa3707fafb230e36db18067cb77dceacfbd7e5d8727dce5af3b015866fca532.json", "source_text_sha256": "1db5406b237c5d2f53dd5c987323ee7db803c8570e982b4fb303af19d500dd42", "content_record_sha256": "14303af65be998cecadce2d01cb6552403f504722a18391ab65480b0d6d93bb5", "quote": "proyecto de condominio de viviendas sociales Flor del Valle"},
        ],
    },
    ("Línea 3 de Metro", "Línea 3 del Metro de Santiago"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "e456549a9815284f66aeb631", "project_name": "Línea 3 de Metro", "raw_mention": "Línea 3 de Metro", "document_id": "4a101509be1d8631632fd2d617fc853c9135eaa53ba1abcd30d2f541d2eb04e9", "url": "https://portal.sma.gob.cl/index.php/sma-formula-cargos-por-ruido-contra-proyecto-linea-3-de-metro/", "content_file": "Fuentes/fulltext/content/c5a07447d2798c2ec5921ca0c1b1a077f57221cb5764bb5df2678f3733e0eb7e.json", "source_text_sha256": "4a101509be1d8631632fd2d617fc853c9135eaa53ba1abcd30d2f541d2eb04e9", "content_record_sha256": "9684fe947b1dedd239dac000552e2e0f53b407c712b2d11f3c69a66aa44b3643", "quote": "Línea 3 de Metro"},
            {"project_id": "c842b3fe450afe684c1bfb14", "project_name": "Línea 3 del Metro de Santiago", "raw_mention": "Línea 3 del Metro de Santiago", "document_id": "e12e4c1b0ddd3d0689e8cc09508f6dadde58aa2976b51d5851517d23cde698d1", "url": "https://www.emol.com/noticias/Nacional/2019/01/21/935071/Vecinos-de-La-Reina-presentan-recurso-contra-Metro-por-vibraciones-y-ruido-de-la-Linea-3.html", "content_file": "Fuentes/fulltext/content/f0c886e788e110c3bd07f250fc7112fdb2ce84e9de251ef0bb847c7a61002b33.json", "source_text_sha256": "e12e4c1b0ddd3d0689e8cc09508f6dadde58aa2976b51d5851517d23cde698d1", "content_record_sha256": "a505daa8f0cd8c577918e07c119d17fc4e7c55306d540adc603a080ad22489c9", "quote": "la Línea 3 del Metro de Santiago -que se encuentra en marcha blanca-"},
        ],
    },
    ("Línea 3 de Metro", "nueva Línea 3 del Metro"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "e456549a9815284f66aeb631", "project_name": "Línea 3 de Metro", "raw_mention": "Línea 3 de Metro", "document_id": "4a101509be1d8631632fd2d617fc853c9135eaa53ba1abcd30d2f541d2eb04e9", "url": "https://portal.sma.gob.cl/index.php/sma-formula-cargos-por-ruido-contra-proyecto-linea-3-de-metro/", "content_file": "Fuentes/fulltext/content/c5a07447d2798c2ec5921ca0c1b1a077f57221cb5764bb5df2678f3733e0eb7e.json", "source_text_sha256": "4a101509be1d8631632fd2d617fc853c9135eaa53ba1abcd30d2f541d2eb04e9", "content_record_sha256": "9684fe947b1dedd239dac000552e2e0f53b407c712b2d11f3c69a66aa44b3643", "quote": "Línea 3 de Metro"},
            {"project_id": "49f1d8ab180d18d361bb2b67", "project_name": "nueva Línea 3 del Metro", "raw_mention": "nueva Línea 3 del Metro", "document_id": "b68e4bf5677760b6306cd4f9545239834fdb9fd0d7bf245ce95039ed8de32e6d", "url": "https://vcm.emol.com/4365/noticias/experto-valora-que-no-se-aplace-la-inauguracion-de-la-linea-3-del-metro-pese-a-reclamos-de-vecinos/", "content_file": "Fuentes/fulltext/content/4891dc6d9c29164b8d29f84a8bf9e8328605a61ca0b51a1a5df77eeecca8b299.json", "source_text_sha256": "b68e4bf5677760b6306cd4f9545239834fdb9fd0d7bf245ce95039ed8de32e6d", "content_record_sha256": "aed2a58883a7b6b790aefaf43cf5ecf9784a476578b417236f7dc15913342c29", "quote": "el estreno de la nueva Línea 3 del Metro, que incluye una extensión de 22 kilómetros, con 18 estaciones"},
        ],
    },
    ("San Nicolás", "proyecto inmobiliario San Nicolás"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "1ef9a6090c8fed40c1289147", "project_name": "San Nicolás", "raw_mention": "San Nicolás", "document_id": "1efad5e5d1644ba0ce0880f146d307241eeb72c3f927a8b1e32aa2362d727033", "url": "https://tribunalambiental.cl/sentencia-r-463-2024-proyecto-inmobiliario-en-san-miguel", "content_file": "Fuentes/fulltext/content/bddecebeebbe09c1d121a542fc4a914cd4e435d39e9b5a6796f8314456665da5.json", "source_text_sha256": "1efad5e5d1644ba0ce0880f146d307241eeb72c3f927a8b1e32aa2362d727033", "content_record_sha256": "1f11b45809a0212b0b0cc0e9bc1549e21a9eda23410def339d9191f956b5d362", "quote": "el proyecto inmobiliario “San Nicolás”, ubicado en dicha comuna de la región Metropolitana"},
            {"project_id": "cc283a51b0c5fb88ffa32953", "project_name": "proyecto inmobiliario San Nicolás", "raw_mention": "proyecto inmobiliario San Nicolás", "document_id": "0cbc85c7a802a791483fae5cdea69c7808eb8fac80a2d858e8d9bab7a7015fda", "url": "https://x.com/exantecl/status/1959941577087877440", "content_file": "Fuentes/fulltext/content/dd294d30c41433fa1527e72657195391b25c0ec51dce5602eaee65a191002f2a.json", "source_text_sha256": "0cbc85c7a802a791483fae5cdea69c7808eb8fac80a2d858e8d9bab7a7015fda", "content_record_sha256": "3e98eac9264880c83a253cb438d9e03f4e60316c416df9862f3108075238bca0", "quote": "El proyecto inmobiliario San Nicolás, impulsado por la Inmobiliaria y Constructora Delabase III en la comuna de San Miguel"},
        ],
    },
    ("Supermercado Líder San Francisco", "supermercado Líder San Francisco de Walmart Chile"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "0913ce433cf7906fb082e70c", "project_name": "Supermercado Líder San Francisco", "raw_mention": "Supermercado Líder San Francisco", "document_id": "86403e92169aadc3b6d8fac3a53a19321d7c7292d5a9b15f4c5c519713d328c4", "url": "https://eldesconcierto.cl/2019/03/23/despelote-total-en-la-comuna-de-pudahuel", "content_file": "Fuentes/fulltext/content/2c1d4382ada0a4329caec6ef7ce6f4275c9fc8f9f0f76b005ed1934a0179f8b8.json", "source_text_sha256": "86403e92169aadc3b6d8fac3a53a19321d7c7292d5a9b15f4c5c519713d328c4", "content_record_sha256": "a3fda26d0aa95414cc81df7a7efe3afbf377a88086f2e9187693949c8562caa0", "quote": "el supermercado Líder San Francisco, proyectos de la empresa Bodegas San Francisco"},
            {"project_id": "b44b728dbea54c5543970e73", "project_name": "supermercado Líder San Francisco de Walmart Chile", "raw_mention": "supermercado Líder San Francisco de Walmart Chile", "document_id": "f82135e32d545685995d1b166aa69c0b5022849afad2c16f77394c770a96b5ec", "url": "https://radio.uchile.cl/2021/07/19/matriz-de-walmart-en-ee-uu-impartira-clases-de-etica-comercial-a-walmart-chile/", "content_file": "Fuentes/fulltext/content/fa36fc7bd69cdabf9a9b1a4688be10a0c643812218445f9661a647f1d7407cf8.json", "source_text_sha256": "f82135e32d545685995d1b166aa69c0b5022849afad2c16f77394c770a96b5ec", "content_record_sha256": "844f830238d2bcfd4c4ec4b2aa239dbaf59699f72d7ed82cfcae114f779fa9ff", "quote": "el supermercado Líder San Francisco de Walmart Chile"},
        ],
    },
    ("Torres Alameda", "tres torres Alameda"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "3221064a885933e8f6ba63b2", "project_name": "Torres Alameda", "raw_mention": "Torres Alameda", "document_id": "cf871c7091dafecfbac7dfe5b2f12b78859d05d0d692954875b52f0675a220e5", "url": "https://www.latercera.com/paula/una-semana-viviendo-gueto-vertical/", "content_file": "Fuentes/fulltext/content/04b01e92a7c15712acbf3a86f6beffe086b63520cdade4df5dcc8d87bbdf7973.json", "source_text_sha256": "cf871c7091dafecfbac7dfe5b2f12b78859d05d0d692954875b52f0675a220e5", "content_record_sha256": "33dc86a66ee51a1dffae7d952a31c3b041be91f1030a6781c63e8ee6167ee5ef", "quote": "tres torres Alameda de la inmobiliaria Su Ksa junto al edificio Alameda Plaza"},
            {"project_id": "cdec0bfb572bc21f30fbda83", "project_name": "tres torres Alameda", "raw_mention": "tres torres Alameda", "document_id": "1b00c0136d4b855eed855b1a5f48ceb7f01e4c9b0d96c8d9666fafd292e043cb", "url": "https://www.latercera.com/pulso-pm/noticia/otra-constructora-en-crisis-upc-que-levanto-32-edificios-en-10-anos-pide-su-reorganizacion-y-registra-deudas-por-casi-10-mil-millones/Z43T42D6NNADVGW6WJAOFTSQPI/", "content_file": "Fuentes/fulltext/content/a352f3e81259a817f93a656f98cee307444ad25cdf8069646fd660633b7072b2.json", "source_text_sha256": "1b00c0136d4b855eed855b1a5f48ceb7f01e4c9b0d96c8d9666fafd292e043cb", "content_record_sha256": "e9cdfaf107588dedc67f934cfcae54ea7cc63298e98237856a63cd37d0092f64", "quote": "tres torres Alameda de la inmobiliaria Su Ksa junto al edificio Alameda Plaza"},
        ],
    },
    ("block 14 de la Villa San Luis", "block 14"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "f71d8d73041a68164ecd5413", "project_name": "block 14 de la Villa San Luis", "raw_mention": "block 14 de la Villa San Luis", "document_id": "4f6bfedb769650ad5d6e7ff0d0a665e4c0589271c691f216e5a10be062876381", "url": "https://radiojgm.uchile.cl/fundacion-villa-san-luis-el-consejo-de-monumentos-nacionales-baila-al-ritmo-de-las-inmobiliarias/", "content_file": "Fuentes/fulltext/content/35ec399a7ec1908d16cb367813b72bf0009e0ff52edad40fcd289dcaa4cd7b4c.json", "source_text_sha256": "4f6bfedb769650ad5d6e7ff0d0a665e4c0589271c691f216e5a10be062876381", "content_record_sha256": "a89e5da6e2d99f64eb383896989da0e783eee193ab19b03a944f541added06ee", "quote": "la demolición del block 14 de la Villa San Luis"},
            {"project_id": "526b792badf047862c170a4e", "project_name": "block 14", "raw_mention": "block 14", "document_id": "f8e60492003dda4a566ca0f20127ce0ca9169e6398285b0100a640a403d8f05a", "url": "https://www.latercera.com/nacional/noticia/patrimonio-ruinas-la-villa-san-luis-las-condes-se-niega-morir/808323/", "content_file": "Fuentes/fulltext/content/d525383ddec8ed609e2df90d3e306cb6e21c255115eb9e5e85f61754788db348.json", "source_text_sha256": "f8e60492003dda4a566ca0f20127ce0ca9169e6398285b0100a640a403d8f05a", "content_record_sha256": "d9e0197a41884989ca14f57459d1bd60010dae5a5912947ee02c1310c536624e", "quote": "En ese paño está el block 14, el único que queda en pie de los 27 edificios originales"},
        ],
    },
    ("edificio de la UNCTAD III (hoy GAM)", "edificio UNCTAD III"): {
        "source": "manual_adjudication",
        "references": [
            {"project_id": "49e36d5e154797526cb7ac7f", "project_name": "edificio de la UNCTAD III (hoy GAM)", "raw_mention": "edificio de la UNCTAD III (hoy GAM)", "document_id": "39001903d30d8d1e7c5822559143b132f268fb5b3e4ebf5c046e30eec94e3805", "url": "https://www.latercera.com/culto/2019/04/09/miguel-lawner-premio-2019/", "content_file": "Fuentes/fulltext/content/c0251b51795b6a6db317585d4a1c99da879077679010b578afe7f0bf1c7eff80.json", "source_text_sha256": "39001903d30d8d1e7c5822559143b132f268fb5b3e4ebf5c046e30eec94e3805", "content_record_sha256": "a094d4dc6dcaf7ff238357dfc118f5462fc3f964c6c7d580417bf248ea218a6f", "quote": "la construcción del edificio de la UNCTAD III, hoy GAM"},
            {"project_id": "e6e1dcbb49d300864229e9e5", "project_name": "edificio UNCTAD III", "raw_mention": "edificio UNCTAD III", "document_id": "8d7516a9774a5d4ebe5db68bb031b230f5e3ada0dd6a1af7ecbd16dbe2dd055a", "url": "https://www.urbanlivinglab.net/hospital-ochagavia/", "content_file": "Fuentes/fulltext/content/29b6dd9801c0f903809aa8e2da350a3b77d99ea6a671e9a83a353262c7d8869b.json", "source_text_sha256": "8d7516a9774a5d4ebe5db68bb031b230f5e3ada0dd6a1af7ecbd16dbe2dd055a", "content_record_sha256": "663e516c351114bda5d12032ebbc49486940d54641001ce7be9590a5df9988de", "quote": "construcción del edificio UNCTAD III"},
        ],
    },
}

REQUIRED_SOURCE_BACKED_MANUAL_PAIRS = frozenset(
    {
        ("Portal La Dehesa", "Cenco Portal La Dehesa"),
        ("Centro Nacional de Arte Contemporáneo de Cerrillos (CNAC)", "Centro Nacional de Arte Contemporáneo Cerrillos"),
        ("Flor del Valle", "proyecto de condominio de viviendas sociales Flor del Valle"),
        ("Línea 3 de Metro", "Línea 3 del Metro de Santiago"),
        ("Línea 3 de Metro", "nueva Línea 3 del Metro"),
        ("San Nicolás", "proyecto inmobiliario San Nicolás"),
        ("Supermercado Líder San Francisco", "supermercado Líder San Francisco de Walmart Chile"),
        ("Torres Alameda", "tres torres Alameda"),
        ("block 14 de la Villa San Luis", "block 14"),
        ("edificio de la UNCTAD III (hoy GAM)", "edificio UNCTAD III"),
    }
)


def classify_with_provenance(name_a: str, name_b: str) -> tuple[bool | None, str, str, str | None]:
    """Clasifica y devuelve el origen estructurado, nunca inferido del texto."""
    if (name_a, name_b) in MANUAL_DECISIONS:
        decision, reason = MANUAL_DECISIONS[(name_a, name_b)]
        meta = MANUAL_DECISION_EVIDENCE.get((name_a, name_b))
        return decision, reason, (meta or {}).get("source", "legacy_manual_adjudication"), None
    if (name_b, name_a) in MANUAL_DECISIONS:
        decision, reason = MANUAL_DECISIONS[(name_b, name_a)]
        meta = MANUAL_DECISION_EVIDENCE.get((name_b, name_a))
        return decision, reason, (meta or {}).get("source", "legacy_manual_adjudication"), None
    # [ORDEN 2026-09-26] el blocklist de nombres genericos (GENERIC_BLOCKLIST:
    # "vespucio", "supermercado lider", etc.) va ANTES del fallback de
    # substring normalizado -- un nombre generico bare puede aparecer como
    # substring de CUALQUIER decision manual que lo mencione, produciendo
    # una reconexion espuria (ej. "Vespucio" matcheando por substring contra
    # una decision real sobre "Jardines de Vespucio" que no tiene relacion).
    # El blocklist ya resuelve estos casos de forma segura (False, nunca
    # fusiona), asi que debe interceptarlos primero.
    if is_generic_bare_name(name_a, name_b) or is_generic_bare_name(name_b, name_a):
        return False, "nombre generico en lista de bloqueo (aparece en multiples proyectos distintos del corpus)", "deterministic_rule", None
    if has_explicit_stage_conflict(name_a, name_b):
        return False, "Etapa/Fase explicita distinta entre los dos nombres (palabra etapa/fase presente en el texto)", "deterministic_rule", None
    # Name similarity is not an identity key. Historical decisions are only
    # reusable through exact project-ID adjudications loaded by the caller.
    if has_bare_trailing_numeral_conflict(name_a, name_b):
        return None, (
            "numeral suelto al final de uno de los nombres, sin decision manual explicita -- "
            "[hallazgo de Sol 2026-09-18] un numeral suelto suele ser una direccion, no una fase; "
            "requiere revision humana, no se asume kept_separate automaticamente"
        ), "unresolved", None
    return None, "sin regla aplicable ni decision manual -- requiere revision humana adicional", "unresolved", None


def classify_project_pair_with_adjudications(
    project_id_a: str,
    name_a: str,
    project_id_b: str,
    name_b: str,
    adjudications: list[dict[str, Any]],
) -> tuple[bool | None, str, str, str | None]:
    """Apply source-reviewed project identity decisions by exact IDs only.

    A reviewed explicit non-identity returns ``False`` (persisted as
    ``kept_separate``); an unresolved pair returns ``None``. Name similarity
    is never used to transfer a human decision to a different project-ID pair.
    """
    pair_ids = tuple(sorted((str(project_id_a), str(project_id_b))))
    name_by_id = {str(project_id_a): name_a, str(project_id_b): name_b}
    exact_entry = None
    reviewed_name_pair = False
    for entry in adjudications:
        ids = entry.get("project_ids")
        if not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2:
            raise ValueError("identity adjudication requires two distinct project_ids")
        entry_ids = tuple(sorted(str(value) for value in ids))
        names = entry.get("project_names")
        if not isinstance(names, dict) or set(names) != set(entry_ids):
            raise ValueError(f"identity adjudication {entry.get('pair_id')!r} has invalid project_names")
        entry_name_pair = tuple(sorted(_norm(str(names[value])) for value in entry_ids))
        if entry_ids == pair_ids:
            if any(str(names[pid]) != name_by_id[pid] for pid in pair_ids):
                raise ValueError(
                    f"canonical_name mismatch for exact identity adjudication {entry.get('pair_id')!r}"
                )
            if exact_entry is not None:
                raise ValueError(f"duplicate exact identity adjudications for {pair_ids!r}")
            exact_entry = entry
        if entry_name_pair == tuple(sorted((_norm(name_a), _norm(name_b)))):
            reviewed_name_pair = True

    if exact_entry is not None:
        identity_class = exact_entry.get("identity_class")
        action = exact_entry.get("resolver_action")
        rationale = str(exact_entry.get("rationale") or "")
        if identity_class == "same_identity" and action == "merge_case":
            return True, rationale, str(exact_entry.get("decision_source") or "identity_followup_2026-09-27"), None
        if identity_class in {"parent_component_phase", "related_plan_or_instrument", "distinct_entities"} and action == "no_new_merge":
            return False, rationale, str(exact_entry.get("decision_source") or "identity_followup_2026-09-27"), None
        if identity_class == "unresolved" and action == "no_new_merge":
            return None, rationale, str(exact_entry.get("decision_source") or "identity_followup_2026-09-27"), None
        raise ValueError(
            f"unsupported resolver_action {action!r} for identity class {identity_class!r}"
        )

    if reviewed_name_pair:
        return (
            None,
            "par de nombres revisado para otros project_id; no se hereda una decision por nombre",
            "identity_followup_name_scope_guard",
            None,
        )
    return classify_with_provenance(name_a, name_b)


def load_project_identity_adjudications(
    artifact_path: Path | None = None,
    source_bundle_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load and pin the exact-ID identity-review decisions consumed by the resolver."""
    root = Path(__file__).resolve().parents[1]
    artifact_path = artifact_path or root / "audit" / "identity_followup_2026-09-27" / "identity_adjudications_v1.json"
    source_bundle_path = source_bundle_path or root / "audit" / "identity_followup_2026-09-26" / "identity_review_bundle.json"
    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    if payload.get("artifact_id") != "project_identity_adjudications_2026-09-27_v1":
        raise ValueError("unexpected project identity adjudication artifact_id")
    expected_bundle_sha = payload.get("source_bundle_sha256")
    bundle_raw = Path(source_bundle_path).read_bytes()
    actual_bundle_sha = hashlib.sha256(bundle_raw).hexdigest()
    if expected_bundle_sha != actual_bundle_sha:
        raise ValueError("identity review bundle SHA-256 mismatch")
    source_bundle = json.loads(bundle_raw.decode("utf-8"))
    bundle_pairs = {item["pair_id"]: item for item in source_bundle.get("unresolved_pairs", [])}
    entries = payload.get("adjudications")
    if not isinstance(entries, list) or len(entries) != 68:
        raise ValueError("identity adjudication artifact must contain exactly 68 reviewed pairs")
    allowed_classes = {
        "same_identity",
        "parent_component_phase",
        "related_plan_or_instrument",
        "distinct_entities",
        "unresolved",
    }
    # Reuse the pure classifier as a structural validation pass: this rejects
    # duplicate ID pairs, stale names and unsupported actions before mutation.
    seen_pair_ids: set[str] = set()
    seen_id_pairs: set[tuple[str, str]] = set()
    for entry in entries:
        pair_id = str(entry.get("pair_id") or "")
        ids = entry.get("project_ids")
        if not pair_id or pair_id in seen_pair_ids or not isinstance(ids, list) or len(ids) != 2:
            raise ValueError("identity adjudication pair_id/project_ids are missing or duplicated")
        id_pair = tuple(sorted(str(value) for value in ids))
        if id_pair in seen_id_pairs:
            raise ValueError(f"duplicate identity adjudication project_id pair {id_pair!r}")
        seen_pair_ids.add(pair_id)
        seen_id_pairs.add(id_pair)
        identity_class = entry.get("identity_class")
        canonical_project_id = entry.get("canonical_project_id")
        if identity_class not in allowed_classes:
            raise ValueError(f"identity adjudication {pair_id!r} has unsupported identity_class")
        if identity_class == "same_identity":
            if entry.get("resolver_action") != "merge_case":
                raise ValueError(f"same_identity pair {pair_id!r} must be merge_case")
            if canonical_project_id not in id_pair:
                raise ValueError(f"same_identity pair {pair_id!r} requires an exact canonical_project_id")
        elif entry.get("resolver_action") != "no_new_merge":
            raise ValueError(f"non-identical or unresolved pair {pair_id!r} must not merge")
        elif canonical_project_id is not None:
            raise ValueError(f"no_new_merge pair {pair_id!r} cannot declare a canonical_project_id")
        names = entry.get("project_names")
        if not isinstance(names, dict) or set(names) != set(id_pair):
            raise ValueError(f"identity adjudication {pair_id!r} has invalid project_names")
        source_pair = bundle_pairs.get(pair_id)
        if source_pair is None:
            raise ValueError(f"identity adjudication pair_id {pair_id!r} is absent from source bundle")
        source_ids = {
            source_pair["project_a"]["project_id"],
            source_pair["project_b"]["project_id"],
        }
        source_names = {
            source_pair["project_a"]["project_id"]: source_pair["project_a"]["canonical_name"],
            source_pair["project_b"]["project_id"]: source_pair["project_b"]["canonical_name"],
        }
        if set(id_pair) != source_ids or names != source_names:
            raise ValueError(f"identity adjudication {pair_id!r} project IDs/names differ from source bundle")
        source_evidence = entry.get("source_evidence")
        if not isinstance(source_evidence, list) or not source_evidence:
            raise ValueError(f"identity adjudication {pair_id!r} has no source_evidence")
        seen_sides: set[str] = set()
        literal_evidence_sides: set[str] = set()
        for ref in source_evidence:
            side = ref.get("side")
            side_key = "project_a" if side == "a" else "project_b" if side == "b" else None
            if side_key is None:
                raise ValueError(f"identity adjudication {pair_id!r} has invalid evidence side")
            source_project = source_pair[side_key]
            project_id = source_project["project_id"]
            if ref.get("project_id") != project_id or ref.get("project_name") != source_project["canonical_name"]:
                raise ValueError(f"identity adjudication {pair_id!r} evidence has stale project identity")
            expected_sources = {
                (example.get("document_id"), example.get("url"), example.get("raw_project_mention"))
                for example in source_project.get("source_examples", [])
            }
            if (
                ref.get("document_id"), ref.get("url"), ref.get("raw_project_mention")
            ) not in expected_sources:
                raise ValueError(f"identity adjudication {pair_id!r} cites a source outside its bundle side")
            if not ref.get("content_record_sha256") or not ref.get("source_text_sha256"):
                raise ValueError(f"identity adjudication {pair_id!r} has incomplete source hashes")
            if ref.get("evidence_status") == "literal_anchor_verified":
                if not ref.get("quote") or not ref.get("matched_fragment"):
                    raise ValueError(f"identity adjudication {pair_id!r} has incomplete literal evidence")
                literal_evidence_sides.add(side)
            elif ref.get("evidence_status") != "no_discriminative_literal_anchor":
                raise ValueError(f"identity adjudication {pair_id!r} has unsupported evidence_status")
            seen_sides.add(side)
        if seen_sides != {"a", "b"}:
            raise ValueError(f"identity adjudication {pair_id!r} must retain source references for both projects")
        if literal_evidence_sides != {"a", "b"} and identity_class != "unresolved":
            raise ValueError(f"identity adjudication {pair_id!r} needs a literal anchor for both projects")
    if seen_pair_ids != set(bundle_pairs):
        raise ValueError("identity adjudication pair_id set differs from the frozen source bundle")
    return entries


def load_historical_project_identity_adjudications(
    artifact_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load the hash-pinned exact-ID supplement for recovered legacy pairs.

    This artifact is deliberately additive: it cannot overlap the reviewed
    68-pair bundle, promote a decision by itself, or transfer a decision by
    name. Unresolved entries remain unresolved.
    """
    root = Path(__file__).resolve().parents[1]
    artifact_path = artifact_path or root / "audit" / "historical_project_pair_adjudications_v1.json"
    raw = Path(artifact_path).read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != HISTORICAL_PAIR_ADJUDICATION_SHA256:
        raise ValueError("historical project-pair adjudication SHA-256 mismatch")
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != "historical_project_pair_adjudications_v1":
        raise ValueError("unexpected historical project-pair adjudication schema_version")
    if payload.get("artifact_id") != "historical_project_pair_adjudications_2026-09-28_v1":
        raise ValueError("unexpected historical project-pair adjudication artifact_id")
    if payload.get("generated_on") != "2026-09-28":
        raise ValueError("unexpected historical project-pair adjudication date")
    if payload.get("scope", {}).get("production_promoted") is not False:
        raise ValueError("historical pair artifact must remain a non-promoted candidate")
    entries = payload.get("adjudications")
    if not isinstance(entries, list) or len(entries) != 27:
        raise ValueError("historical project-pair artifact must contain exactly 27 pairs")
    allowed_classes = {
        "same_identity", "parent_component_phase", "related_plan_or_instrument",
        "distinct_entities", "unresolved",
    }
    seen_pair_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    snapshot = []
    for entry in entries:
        pair_id = str(entry.get("pair_id") or "")
        ids = entry.get("project_ids")
        if not pair_id or pair_id in seen_pair_ids or not isinstance(ids, list) or len(ids) != 2:
            raise ValueError("historical pair_id/project_ids are missing or duplicated")
        id_pair = tuple(sorted(str(value) for value in ids))
        if len(set(id_pair)) != 2 or id_pair in seen_pairs:
            raise ValueError(f"duplicate or invalid historical project-ID pair {id_pair!r}")
        expected_pair_id = "historical_pair:" + hashlib.sha256("\0".join(id_pair).encode()).hexdigest()[:20]
        if pair_id != expected_pair_id:
            raise ValueError(f"historical pair_id does not match exact project IDs: {pair_id!r}")
        if entry.get("identity_class") not in allowed_classes:
            raise ValueError(f"historical pair {pair_id!r} has unsupported identity_class")
        same = entry["identity_class"] == "same_identity"
        if same:
            if entry.get("resolver_action") != "merge_case" or entry.get("canonical_project_id") not in id_pair:
                raise ValueError(f"historical same_identity pair {pair_id!r} has invalid merge/canonical ID")
        elif entry.get("resolver_action") != "no_new_merge" or entry.get("canonical_project_id") is not None:
            raise ValueError(f"historical non-identity pair {pair_id!r} must not merge or name a canonical ID")
        if entry.get("decision_source") != "historical_pair_adjudication_2026-09-28":
            raise ValueError(f"historical pair {pair_id!r} has unexpected decision_source")
        if entry.get("typed_relation_persisted") is not False or entry.get("production_promoted") is not False:
            raise ValueError(f"historical pair {pair_id!r} must remain an unpromoted candidate")
        names = entry.get("project_names")
        if not isinstance(names, dict) or set(names) != set(id_pair) or any(not names[pid] for pid in id_pair):
            raise ValueError(f"historical pair {pair_id!r} has invalid project_names")
        refs = entry.get("source_evidence")
        if not isinstance(refs, list) or len(refs) != 2 or {ref.get("side") for ref in refs} != {"a", "b"}:
            raise ValueError(f"historical pair {pair_id!r} must cite one source per side")
        for ref in refs:
            if ref.get("project_id") not in id_pair or names.get(ref.get("project_id")) != ref.get("project_name"):
                raise ValueError(f"historical pair {pair_id!r} has evidence for a different project ID")
            if ref.get("evidence_status") != "literal_anchor_verified" or not ref.get("quote"):
                raise ValueError(f"historical pair {pair_id!r} lacks a literal source anchor")
            if not ref.get("source_text_sha256") or not ref.get("content_record_sha256"):
                raise ValueError(f"historical pair {pair_id!r} lacks source hashes")
        seen_pair_ids.add(pair_id)
        seen_pairs.add(id_pair)
        snapshot.append({
            "project_ids": ids,
            "project_names": names,
            "source_queue_rowid": entry.get("source_queue_rowid"),
        })
    snapshot_sha = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if payload.get("source_pair_snapshot_sha256") != snapshot_sha:
        raise ValueError("historical project-pair snapshot SHA-256 mismatch")
    base_pairs = {
        tuple(sorted(str(value) for value in entry["project_ids"]))
        for entry in load_project_identity_adjudications()
    }
    overlap = seen_pairs & base_pairs
    if overlap:
        raise ValueError(f"historical supplement overlaps the frozen 68-pair artifact: {sorted(overlap)!r}")
    return entries


def load_effective_project_identity_adjudications(
    override_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Combine the frozen 68-pair review, exact-ID overrides, and 27 legacy pairs.

    Overrides can only replace an ``unresolved`` entry in the exact frozen base
    artifact. They cannot transfer by name, alter the historical supplement,
    or mark themselves as production-promoted. The returned objects are copies;
    the source adjudication artifacts remain immutable.
    """
    root = Path(__file__).resolve().parents[1]
    base_path = root / "audit" / "identity_followup_2026-09-27" / "identity_adjudications_v1.json"
    bundle_path = root / "audit" / "identity_followup_2026-09-26" / "identity_review_bundle.json"
    historical_path = root / "audit" / "historical_project_pair_adjudications_v1.json"
    override_path = override_path or root / "audit" / "project_identity_adjudication_overrides_2026-09-28_v2.json"

    base_raw = base_path.read_bytes()
    if hashlib.sha256(base_raw).hexdigest() != PROJECT_IDENTITY_BASE_ADJUDICATION_SHA256:
        raise ValueError("base project identity adjudication SHA-256 mismatch")
    bundle_raw = bundle_path.read_bytes()
    payload_raw = Path(override_path).read_bytes()
    override_sha = hashlib.sha256(payload_raw).hexdigest()
    if override_sha != PROJECT_IDENTITY_OVERRIDE_SHA256:
        raise ValueError("override SHA-256 mismatch")
    payload = json.loads(payload_raw.decode("utf-8"))
    if payload.get("schema_version") != "project_identity_adjudication_overrides_v2":
        raise ValueError("unexpected project identity override schema_version")
    if payload.get("artifact_id") != "project_identity_adjudication_overrides_2026-09-28_v2":
        raise ValueError("unexpected project identity override artifact_id")
    if payload.get("generated_on") != "2026-09-28":
        raise ValueError("unexpected project identity override date")
    if payload.get("source_base_adjudication_sha256") != PROJECT_IDENTITY_BASE_ADJUDICATION_SHA256:
        raise ValueError("project identity override does not pin the frozen base adjudication")
    if payload.get("source_base_bundle_sha256") != hashlib.sha256(bundle_raw).hexdigest():
        raise ValueError("project identity override source bundle SHA-256 mismatch")
    if payload.get("source_historical_adjudication_sha256") != HISTORICAL_PAIR_ADJUDICATION_SHA256:
        raise ValueError("project identity override does not pin the historical supplement")
    scope = payload.get("scope")
    if not isinstance(scope, dict) or scope.get("production_promoted") is not False:
        raise ValueError("project identity override must remain unpromoted")
    if scope.get("typed_relation_persisted") is not False:
        raise ValueError("project identity override cannot claim a typed relation was persisted")
    topology_unresolved = scope.get("topology_unresolved_reviewed")
    if not isinstance(topology_unresolved, list) or any(
        not isinstance(item, dict) or not item.get("pair_id") or not item.get("reason")
        for item in topology_unresolved
    ):
        raise ValueError("project identity override needs explicit topology-unresolved reasons")

    base_entries = load_project_identity_adjudications()
    historical_entries = load_historical_project_identity_adjudications(historical_path)
    if len(base_entries) != 68 or len(historical_entries) != 27:
        raise ValueError("effective identity input counts differ from the pinned contract")
    base_by_pair = {
        tuple(sorted(str(value) for value in entry["project_ids"])): entry
        for entry in base_entries
    }
    historical_pairs = {
        tuple(sorted(str(value) for value in entry["project_ids"]))
        for entry in historical_entries
    }
    unresolved_base = {
        entry["pair_id"]: tuple(sorted(str(value) for value in entry["project_ids"]))
        for entry in base_entries
        if entry.get("identity_class") == "unresolved"
    }
    unresolved_history = {
        entry["pair_id"]
        for entry in historical_entries
        if entry.get("identity_class") == "unresolved"
    }
    if set(scope.get("base_unresolved_retained", [])) != set(unresolved_base) - {
        str(entry.get("pair_id")) for entry in payload.get("adjudications", [])
    }:
        raise ValueError("override unresolved-base inventory does not match the frozen base decisions")
    if set(scope.get("historical_unresolved_retained", [])) != unresolved_history:
        raise ValueError("override historical-unresolved inventory does not match the historical artifact")

    overrides = payload.get("adjudications")
    if not isinstance(overrides, list) or len(overrides) != 13 or scope.get("pair_count") != 13:
        raise ValueError("project identity override must contain exactly 13 exact-ID pairs")
    topology_unresolved_ids = {str(item["pair_id"]) for item in topology_unresolved}
    if topology_unresolved_ids != {"d0fb99d977176b8fd90c", "7dfca97fba3dc5d6abd2"}:
        raise ValueError("topology blocker inventory differs from the adjudicated exact pairs")
    seen_pairs: set[tuple[str, str]] = set()
    seen_pair_ids: set[str] = set()
    override_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for override in overrides:
        pair_id = str(override.get("pair_id") or "")
        ids = override.get("project_ids")
        if not pair_id or pair_id in seen_pair_ids or not isinstance(ids, list) or len(ids) != 2:
            raise ValueError("project identity override has missing/duplicate pair_id or project_ids")
        pair = tuple(sorted(str(value) for value in ids))
        if pair[0] == pair[1] or pair in seen_pairs or pair in historical_pairs:
            raise ValueError(f"duplicate, self, or historical override pair {pair!r}")
        base = base_by_pair.get(pair)
        if base is None or base.get("pair_id") != pair_id or base.get("identity_class") != "unresolved":
            raise ValueError(f"override {pair_id!r} is not an exact unresolved pair in the frozen base")
        names = override.get("project_names")
        if names != base.get("project_names") or set(names or {}) != set(pair):
            raise ValueError(f"override {pair_id!r} project names differ from the frozen base")
        identity_class = override.get("identity_class")
        action = override.get("resolver_action")
        canonical = override.get("canonical_project_id")
        if identity_class == "same_identity":
            if action != "merge_case" or canonical not in pair:
                raise ValueError(f"same_identity override {pair_id!r} needs merge_case and an exact canonical ID")
            if not override.get("canonical_selection_note"):
                raise ValueError(f"same_identity override {pair_id!r} needs a canonical-selection rationale")
            if override.get("confidence") != "high":
                raise ValueError(f"same_identity override {pair_id!r} needs high confidence before merging")
        elif identity_class == "distinct_entities":
            if action != "no_new_merge" or canonical is not None or override.get("canonical_selection_note") is not None:
                raise ValueError(f"distinct_entities override {pair_id!r} must not merge or choose a canonical ID")
        elif identity_class == "unresolved":
            if action != "no_new_merge" or canonical is not None or override.get("canonical_selection_note") is not None:
                raise ValueError(f"unresolved override {pair_id!r} must remain unmerged without a canonical ID")
        else:
            raise ValueError(f"unsupported project identity override class {identity_class!r}")
        if override.get("decision_source") != PROJECT_IDENTITY_OVERRIDE_SOURCE:
            raise ValueError(f"override {pair_id!r} has unexpected decision_source")
        if override.get("production_promoted") is not False or override.get("typed_relation_persisted") is not False:
            raise ValueError(f"override {pair_id!r} must remain an unpromoted candidate")
        if override.get("confidence") not in {"high", "medium"} or not override.get("rationale"):
            raise ValueError(f"override {pair_id!r} has incomplete decision rationale/confidence")
        if pair_id in topology_unresolved_ids and identity_class != "unresolved":
            raise ValueError(f"topology-blocking pair {pair_id!r} must remain unresolved")

        base_refs = {
            ref.get("evidence_ref_id"): ref
            for ref in base.get("source_evidence", [])
            if ref.get("evidence_ref_id")
        }
        evidence_ref_ids = override.get("source_evidence_ref_ids")
        if not isinstance(evidence_ref_ids, list) or not evidence_ref_ids or len(set(evidence_ref_ids)) != len(evidence_ref_ids):
            raise ValueError(f"override {pair_id!r} has missing or duplicate source evidence references")
        cited_refs = [base_refs.get(ref_id) for ref_id in evidence_ref_ids]
        if any(ref is None for ref in cited_refs) or {ref.get("side") for ref in cited_refs if ref} != {"a", "b"}:
            raise ValueError(f"override {pair_id!r} must cite frozen source evidence for both exact project IDs")
        if any(ref.get("project_id") not in pair for ref in cited_refs if ref):
            raise ValueError(f"override {pair_id!r} source evidence references another project ID")
        supporting_sources = override.get("supporting_sources")
        if not isinstance(supporting_sources, list) or not supporting_sources:
            raise ValueError(f"override {pair_id!r} has no supporting source links")
        for source in supporting_sources:
            if not isinstance(source, dict) or not str(source.get("url", "")).startswith("https://"):
                raise ValueError(f"override {pair_id!r} has an invalid supporting source URL")
            if not source.get("publisher") or not source.get("supports"):
                raise ValueError(f"override {pair_id!r} has an incomplete supporting source record")

        seen_pairs.add(pair)
        seen_pair_ids.add(pair_id)
        override_by_pair[pair] = override

    if set(seen_pair_ids) != set(unresolved_base) - set(scope.get("base_unresolved_retained", [])):
        raise ValueError("override pair set does not exactly cover the declared subset of base unresolved pairs")

    effective_base: list[dict[str, Any]] = []
    for original in base_entries:
        pair = tuple(sorted(str(value) for value in original["project_ids"]))
        override = override_by_pair.get(pair)
        if override is None:
            effective_base.append(copy.deepcopy(original))
            continue
        effective = copy.deepcopy(original)
        effective["prior_adjudication"] = {
            "identity_class": original.get("identity_class"),
            "resolver_action": original.get("resolver_action"),
            "canonical_project_id": original.get("canonical_project_id"),
            "rationale": original.get("rationale"),
            "decision_source": original.get("decision_source"),
        }
        for field in (
            "identity_class", "resolver_action", "canonical_project_id", "canonical_selection_note",
            "confidence", "rationale", "decision_source", "production_promoted", "typed_relation_persisted",
        ):
            effective[field] = override.get(field)
        effective["override_artifact"] = "audit/project_identity_adjudication_overrides_2026-09-28_v2.json"
        effective["override_artifact_sha256"] = override_sha
        effective["override_source_evidence_ref_ids"] = list(override["source_evidence_ref_ids"])
        effective["override_supporting_sources"] = copy.deepcopy(override["supporting_sources"])
        effective_base.append(effective)

    effective_pairs = [tuple(sorted(str(value) for value in entry["project_ids"])) for entry in effective_base + historical_entries]
    if len(effective_pairs) != len(set(effective_pairs)):
        raise ValueError("effective project identity artifacts contain a duplicate exact-ID pair")
    return effective_base + copy.deepcopy(historical_entries)


def validate_project_identity_adjudication_scope(
    projects: dict[str, str],
    rows: list[tuple[int, str, str, str, str]],
    adjudications: list[dict[str, Any]],
) -> None:
    """Fail closed if a reviewed pair no longer matches the live review queue."""
    queue_pairs = {tuple(sorted((str(pid_a), str(pid_b)))) for _, pid_a, _, pid_b, _ in rows}
    for entry in adjudications:
        ids = tuple(sorted(str(value) for value in entry["project_ids"]))
        for project_id in ids:
            actual_name = projects.get(project_id)
            expected_name = entry["project_names"].get(project_id)
            if actual_name is None:
                raise ValueError(f"identity adjudication references missing project_id {project_id!r}")
            if actual_name != expected_name:
                raise ValueError(
                    f"canonical_name mismatch for identity adjudication {entry['pair_id']!r}: "
                    f"{actual_name!r} != {expected_name!r}"
                )
        if ids not in queue_pairs:
            raise ValueError(f"reviewed identity pair {entry['pair_id']!r} is absent from project_review_queue")


def validate_project_identity_adjudication_evidence(
    adjudications: list[dict[str, Any]], project_root: Path, content_root: Path | None = None
) -> dict[str, int]:
    """Verify every cited fulltext record, hash, URL and literal quote before resolving.

    This validation is intentionally fail-closed. A checked-in adjudication is
    not sufficient by itself: the exact external corpus record must still be
    present under the project's fulltext content root and match its hashes.
    """
    root = Path(project_root).resolve()
    content_root = (
        Path(content_root).resolve()
        if content_root is not None
        else (root / "Fuentes" / "fulltext" / "content").resolve()
    )
    failures: list[str] = []
    valid_references = 0
    verified_literal_quotes = 0
    unanchored_references = 0
    for entry in adjudications:
        pair_id = str(entry.get("pair_id") or "")
        project_ids = entry.get("project_ids") or []
        project_names = entry.get("project_names") or {}
        for index, ref in enumerate(entry.get("source_evidence", [])):
            label = f"{pair_id}[{index}]"
            required = {
                "side", "project_id", "project_name", "document_id", "url",
                "content_file", "source_text_sha256", "content_record_sha256",
                "raw_project_mention", "evidence_status",
            }
            if not isinstance(ref, dict) or required - set(ref):
                absent = sorted(required - set(ref)) if isinstance(ref, dict) else sorted(required)
                failures.append(f"{label}: faltan campos de evidencia {absent}")
                continue
            if ref["project_id"] not in project_ids or project_names.get(ref["project_id"]) != ref["project_name"]:
                failures.append(f"{label}: project_id/name no corresponde a la adjudicación")
                continue
            relative = Path(str(ref["content_file"]))
            expected_prefix = ("Fuentes", "fulltext", "content")
            if relative.is_absolute() or relative.parts[:3] != expected_prefix or ".." in relative.parts:
                failures.append(f"{label}: content_file debe ser relativo")
                continue
            candidate = (
                Path(content_root).resolve() / Path(*relative.parts[3:])
                if content_root is not None
                else root / relative
            ).resolve()
            try:
                candidate.relative_to(content_root)
            except ValueError:
                failures.append(f"{label}: content_file queda fuera de Fuentes/fulltext/content")
                continue
            if not candidate.is_file():
                failures.append(f"{label}: no existe content_file {ref['content_file']!r}")
                continue
            raw = candidate.read_bytes()
            if hashlib.sha256(raw).hexdigest() != ref["content_record_sha256"]:
                failures.append(f"{label}: content_record_sha256 no coincide")
                continue
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                failures.append(f"{label}: JSON de fulltext inválido ({exc})")
                continue
            text = record.get("text")
            if not isinstance(text, str):
                failures.append(f"{label}: record.text no es texto")
                continue
            text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if record.get("url") != ref["url"]:
                failures.append(f"{label}: URL del registro no coincide")
            if text_sha != ref["source_text_sha256"] or text_sha != ref["document_id"]:
                failures.append(f"{label}: hash del texto/document_id no coincide")
            if ref["evidence_status"] == "literal_anchor_verified":
                quote = ref.get("quote")
                fragment = ref.get("matched_fragment")
                if not isinstance(quote, str) or not quote or quote not in text:
                    failures.append(f"{label}: quote no es substring literal del fulltext")
                if (
                    not isinstance(fragment, str)
                    or not fragment
                    or not isinstance(quote, str)
                    or fragment not in quote
                ):
                    failures.append(f"{label}: matched_fragment no aparece en la cita literal")
                else:
                    verified_literal_quotes += 1
            elif ref["evidence_status"] == "no_discriminative_literal_anchor":
                if ref.get("quote") is not None or ref.get("matched_fragment") is not None:
                    failures.append(f"{label}: fuente sin ancla discriminante no debe inventar cita")
                unanchored_references += 1
            else:
                failures.append(f"{label}: evidence_status no reconocido")
            if record.get("url") == ref["url"] and text_sha == ref["document_id"]:
                valid_references += 1
    if failures:
        raise ValueError("identity adjudication source evidence invalid: " + "; ".join(failures[:20]))
    return {
        "valid_references": valid_references,
        "verified_literal_quotes": verified_literal_quotes,
        "unanchored_references": unanchored_references,
    }


def validate_project_identity_adjudication_topology(
    project_to_case: dict[str, str],
    baseline_case_id_by_project: dict[str, str],
    adjudications: list[dict[str, Any]],
) -> dict[str, int]:
    """Reject a transitive topology change that defeats any reviewed no-merge.

    A no-new-merge pair may already share a legacy case_id. That historical
    grouping is reported but is not newly applied. If it starts in separate
    baseline groups and ends in one output group, fail before SQLite writes.
    """
    checked = 0
    transitive_reconnections: list[str] = []
    for entry in adjudications:
        if entry.get("resolver_action") != "no_new_merge":
            continue
        ids = entry.get("project_ids") or []
        if len(ids) != 2 or any(pid not in project_to_case for pid in ids):
            raise ValueError(f"identity adjudication {entry.get('pair_id')!r} references missing topology IDs")
        checked += 1
        left, right = ids
        if (
            baseline_case_id_by_project[left] != baseline_case_id_by_project[right]
            and project_to_case[left] == project_to_case[right]
        ):
            transitive_reconnections.append(str(entry.get("pair_id")))
    if transitive_reconnections:
        raise ValueError(
            "no_new_merge pair became connected through another merge: "
            + ", ".join(transitive_reconnections[:20])
        )
    return {"checked": checked, "transitive_reconnections": 0}


def classify(name_a: str, name_b: str) -> tuple[bool | None, str]:
    decision, reason, _source, _actor = classify_with_provenance(name_a, name_b)
    return decision, reason


def decision_provenance_ref(
    name_a: str,
    name_b: str,
    source: str,
    project_ids: tuple[str, str] | None = None,
    identity_adjudications: list[dict[str, Any]] | None = None,
) -> str:
    """Devuelve una referencia estable sin analizar la razón narrativa."""
    if source == "identity_followup_name_scope_guard":
        return json.dumps(
            {
                "source": source,
                "artifact": "audit/identity_followup_2026-09-27/identity_adjudications_v1.json",
                "project_ids": sorted(str(value) for value in (project_ids or ())),
                "note": "decision not transferred because reviewed names belong to different project IDs",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if source in {
        "identity_followup_2026-09-27",
        "historical_pair_adjudication_2026-09-28",
        PROJECT_IDENTITY_OVERRIDE_SOURCE,
    }:
        if project_ids is None or identity_adjudications is None:
            raise ValueError("identity review provenance requires exact project IDs and adjudications")
        ids = tuple(sorted(str(value) for value in project_ids))
        entry = next(
            (item for item in identity_adjudications if tuple(sorted(item["project_ids"])) == ids),
            None,
        )
        if entry is None:
            raise ValueError(f"missing identity review provenance for project pair {ids!r}")
        entry_source = str(entry.get("decision_source") or "identity_followup_2026-09-27")
        if entry_source != source:
            raise ValueError(f"identity review provenance source mismatch for project pair {ids!r}")
        artifact = {
            "identity_followup_2026-09-27": "audit/identity_followup_2026-09-27/identity_adjudications_v1.json",
            "historical_pair_adjudication_2026-09-28": "audit/historical_project_pair_adjudications_v1.json",
            PROJECT_IDENTITY_OVERRIDE_SOURCE: "audit/project_identity_adjudication_overrides_2026-09-28_v2.json",
        }[source]
        artifact_path = Path(__file__).resolve().parents[1] / artifact
        return json.dumps(
            {
                "source": source,
                "artifact": artifact,
                "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "pair_id": entry["pair_id"],
                "identity_class": entry["identity_class"],
                "source_evidence_ref_ids": entry.get("override_source_evidence_ref_ids"),
                "supporting_source_urls": sorted(
                    source_ref["url"] for source_ref in entry.get("override_supporting_sources", [])
                ),
                "source_evidence_sha256": sorted(
                    ref["content_record_sha256"] for ref in entry.get("source_evidence", [])
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    meta = MANUAL_DECISION_EVIDENCE.get((name_a, name_b)) or MANUAL_DECISION_EVIDENCE.get((name_b, name_a))
    if meta:
        payload = dict(meta)
        payload["validation_scope"] = "source_text_quote_and_project_mention_not_structured_evidence_row"
        payload["structured_evidence_row_checked"] = False
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    pair_hash = hashlib.sha256("\0".join(sorted((name_a, name_b))).encode("utf-8")).hexdigest()
    return f"{source}:pair_sha256={pair_hash}"


def validate_manual_decision_evidence(
    conn: sqlite3.Connection,
    project_root: Path,
    evidence_map: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Valida las referencias a fuentes de adjudicaciones positivas antes de mutar SQLite.

    Comprueba en conjunto la identidad del proyecto, la mencion resuelta,
    la URL del documento, la ruta permitida, el hash del texto y del registro
    JSON, y que la cita sea un substring literal del texto congelado. No afirma
    que la cita exista como fila estructurada en ``evidence``: estas son
    adjudicaciones humanas directas sobre la fuente y esa relación no está
    disponible de forma fiable para todas las referencias.
    """
    references_by_pair = evidence_map if evidence_map is not None else MANUAL_DECISION_EVIDENCE
    failures: list[str] = []
    expected_pairs = REQUIRED_SOURCE_BACKED_MANUAL_PAIRS
    supplied_pairs = set(references_by_pair)
    if evidence_map is None and supplied_pairs != expected_pairs:
        missing = sorted(expected_pairs - supplied_pairs)
        extra = sorted(supplied_pairs - expected_pairs)
        if missing:
            failures.append(f"faltan referencias para adjudicaciones positivas: {missing}")
        if extra:
            failures.append(f"referencias sin adjudicacion positiva exacta: {extra}")
    elif evidence_map is not None and not supplied_pairs <= expected_pairs:
        failures.append(
            f"evidence_map de prueba contiene adjudicaciones fuera del allowlist: "
            f"{sorted(supplied_pairs - expected_pairs)}"
        )

    root = Path(project_root).resolve()
    content_root = (root / "Fuentes" / "fulltext" / "content").resolve()
    conn.row_factory = sqlite3.Row
    valid_references = 0
    literal_raw_mentions = 0
    nonliteral_raw_mentions: list[dict[str, str]] = []
    for pair, meta in sorted(references_by_pair.items()):
        references = meta.get("references") if isinstance(meta, dict) else None
        if not isinstance(meta, dict):
            failures.append(f"{pair}: metadata no es objeto")
            continue
        if meta.get("source") != "manual_adjudication":
            failures.append(f"{pair}: source debe ser manual_adjudication")
        if not isinstance(references, list) or not references:
            failures.append(f"{pair}: references debe ser una lista no vacia")
            continue
        pair_projects: set[str] = set()
        for index, ref in enumerate(references):
            label = f"{pair}[{index}]"
            required = {
                "project_id", "project_name", "raw_mention", "document_id", "url",
                "content_file", "source_text_sha256", "content_record_sha256", "quote",
            }
            if not isinstance(ref, dict):
                failures.append(f"{label}: referencia no es objeto")
                continue
            absent = sorted(required - set(ref))
            if absent:
                failures.append(f"{label}: faltan campos {absent}")
                continue
            project_id = str(ref["project_id"])
            project_name = str(ref["project_name"])
            pair_projects.add(project_name)
            if project_name not in pair:
                failures.append(f"{label}: project_name {project_name!r} no pertenece al par")
            project = conn.execute(
                "SELECT canonical_name FROM project WHERE project_id=?", (project_id,)
            ).fetchone()
            if project is None:
                failures.append(f"{label}: project_id inexistente {project_id!r}")
            elif project["canonical_name"] != project_name:
                failures.append(
                    f"{label}: canonical_name DB {project['canonical_name']!r} != {project_name!r}"
                )
            mention = conn.execute(
                "SELECT 1 FROM project_mention_resolved WHERE document_id=? AND project_id=? AND raw_nombre_proyecto=?",
                (ref["document_id"], project_id, ref["raw_mention"]),
            ).fetchone()
            if mention is None:
                failures.append(f"{label}: project_mention_resolved no confirma raw_mention exacta")
            document = conn.execute(
                "SELECT url FROM document WHERE document_id=?", (ref["document_id"],)
            ).fetchone()
            if document is None:
                failures.append(f"{label}: document_id inexistente {ref['document_id']!r}")
                continue
            if document["url"] != ref["url"]:
                failures.append(f"{label}: URL no coincide exactamente con document.url")

            rel_path = Path(str(ref["content_file"]))
            if rel_path.is_absolute():
                failures.append(f"{label}: content_file debe ser ruta relativa")
                continue
            candidate = (root / rel_path).resolve()
            try:
                candidate.relative_to(content_root)
            except ValueError:
                failures.append(f"{label}: content_file queda fuera de Fuentes/fulltext/content")
                continue
            if not candidate.is_file():
                failures.append(f"{label}: no existe content_file {ref['content_file']!r}")
                continue
            raw_bytes = candidate.read_bytes()
            if hashlib.sha256(raw_bytes).hexdigest() != ref["content_record_sha256"]:
                failures.append(f"{label}: content_record_sha256 no coincide")
                continue
            try:
                record = json.loads(raw_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                failures.append(f"{label}: JSON invalido ({exc})")
                continue
            text = record.get("text")
            if not isinstance(text, str):
                failures.append(f"{label}: record.text no es texto")
                continue
            if record.get("url") != ref["url"]:
                failures.append(f"{label}: URL del JSON no coincide con la fuente")
            text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if text_sha256 != ref["source_text_sha256"] or text_sha256 != ref["document_id"]:
                failures.append(f"{label}: source_text_sha256/document_id no coincide con record.text")
            if not ref["quote"] or ref["quote"] not in text:
                failures.append(f"{label}: quote no es substring literal del texto")
            if ref["raw_mention"] in text:
                literal_raw_mentions += 1
            else:
                nonliteral_raw_mentions.append(
                    {"pair": " / ".join(pair), "project_id": project_id, "raw_mention": ref["raw_mention"]}
                )
            if (
                project is not None and mention is not None and document["url"] == ref["url"]
                and text_sha256 == ref["source_text_sha256"] == ref["document_id"]
                and hashlib.sha256(raw_bytes).hexdigest() == ref["content_record_sha256"]
                and ref["quote"] in text
            ):
                valid_references += 1
        if pair_projects != set(pair):
            failures.append(f"{pair}: referencias no cubren ambos nombres del par ({sorted(pair_projects)})")

    if failures:
        raise ValueError(
            "preflight de evidencia manual bloqueado antes de escribir SQLite:\n - "
            + "\n - ".join(failures)
        )
    return {
        "pairs": len(references_by_pair),
        "references": valid_references,
        "literal_raw_mentions": literal_raw_mentions,
        "nonliteral_raw_mentions": nonliteral_raw_mentions,
    }


@dataclass(frozen=True)
class ResolutionPlan:
    project_to_case: dict[str, str]
    row_decisions: dict[int, tuple[bool | None, str, str, str | None]]
    homonym_vetoes: int


def validate_review_queue_rows(projects: dict[str, str], rows: list[tuple[int, str, str, str, str]]) -> None:
    """Falla antes de escribir ante una cola obsoleta, ambigua o duplicada."""
    seen_pairs: set[tuple[str, str]] = set()
    for rowid, pid_a, name_a, pid_b, name_b in rows:
        for pid, supplied_name in ((pid_a, name_a), (pid_b, name_b)):
            if pid not in projects:
                raise ValueError(f"project_review_queue rowid={rowid}: missing project_id {pid!r}")
            if projects[pid] != supplied_name:
                raise ValueError(
                    f"project_review_queue rowid={rowid}: canonical_name mismatch for {pid!r}: "
                    f"queue={supplied_name!r}, project={projects[pid]!r}"
                )
        if pid_a == pid_b:
            raise ValueError(f"project_review_queue rowid={rowid}: self-pair {pid_a!r}")
        pair = tuple(sorted((pid_a, pid_b)))
        if pair in seen_pairs:
            raise ValueError(f"project_review_queue rowid={rowid}: duplicate project pair {pair!r}")
        seen_pairs.add(pair)


def resolve_case_components(
    projects: dict[str, str],
    rows: list[tuple[int, str, str, str, str]],
    partitions: dict[str, str],
    baseline_case_id_by_project: dict[str, str],
    classifier,
    pair_classifier=None,
) -> ResolutionPlan:
    """Resuelve componentes de forma determinista y fail-closed.

    Conserva los componentes ya establecidos en el baseline. Una separación
    explícita no puede ser contradicha por un cierre transitivo.
    """
    validate_review_queue_rows(projects, rows)
    project_ids = set(projects)
    if set(baseline_case_id_by_project) != project_ids:
        missing = sorted(project_ids - set(baseline_case_id_by_project))[:10]
        stale = sorted(set(baseline_case_id_by_project) - project_ids)[:10]
        raise ValueError(f"baseline project_id set mismatch; missing={missing}, stale={stale}")
    for pid, case_id in baseline_case_id_by_project.items():
        if case_id not in project_ids:
            raise ValueError(f"baseline case_id {case_id!r} for {pid!r} is not a current project_id")
    if set(partitions) - project_ids:
        raise ValueError(f"homonym partitions reference missing project_ids: {sorted(set(partitions)-project_ids)[:10]}")

    parent = {pid: pid for pid in project_ids}

    def find(pid: str) -> str:
        root = pid
        while parent[root] != root:
            root = parent[root]
        while parent[pid] != pid:
            nxt = parent[pid]
            parent[pid] = root
            pid = nxt
        return root

    def union(pid_a: str, pid_b: str) -> None:
        root_a, root_b = find(pid_a), find(pid_b)
        if root_a != root_b:
            low, high = sorted((root_a, root_b))
            parent[high] = low

    baseline_groups: dict[str, list[str]] = {}
    for pid, case_id in baseline_case_id_by_project.items():
        baseline_groups.setdefault(case_id, []).append(pid)
    for members in baseline_groups.values():
        ordered = sorted(members)
        for pid in ordered[1:]:
            union(ordered[0], pid)

    def component_partitions(root: str) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        for pid, value in partitions.items():
            if find(pid) == root:
                result.setdefault(value.split("::", 1)[0], set()).add(value)
        return result

    def has_partition_collision(root_a: str, root_b: str) -> bool:
        parts_a = component_partitions(root_a)
        parts_b = component_partitions(root_b)
        for base in parts_a.keys() & parts_b.keys():
            if len(parts_a[base] | parts_b[base]) > 1:
                return True
        return False

    for root in sorted({find(pid) for pid in project_ids}):
        for base, values in component_partitions(root).items():
            if len(values) > 1:
                raise ValueError(f"baseline homonym_partition collision in {base!r}: {sorted(values)!r}")

    classified = []
    for rowid, pid_a, name_a, pid_b, name_b in rows:
        if pair_classifier is None:
            decision, reason, source, actor = classifier(name_a, name_b)
        else:
            decision, reason, source, actor = pair_classifier(pid_a, name_a, pid_b, name_b)
        classified.append((tuple(sorted((pid_a, pid_b))), rowid, pid_a, name_a, pid_b, name_b, decision, reason, source, actor))

    row_decisions: dict[int, tuple[bool | None, str, str, str | None]] = {}
    explicit_separations: list[tuple[int, str, str, str]] = []
    homonym_vetoes = 0
    for _pair, rowid, pid_a, name_a, pid_b, name_b, decision, reason, source, actor in sorted(classified):
        if decision is True:
            root_a, root_b = find(pid_a), find(pid_b)
            if root_a != root_b and has_partition_collision(root_a, root_b):
                decision = False
                source = "homonym_partition_safety_veto"
                reason = f"VETO homonym_partition: proposed merge would reconnect incompatible partitions; original={reason}"
                actor = None
                homonym_vetoes += 1
            else:
                union(pid_a, pid_b)
        elif decision is False:
            explicit_separations.append((rowid, pid_a, pid_b, reason))
        row_decisions[rowid] = (decision, reason, source, actor)

    for rowid, pid_a, pid_b, reason in explicit_separations:
        if find(pid_a) == find(pid_b):
            raise ValueError(
                f"transitive merge violates kept_separate rowid={rowid}: {pid_a!r} / {pid_b!r}; {reason}"
            )

    members_by_root: dict[str, list[str]] = {}
    for pid in sorted(project_ids):
        members_by_root.setdefault(find(pid), []).append(pid)
    project_to_case: dict[str, str] = {}
    for members in members_by_root.values():
        prior_roots: dict[str, int] = {}
        for pid in members:
            prior = baseline_case_id_by_project[pid]
            prior_roots[prior] = prior_roots.get(prior, 0) + 1
        chosen = min(prior_roots, key=lambda case_id: (-prior_roots[case_id], case_id))
        for pid in members:
            project_to_case[pid] = chosen
    return ResolutionPlan(project_to_case, row_decisions, homonym_vetoes)


def run_atomically(conn: sqlite3.Connection, operation):
    """Ejecuta la reconstrucción completa en una sola transacción SQLite."""
    nested = conn.in_transaction
    savepoint = "resolve_project_review_atomic"
    if nested:
        conn.execute(f"SAVEPOINT {savepoint}")
    else:
        conn.execute("BEGIN IMMEDIATE")
    try:
        result = operation(conn)
        if nested:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            conn.commit()
        return result
    except BaseException:
        if nested:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            conn.rollback()
        raise


def _project_id_set_sha256(project_ids: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(project_ids)) + "\n").encode("utf-8")).hexdigest()


def load_case_baseline(projects: dict[str, str], path: Path = CASE_BASELINE) -> tuple[dict[str, str], str]:
    if not path.exists():
        raise FileNotFoundError(f"case_id baseline no existe: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "project_case_baseline_v1":
        raise ValueError("schema_version de project_case_baseline no reconocido")
    source_hash = payload.get("source_warehouse_sha256")
    if not isinstance(source_hash, str) or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None:
        raise ValueError("source_warehouse_sha256 debe ser SHA-256 hexadecimal de 64 caracteres")
    project_ids = set(projects)
    if payload.get("project_id_set_sha256") != _project_id_set_sha256(project_ids):
        raise ValueError("el conjunto actual de project_id no coincide con el baseline versionado")
    rows = payload.get("projects")
    if not isinstance(rows, list):
        raise ValueError("baseline.projects debe ser una lista")
    baseline = {row["project_id"]: row["case_id"] for row in rows}
    if len(baseline) != len(rows) or set(baseline) != project_ids:
        raise ValueError("el mapeo project_id→case_id del baseline no cubre exactamente los proyectos actuales")
    for pid, case_id in baseline.items():
        if case_id not in project_ids:
            raise ValueError(f"baseline case_id inválido {case_id!r} para {pid!r}")
    mapping_bytes = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    mapping_sha256 = hashlib.sha256(mapping_bytes).hexdigest()
    if payload.get("mapping_sha256") != mapping_sha256:
        raise ValueError("mapping_sha256 del baseline no coincide con su contenido")
    return baseline, mapping_sha256


def validate_initial_baseline_warehouse_hash(
    conn: sqlite3.Connection,
    baseline_path: Path = CASE_BASELINE,
    warehouse_path: Path = WAREHOUSE,
) -> bool:
    """En la primera aplicación, ata el baseline al warehouse fuente exacto.

    Una vez que existe case_id_alias, el warehouse ya es posterior a la
    migración y su hash necesariamente cambió; entonces se valida el mapeo,
    no el hash histórico de origen.
    """
    alias_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_id_alias'"
    ).fetchone() is not None
    if alias_exists:
        return False
    payload = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "project_case_baseline_v1":
        raise ValueError("schema_version de project_case_baseline no reconocido")
    expected = payload.get("source_warehouse_sha256")
    if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise ValueError("source_warehouse_sha256 debe ser SHA-256 hexadecimal de 64 caracteres")
    warehouse_path = Path(warehouse_path)
    wal_path = Path(f"{warehouse_path}-wal")
    if wal_path.exists() and wal_path.stat().st_size > 0:
        raise ValueError(
            "baseline inicial no puede verificarse solo contra el archivo SQLite mientras existe un WAL no vacío; "
            "preservar el WAL y crear/verificar un snapshot SQLite consistente primero"
        )
    actual = hashlib.sha256(warehouse_path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(
            "source_warehouse_sha256 no coincide con el warehouse previo a la primera resolución: "
            f"baseline={expected}, actual={actual}"
        )
    return True


def rebuild_case_id_alias(conn: sqlite3.Connection, baseline: dict[str, str], project_to_case: dict[str, str], baseline_sha256: str) -> int:
    old_case_to_new: dict[str, set[str]] = {}
    for pid, old_case_id in baseline.items():
        old_case_to_new.setdefault(old_case_id, set()).add(project_to_case[pid])
    inconsistent = {old: sorted(new) for old, new in old_case_to_new.items() if len(new) != 1}
    if inconsistent:
        raise ValueError(f"un case_id previo se dividió durante resolución, no se puede aliasar: {inconsistent}")
    conn.execute("DROP TABLE IF EXISTS case_id_alias")
    conn.execute(
        """CREATE TABLE case_id_alias (
            old_case_id TEXT PRIMARY KEY,
            canonical_case_id TEXT NOT NULL,
            mapping_basis TEXT NOT NULL,
            baseline_mapping_sha256 TEXT NOT NULL
        )"""
    )
    rows = [
        (old_case_id, next(iter(new_case_ids)), "preserved" if old_case_id in new_case_ids else "merged", baseline_sha256)
        for old_case_id, new_case_ids in sorted(old_case_to_new.items())
    ]
    conn.executemany(
        "INSERT INTO case_id_alias (old_case_id, canonical_case_id, mapping_basis, baseline_mapping_sha256) VALUES (?,?,?,?)",
        rows,
    )
    return len(rows)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, coltype: str = "TEXT") -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def _drop_column_if_exists(conn: sqlite3.Connection, table: str, column: str) -> None:
    """[AGREGADO 2026-09-18] limpia phase_family_id (columna de la version
    anterior del modelo de fase, conceptualmente invertida -- hallazgo de
    la revisión) sin dejar basura si el script corre de nuevo. Requiere SQLite
    3.35+ (DROP COLUMN); si la version bundleada no lo soporta, no falla el
    resto del script, solo deja la columna vieja sin usar."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in existing:
        try:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        except sqlite3.OperationalError:
            pass


def _resolve_database(conn: sqlite3.Connection, *, evidence_content_root: Path | None = None) -> int:
    _add_column_if_missing(conn, "project_review_queue", "decision")
    _add_column_if_missing(conn, "project_review_queue", "decision_reason")
    _add_column_if_missing(conn, "project_review_queue", "decided_by")
    _add_column_if_missing(conn, "project_review_queue", "decided_by_legacy")
    _add_column_if_missing(conn, "project_review_queue", "decision_source")
    _add_column_if_missing(conn, "project_review_queue", "decision_actor")
    _add_column_if_missing(conn, "project_review_queue", "decision_provenance_ref")
    conn.execute(
        "UPDATE project_review_queue SET decided_by_legacy=decided_by "
        "WHERE decided_by IS NOT NULL AND decided_by_legacy IS NULL"
    )

    rows = conn.execute(
        "SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b "
        "FROM project_review_queue ORDER BY rowid"
    ).fetchall()
    projects = dict(conn.execute("SELECT project_id, canonical_name FROM project ORDER BY project_id"))
    identity_adjudications = load_effective_project_identity_adjudications()
    validate_project_identity_adjudication_scope(projects, rows, identity_adjudications)
    partitions = dict(
        conn.execute("SELECT project_id, homonym_partition FROM project WHERE homonym_partition IS NOT NULL")
    )
    baseline, baseline_sha256 = load_case_baseline(projects)
    plan = resolve_case_components(
        projects,
        rows,
        partitions,
        baseline,
        classify_with_provenance,
        pair_classifier=lambda pid_a, name_a, pid_b, name_b: classify_project_pair_with_adjudications(
            pid_a, name_a, pid_b, name_b, identity_adjudications
        ),
    )
    validate_project_identity_adjudication_evidence(
        identity_adjudications, PROJECT_ROOT, content_root=evidence_content_root
    )
    validate_project_identity_adjudication_topology(
        plan.project_to_case, baseline, identity_adjudications
    )

    counts = {"merged": 0, "kept_separate": 0, "needs_human_review": 0}
    for rowid, pid_a, name_a, pid_b, name_b in rows:
        decision, reason, source, actor = plan.row_decisions[rowid]
        status = "merged" if decision is True else "kept_separate" if decision is False else "needs_human_review"
        counts[status] += 1
        conn.execute(
            "UPDATE project_review_queue SET resolved=?, decision=?, decision_reason=?, decision_source=?, "
            "decision_actor=?, decision_provenance_ref=?, decided_by=NULL WHERE rowid=?",
            (
                0 if status == "needs_human_review" else 1,
                status,
                reason,
                source,
                actor,
                decision_provenance_ref(
                    name_a,
                    name_b,
                    source,
                    project_ids=(pid_a, pid_b),
                    identity_adjudications=identity_adjudications,
                ),
                rowid,
            ),
        )

    all_pids = sorted(projects)
    _add_column_if_missing(conn, "project", "case_id")
    conn.executemany(
        "UPDATE project SET case_id=? WHERE project_id=?",
        [(plan.project_to_case[pid], pid) for pid in all_pids],
    )
    n_case_alias_rows = rebuild_case_id_alias(conn, baseline, plan.project_to_case, baseline_sha256)
    n_cases = len(set(plan.project_to_case.values()))
    n_homonym_vetoes = plan.homonym_vetoes

    def find(pid: str) -> str:
        return plan.project_to_case[pid]

    # [REDISENADO 2026-09-18, hallazgo conceptual de la revisión] nivel PROJECT_PHASE
    # del modelo de 3 niveles, con 3 relaciones explicitas (has_phase /
    # same_phase_alias / represents_phase) en vez de un unico union-find
    # simetrico -- ver el comentario largo junto a PHASE_OF_PAIRS_BY_SOL
    # mas arriba para el
    # razonamiento completo. Se elimina la columna project.phase_family_id de
    # la version anterior (estaba conceptualmente invertida, no se congela)
    # y se reemplaza por 2 tablas nuevas.
    _drop_column_if_exists(conn, "project", "phase_family_id")

    name_to_pid: dict[str, str] = {}
    dup_names: set[str] = set()
    for pid, name in conn.execute("SELECT project_id, canonical_name FROM project").fetchall():
        if name in name_to_pid:
            dup_names.add(name)
        else:
            name_to_pid[name] = pid

    phase_alias_uf: dict[str, str] = {}

    def phase_alias_find(x: str) -> str:
        while phase_alias_uf.get(x, x) != x:
            x = phase_alias_uf.get(x, x)
        return x

    def phase_alias_union(a: str, b: str) -> None:
        ra, rb = phase_alias_find(a), phase_alias_find(b)
        if ra != rb:
            phase_alias_uf[ra] = rb

    # [AGREGADO 2026-09-18, hallazgo de la revisión] dup_names se calculaba pero
    # nunca se usaba -- si un nombre canonico duplicado (Costanera Center,
    # Plaza Egana, por los homonimos ya separados) llegara a usarse en
    # PHASE_OF_PAIRS_BY_SOL o SAME_PHASE_ALIAS_PAIRS_BY_SOL, name_to_pid
    # elegiria en silencio uno de los 2 project_id -- fail-closed en vez de
    # eso. Hoy no dispara (ninguno de los 5+2 pares usa un nombre duplicado)
    # pero protege contra una futura adicion silenciosamente incorrecta.
    all_phase_names_used = {n for pair in PHASE_OF_PAIRS_BY_SOL for n in pair} | {
        n for pair in SAME_PHASE_ALIAS_PAIRS_BY_SOL for n in pair
    }
    dup_names_in_use = all_phase_names_used & dup_names
    if dup_names_in_use:
        raise RuntimeError(
            f"PHASE_OF_PAIRS_BY_SOL/SAME_PHASE_ALIAS_PAIRS_BY_SOL usan canonical_name duplicado(s) "
            f"{dup_names_in_use} -- name_to_pid no puede resolverlos sin ambiguedad, corregir con "
            f"project_id explicito antes de continuar."
        )

    missing_phase_names: list[str] = []
    for name_a, name_b in SAME_PHASE_ALIAS_PAIRS_BY_SOL:
        pid_a, pid_b = name_to_pid.get(name_a), name_to_pid.get(name_b)
        if not pid_a:
            missing_phase_names.append(name_a)
        if not pid_b:
            missing_phase_names.append(name_b)
        if pid_a and pid_b:
            phase_alias_union(pid_a, pid_b)

    phase_side_pids: set[str] = set()
    for _matrix_name, phase_name in PHASE_OF_PAIRS_BY_SOL:
        pid = name_to_pid.get(phase_name)
        if pid:
            phase_side_pids.add(pid)
        else:
            missing_phase_names.append(phase_name)
    for name_a, name_b in SAME_PHASE_ALIAS_PAIRS_BY_SOL:
        for n in (name_a, name_b):
            pid = name_to_pid.get(n)
            if pid:
                phase_side_pids.add(pid)

    def phase_id_for(pid: str) -> str:
        return _stable_phase_id(phase_alias_find(pid))

    # [ACTUALIZADO 2026-09-18, segunda ronda de precisiones de la revisión]
    # (1) relation_type ya no marca "same_phase_alias" para TODO
    # project_id del lado fase, incluidos los que no tienen ningun alias
    # real (ej. "Urbanya Etapa I" sola) -- ahora se distingue
    # "represents_phase" (unico representante, sin alias) de
    # "same_phase_alias" (2+ project_id que son la misma fase).
    # (2) "phase_of" renombrado a "has_phase" -- la direccion de la tabla
    # (project_id de la matriz -> phase_id) no cambia, solo el nombre, que
    # ahora coincide con como se lee la fila (PROJECT has_phase PHASE).
    # (3) constraints explicitos (PK compuesta + FOREIGN KEY) para que la
    # tabla sea auditable, no solo funcional.
    if missing_phase_names:
        raise RuntimeError(
            "Faltan nombres de proyecto configurados para PROJECT_PHASE; no se reemplazan las tablas: "
            f"{sorted(set(missing_phase_names))}"
        )

    # [CORREGIDO 2026-09-18, consecuencia real de activar PRAGMA
    # foreign_keys=ON] con las FK ahora exigidas de verdad, hay que borrar
    # la tabla HIJA (project_phase_link, que referencia a project_phase)
    # antes que la tabla PADRE -- el orden anterior (project_phase primero)
    # rompia con IntegrityError en cuanto se activo el enforcement real.
    conn.execute("DROP TABLE IF EXISTS project_phase_link")
    conn.execute("DROP TABLE IF EXISTS project_phase")
    conn.execute(
        """
        CREATE TABLE project_phase (
            phase_id TEXT PRIMARY KEY,
            case_id TEXT,
            phase_label TEXT,
            phase_number TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE project_phase_link (
            project_id TEXT NOT NULL,
            phase_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            evidence_source TEXT,
            PRIMARY KEY (project_id, phase_id, relation_type),
            FOREIGN KEY (project_id) REFERENCES project(project_id),
            FOREIGN KEY (phase_id) REFERENCES project_phase(phase_id)
        )
        """
    )

    project_case_id = dict(conn.execute("SELECT project_id, case_id FROM project").fetchall())
    pid_to_name = {p: n for n, p in name_to_pid.items()}
    phase_rows: dict[str, dict] = {}
    phase_link_rows: list[tuple[str, str, str, str]] = []

    # agrupar phase_side_pids por su raiz de phase_alias_uf para saber si
    # un grupo tiene 1 solo miembro (represents_phase) o 2+ (same_phase_alias)
    members_by_root: dict[str, list[str]] = {}
    for pid in phase_side_pids:
        root = phase_alias_find(pid)
        members_by_root.setdefault(root, []).append(pid)

    # [CORREGIDO 2026-09-18, hallazgo de la revisión] phase_side_pids es un set --
    # iterarlo directamente para decidir que alias queda como phase_label
    # dependia del orden (no determinista) de iteracion del set: el mismo
    # export podia mostrar un alias distinto entre corridas identicas (el
    # phase_id y todas las relaciones seguian siendo correctos, solo
    # cambiaba cosmeticamente la etiqueta mostrada). Se elige ahora de forma
    # deterministica por grupo, con una regla explicita: (1) prefiere el
    # nombre con "Etapa/Fase N" explicito, (2) entre esos, el mas corto,
    # (3) empate -> orden lexicografico. sorted() sobre iterables ya
    # deterministas (listas, no sets) en todo lo demas.
    def _phase_label_sort_key(pid: str) -> tuple[int, int, str]:
        name = pid_to_name[pid]
        has_etapa = 0 if _etapa_tokens(name) else 1
        return (has_etapa, len(name), name)

    for root, members in members_by_root.items():
        members_sorted = sorted(members, key=_phase_label_sort_key)
        chosen_pid = members_sorted[0]
        chosen_name = pid_to_name[chosen_pid]
        etapa_tok = _etapa_tokens(chosen_name)
        this_phase_id = _stable_phase_id(root)
        phase_rows[this_phase_id] = {
            "phase_id": this_phase_id,
            "case_id": project_case_id.get(chosen_pid),
            "phase_label": chosen_name,
            "phase_number": ",".join(sorted(etapa_tok)) if etapa_tok else None,
        }
        relation = "same_phase_alias" if len(members) > 1 else "represents_phase"
        for pid in members_sorted:
            name = pid_to_name[pid]
            phase_link_rows.append((pid, this_phase_id, relation, f"nombre propio: {name!r}"))

    # dedupe por (matrix_pid, phase_id): 2+ pares de PHASE_OF_PAIRS_BY_SOL
    # pueden resolver al MISMO phase_id (ej. "Mall Vivo" es matriz tanto de
    # "Mall Vivo Santiago Etapa II" como de su alias "Centro Comercial Mall
    # Vivo Santiago Etapa II", que via same_phase_alias terminan siendo un
    # solo phase_id) -- sin dedupe, se violaria la PRIMARY KEY compuesta.
    has_phase_by_key: dict[tuple[str, str], list[str]] = {}
    for matrix_name, phase_name in PHASE_OF_PAIRS_BY_SOL:
        matrix_pid = name_to_pid.get(matrix_name)
        phase_pid = name_to_pid.get(phase_name)
        if not matrix_pid or not phase_pid:
            continue
        this_phase_id = phase_id_for(phase_pid)
        has_phase_by_key.setdefault((matrix_pid, this_phase_id), []).append(
            f"{matrix_name!r} -> {phase_name!r}"
        )
    for (matrix_pid, this_phase_id), evidences in has_phase_by_key.items():
        phase_link_rows.append(
            (matrix_pid, this_phase_id, "has_phase", "[Sol 2026-09-18] " + "; ".join(evidences))
        )

    conn.executemany(
        "INSERT INTO project_phase (phase_id, case_id, phase_label, phase_number) VALUES (:phase_id, :case_id, :phase_label, :phase_number)",
        list(phase_rows.values()),
    )
    conn.executemany(
        "INSERT INTO project_phase_link (project_id, phase_id, relation_type, evidence_source) VALUES (?,?,?,?)",
        phase_link_rows,
    )
    relation_counts = rebuild_project_relations(conn)

    n_phases = len(phase_rows)
    n_has_phase_links = sum(1 for r in phase_link_rows if r[2] == "has_phase")
    n_same_phase_alias_links = sum(1 for r in phase_link_rows if r[2] == "same_phase_alias")
    n_represents_phase_links = sum(1 for r in phase_link_rows if r[2] == "represents_phase")

    # [AGREGADO 2026-09-18, salvaguarda general pedida por la revisión] verifica, para
    # cada homonimo conocido (agrupado por su norm base, ej. "costanera
    # center"), que el numero de case_id resultantes entre sus particiones
    # sea >= al numero de particiones esperadas -- si un homonimo se
    # reconecta silenciosamente por otra via (no solo la ya vetada arriba),
    # esto lo hace fallar de forma ruidosa en vez de dejarlo pasar.
    partitions_by_base: dict[str, set[str]] = {}
    for pid, partition in partitions.items():
        base = partition.split("::", 1)[0]
        partitions_by_base.setdefault(base, set()).add(partition)
    homonym_check_failures = []
    for base, expected_partitions in partitions_by_base.items():
        pids_for_base = [pid for pid, p in partitions.items() if p.split("::", 1)[0] == base]
        resulting_case_ids = {find(pid) for pid in pids_for_base}
        if len(resulting_case_ids) < len(expected_partitions):
            homonym_check_failures.append(
                {"homonym_base": base, "n_partitions_expected": len(expected_partitions), "n_case_ids_resulting": len(resulting_case_ids)}
            )
    if homonym_check_failures:
        raise RuntimeError(
            f"Homonimos reconectados por case_id pese a KNOWN_HOMONYM_SPLITS: {homonym_check_failures}"
        )

    summary = {
        "n_pairs_reviewed": len(rows),
        "decisions": counts,
        "n_projects_before": len(all_pids),
        "n_cases_after_merge": n_cases,
        "n_projects_merged_away": len(all_pids) - n_cases,
        "project_relations": relation_counts,
        "n_homonym_partition_vetoes": n_homonym_vetoes,
        "homonym_partitions_checked": len(partitions_by_base),
        "case_id_baseline": {
            "path": str(CASE_BASELINE.relative_to(PROJECT_ROOT)),
            "mapping_sha256": baseline_sha256,
            "n_project_ids": len(baseline),
            "n_old_case_ids_mapped": n_case_alias_rows,
        },
        "modelo_3_niveles": {
            "n_project_ids": len(all_pids),
            "n_cases_after_merge": n_cases,
            "n_phases": n_phases,
            "n_has_phase_links": n_has_phase_links,
            "n_same_phase_alias_links": n_same_phase_alias_links,
            "n_represents_phase_links": n_represents_phase_links,
            "missing_phase_names": missing_phase_names,
            "cobertura": (
                "PARCIAL Y AUDITADA, no exhaustiva -- [precision pedida por Sol, ronda 12] esta capa "
                "solo cubre los 26 pares que Sol reviso a mano (5 has_phase + 2 same_phase_alias). La "
                "ausencia de un project_id en project_phase_link significa 'no adjudicado como fase "
                "todavia', NUNCA 'este proyecto no tiene fases'. La cola de 255 pares tiene otros "
                "candidatos evidentes (Alto Las Condes vs Alto Las Condes 2, Distrito Cordillera I/II, "
                "La Maestranza I/II, Vespucio Oriente/II) que NO se agregaron aqui sin revision -- "
                "poblar el resto de una ontologia de fases exhaustiva del corpus es un proyecto de "
                "resolucion ontologica separado, no otra heuristica agregada al bridge."
            ),
            "nota": (
                "[REDISENADO 2026-09-18, hallazgo conceptual de Sol] PROJECT=project_id (fino). "
                "PROJECT_PHASE=tablas project_phase/project_phase_link, con 3 relaciones EXPLICITAS: "
                "has_phase (project_id de la MATRIZ -> phase_id de una fase especifica dentro de ella, "
                "asimetrica; renombrada de 'phase_of' -- Sol senalo que 'PROJECT has_phase PHASE' se lee "
                "mejor que 'PROJECT phase_of PHASE'), same_phase_alias (2+ project_id que son la MISMA "
                "fase con redaccion distinta) y represents_phase (un unico project_id que representa una "
                "fase sin tener ningun alias -- distincion agregada tras precision de Sol: antes TODO "
                "project_id del lado fase se marcaba same_phase_alias aunque no tuviera alias real). "
                "CASE=case_id (el mas amplio, incluye fusiones por cualquier razon). Ya NO existe "
                "project.phase_family_id (version anterior, invertida: fusionaba matriz y fase "
                "en un solo grupo simetrico -- ver active-context.md ronda 11 para el caso Urbanya que "
                "expuso el error)."
            ),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    conn = sqlite3.connect(WAREHOUSE)
    try:
        # PRAGMA debe ejecutarse antes de BEGIN; la transacción abarca DDL,
        # decisiones, case_id, aliases y relaciones de fases.
        conn.execute("PRAGMA foreign_keys = ON")

        def operation(connection: sqlite3.Connection) -> int:
            # Se valida dentro del BEGIN IMMEDIATE para que otra escritura no
            # pueda cambiar el warehouse entre el preflight y la resolución.
            evidence_check = validate_manual_decision_evidence(connection, PROJECT_ROOT)
            print(
                "[preflight evidencia manual] "
                f"{evidence_check['pairs']} pares, {evidence_check['references']} referencias verificadas; "
                f"{evidence_check['literal_raw_mentions']} raw_mention literales, "
                f"{len(evidence_check['nonliteral_raw_mentions'])} derivadas/no literales"
            )
            baseline_hash_checked = validate_initial_baseline_warehouse_hash(
                connection, CASE_BASELINE, WAREHOUSE
            )
            print(f"[preflight baseline] source_warehouse_sha256 verificado={baseline_hash_checked}")
            return _resolve_database(connection)

        return run_atomically(conn, operation)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
