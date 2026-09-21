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
from pathlib import Path
from typing import Any


def _stable_phase_id(*parts: str) -> str:
    return "phase:" + hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:24]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = PROJECT_ROOT / "Auditoria" / "integracion_v1" / "warehouse_v3_2_bridge.sqlite"

GENERIC_BLOCKLIST = {"data center", "vespucio", "ciudad empresarial", "lo aguirre", "las americas", "supermercado lider"}

_NUMERAL_RE = re.compile(r"\b(i{1,3}|iv|v|vi{0,3}|\d+)\b", re.IGNORECASE)
_ETAPA_RE = re.compile(r"\b(etapa|fase)\s+([ivx\d]+)\b", re.IGNORECASE)


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
    ("Hotel Sheraton", "Hotel Sheraton Santiago"): (True, "mismo hotel"),
    ("Hotel Sheraton", "proyecto de construcción en perímetro del Hotel Sheraton Santiago"): (False, "proyecto de construccion distinto, adyacente al hotel"),
    ("Reserva La Dehesa", "Reserva La Dehesa (ex Chaguay)"): (True, "mismo sitio, nombre anterior entre parentesis"),
    ("Desnitrificador SCR para Caldera de Ciclo Combinado de Central Nueva Renca", "Nueva Renca"): (True, "obra especifica en la misma central"),
    ("Chaguay", "Habilitación de caminos de acceso e instalaciones complementarias de la subdivisión agrícola Chaguay"): (True, "misma subdivision Chaguay"),
    ("Chaguay", "Reserva La Dehesa (ex Chaguay)"): (True, "Chaguay es el nombre anterior del mismo sitio"),
    ("Eco Egaña Sustentable", "Eco Egaña"): (True, "mismo proyecto"),
    ("Eco Egaña Sustentable", "Egaña Sustentable"): (True, "mismo proyecto"),
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
}


def classify(name_a: str, name_b: str) -> tuple[bool, str]:
    if (name_a, name_b) in MANUAL_DECISIONS:
        return MANUAL_DECISIONS[(name_a, name_b)]
    if (name_b, name_a) in MANUAL_DECISIONS:
        return MANUAL_DECISIONS[(name_b, name_a)]
    if is_generic_bare_name(name_a, name_b) or is_generic_bare_name(name_b, name_a):
        return False, "nombre generico en lista de bloqueo (aparece en multiples proyectos distintos del corpus)"
    if has_explicit_stage_conflict(name_a, name_b):
        return False, "Etapa/Fase explicita distinta entre los dos nombres (palabra etapa/fase presente en el texto)"
    if has_bare_trailing_numeral_conflict(name_a, name_b):
        return None, (
            "numeral suelto al final de uno de los nombres, sin decision manual explicita -- "
            "[hallazgo de Sol 2026-09-18] un numeral suelto suele ser una direccion, no una fase; "
            "requiere revision humana, no se asume kept_separate automaticamente"
        )
    return None, "sin regla aplicable ni decision manual -- requiere revision humana adicional"


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


def main() -> int:
    conn = sqlite3.connect(WAREHOUSE)
    # [AGREGADO 2026-09-18, ultima precision de la revisión] SQLite declara las
    # FOREIGN KEY de project_phase_link pero no las hace cumplir por
    # conexion salvo que se active explicitamente -- sin esto, las FK son
    # solo documentacion del schema, no una restriccion real.
    conn.execute("PRAGMA foreign_keys = ON")
    # Idempotente: este script puede correr mas de una vez sobre la misma base
    # (ej. para aplicar una corrección como la auditoría de 2026-09-18)
    # sin fallar por "duplicate column name" en una segunda corrida.
    _add_column_if_missing(conn, "project_review_queue", "decision")
    _add_column_if_missing(conn, "project_review_queue", "decision_reason")
    _add_column_if_missing(conn, "project_review_queue", "decided_by")

    rows = conn.execute("SELECT rowid, project_id_a, canonical_name_a, project_id_b, canonical_name_b FROM project_review_queue").fetchall()

    # [AGREGADO 2026-09-18, hallazgo BLOQUEANTE de la revisión] "separar un homonimo a
    # nivel de project_id no basta": Costanera Center Chile y Costanera
    # Center Argentina (KNOWN_HOMONYM_SPLITS en build_case_project_bridge.py)
    # volvian a conectarse por case_id porque AMBAS pasaban por el mismo par
    # con nombre identico ("Costanera Center" vs "mall Costanera Center" ->
    # merged), y classify() decide por NOMBRE, sin saber que hay 2 project_id
    # distintos detras. homonym_partition (columna nueva en `project`) marca
    # la particion de cada mitad de un homonimo conocido -- una union entre
    # dos project_id de particiones DISTINTAS del mismo homonimo se veta
    # aqui, sin importar lo que diga classify() para ese par de nombres.
    partitions = dict(conn.execute("SELECT project_id, homonym_partition FROM project WHERE homonym_partition IS NOT NULL").fetchall())

    union_find: dict[str, str] = {}
    # Por cada raiz actual del union-find, el conjunto de homonym_partition
    # (de KNOWN_HOMONYM_SPLITS) ya absorbidas transitivamente en ese
    # componente -- permite vetar una union INDIRECTA (via un tercer
    # project_id sin particion propia, ej. "mall Costanera Center" haciendo
    # de puente entre las dos mitades de "Costanera Center"), no solo una
    # union directa entre dos project_id con particiones distintas.
    partitions_in_component: dict[str, set[str]] = {
        pid: {partition} for pid, partition in partitions.items()
    }

    def find(x: str) -> str:
        while union_find.get(x, x) != x:
            x = union_find.get(x, x)
        return x

    def would_reconnect_incompatible_homonym(a: str, b: str) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        merged = partitions_in_component.get(ra, set()) | partitions_in_component.get(rb, set())
        bases: dict[str, set[str]] = {}
        for p in merged:
            bases.setdefault(p.split("::", 1)[0], set()).add(p)
        return any(len(v) > 1 for v in bases.values())

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            merged = partitions_in_component.pop(ra, set()) | partitions_in_component.pop(rb, set())
            union_find[ra] = rb
            if merged:
                partitions_in_component[rb] = merged

    counts = {"merged": 0, "kept_separate": 0, "needs_human_review": 0}
    n_homonym_vetoes = 0
    for rowid, pid_a, name_a, pid_b, name_b in rows:
        decision, reason = classify(name_a, name_b)
        if decision is True and would_reconnect_incompatible_homonym(pid_a, pid_b):
            n_homonym_vetoes += 1
            decision = False
            reason = (
                f"VETO homonym_partition [Sol 2026-09-18]: classify() decidia merged por nombre "
                f"('{reason}'), pero fusionar project_id_a y project_id_b reconectaria (directa o "
                f"transitivamente, ej. via un tercer project_id puente sin particion propia) dos "
                f"particiones distintas de un homonimo conocido (KNOWN_HOMONYM_SPLITS) -- vetado."
            )
        if decision is True:
            counts["merged"] += 1
            status = "merged"
            union(pid_a, pid_b)
        elif decision is False:
            counts["kept_separate"] += 1
            status = "kept_separate"
        else:
            counts["needs_human_review"] += 1
            status = "needs_human_review"
        # [CORRECCION 2026-09-18, hallazgo de la revisión punto 5] resolved=1 se
        # escribia incondicionalmente para las 3 ramas, incluida
        # needs_human_review -- contradictorio (una fila sin decision no
        # deberia marcarse como resuelta). Sin efecto visible en los 253
        # actuales porque terminaron con needs_human_review=0, pero es un bug
        # real y latente para cualquier cola futura con pares sin regla ni
        # decision manual.
        conn.execute(
            "UPDATE project_review_queue SET resolved=?, decision=?, decision_reason=?, decided_by=? WHERE rowid=?",
            (
                0 if status == "needs_human_review" else 1,
                status,
                reason,
                "claude_sonnet_5_manual_review_2026-09-17_corregido_2026-09-18_tras_auditoria_sol",
                rowid,
            ),
        )

    all_pids = [r[0] for r in conn.execute("SELECT project_id FROM project").fetchall()]
    for pid in all_pids:
        find(pid)  # asegura que cada project_id tenga una raiz (a si mismo si no fue fusionado)

    _add_column_if_missing(conn, "project", "case_id")
    for pid in all_pids:
        conn.execute("UPDATE project SET case_id=? WHERE project_id=?", (find(pid), pid))
    conn.commit()

    n_cases = len(set(find(pid) for pid in all_pids))

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
    conn.commit()

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
        "n_homonym_partition_vetoes": n_homonym_vetoes,
        "homonym_partitions_checked": len(partitions_by_base),
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
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
