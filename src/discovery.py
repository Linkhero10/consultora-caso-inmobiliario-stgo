#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descubrimiento de noticias via Bright Data SERP API — Caso piloto inmobiliario Santiago.

Patron adaptado de:
- D:\\Analisis conflictos\\02_externo\\encargo_profesor\\Trabajo\\SAM-Cordillera\\scripts\\serpapi_discovery.py
  (estructura de contrato, presupuesto, guardado incremental)
- D:\\Analisis conflictos\\01_proyecto_universidad\\02_filtrado_llm\\02_pipeline_v2_prefiltro_base_nueva_20k_a_7k\\02_enrichment\\url_resolver.py
  (RateLimiter anti-bloqueo, resolucion de links de Google)

Verificado empiricamente 2026-09-11 antes de escribir este script:
- Bright Data zona 'emprendimiento1' (SERP API, data_format=parsed_light) funciona.
- Geo-targeting correcto: hl=es&gl=cl en la URL de Google (NO un campo "country" en
  el payload -- eso dio resultados inconsistentes en pruebas reales).
- El campo "link" es una ruta relativa /goto?url=<token> -- resolver con
  requests.get("https://www.google.com" + link, allow_redirects=True).url
  YA es suficiente (confirmado con un caso real: resolvio a lascondes.cl).
- Google devuelve 429/502 con llamadas repetidas en <30s sobre la misma zona --
  este script aplica delay progresivo + backoff, no solo per_domain_delay_seconds.

Uso:
  python brightdata_discovery.py --dry-run          # 1 query de prueba, no guarda
  python brightdata_discovery.py --limit 5          # primeras 5 queries del plan
  python brightdata_discovery.py                    # todas las queries del plan
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("brightdata_discovery")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
FUENTES_DIR = PROJECT_ROOT / "Fuentes" / "brightdata_discovery"
BRIGHTDATA_ENDPOINT = "https://api.brightdata.com/request"
BRIGHTDATA_ZONE = "emprendimiento1"
DISCOVERY_PLAN_VERSION = "discovery_plan_v2"

COMUNAS = [
    # Las 32 comunas de la Provincia de Santiago (verificado contra Wikipedia
    # 2026-09-11). Ampliado desde las 4 comunas orientales originales por
    # decision del usuario 2026-09-11: 12 registros era insuficiente para un
    # caso de portafolio, hay que ampliar a toda el area metropolitana.
    "Santiago", "Vitacura", "San Ramón", "San Miguel", "San Joaquín", "Renca",
    "Recoleta", "Quinta Normal", "Quilicura", "Pudahuel", "Providencia",
    "Peñalolén", "Pedro Aguirre Cerda", "Ñuñoa", "Maipú", "Macul", "Lo Prado",
    "Lo Espejo", "Lo Barnechea", "Las Condes", "La Reina", "La Pintana",
    "La Granja", "La Florida", "La Cisterna", "Independencia", "Huechuraba",
    "Estación Central", "El Bosque", "Conchalí", "Cerro Navia", "Cerrillos",
]
# Comunas con nombre ambiguo (colisionan con sustantivo comun o toponimo
# compartido con otro pais) -- hallazgo del subagente auditor 2026-09-12,
# verificado con busqueda real (la-municipalidad.cl distingue "Santiago
# Centro" de "Santiago Capital" precisamente por esta ambiguedad; Recoleta
# colisiona con el barrio de Buenos Aires; Independencia con el sustantivo
# comun; La Florida con toponimos de otros paises). Se ancla la busqueda con
# "comuna de X" solo para estas 4, sin tocar el patron de las otras 28.
COMUNA_QUERY_ANCHOR = {
    "Santiago": '"comuna de Santiago"',
    "Independencia": '"comuna de Independencia"',
    "La Florida": '"comuna de La Florida"',
    "Recoleta": '"comuna de Recoleta"',
}

# Sectores/barrios con conflictividad inmobiliaria real y verificada (no
# inventados) dentro de comunas de alta actividad -- hallazgo del subagente
# auditor 2026-09-12: anclar solo a nivel de comuna sub-captura sistematica-
# mente estos casos porque los articulos rara vez mencionan el nombre de la
# comuna completa junto al termino en el mismo fragmento indexado.
SECTORES = {
    "Ñuñoa": ["Plaza Ñuñoa", "Barrio Italia Ñuñoa"],
    "Providencia": ["Bellavista Providencia", "Las Lilas Providencia", "Santa Isabel Providencia", "Los Naranjos Providencia"],
    "Santiago": ["Barrio Yungay"],
    "San Miguel": ["Ciudad del Niño San Miguel"],
    "Las Condes": ["Resistencia ABC1"],
}
# Subconjunto de terminos mas fuertes para usar con anclas de sector (evita
# explosion combinatoria de sector x los 16 terminos completos).
TERMINOS_SECTOR = [
    "recurso de protección",
    "reclamo de ilegalidad",
    "invalidación de permisos de edificación",
    "guetos verticales",
    "megaproyecto inmobiliario oposición",
    "gentrificación",
    "oposición vecinal edificio",
    "denuncia contraloría edificación",
]

TERMINOS = [
    # Revisado 2026-09-12 tras auditoria de un subagente experto con busqueda
    # real (ver bitacora FARO): el vocabulario original (DS19 rechazo
    # vecinos, conflicto inmobiliario, especulacion inmobiliaria) no es el
    # que usa la prensa chilena real para este fenomeno -- confirmado
    # empiricamente en la prueba piloto (trajo puro ruido institucional de
    # MINVU/Serviu). Reemplazado por vocabulario judicial/periodistico real
    # encontrado en casos documentados (Estacion Central "guetos verticales",
    # San Miguel "megaproyecto", Providencia "invalidacion de permisos").
    "recurso de protección",
    "reclamo de ilegalidad",
    "invalidación de permisos de edificación",
    "guetos verticales",
    "megaproyecto inmobiliario oposición",
    "gentrificación",
    "oposición vecinal edificio",
    "vivienda social integración conflicto",
    "edificio altura densidad reclamo",
    "rechazo proyecto inmobiliario",
    "denuncia contraloría edificación",
    "concejo municipal rechaza permiso edificación",
    "junta de vecinos inmobiliaria",
    "densificación vecinos reclamo",
    "corte de apelaciones proyecto inmobiliario",
    "impugnación plan regulador",
]
PERIODOS = [
    # Ventanas temporales (revisado 2026-09-12): DS19 nace por Decreto
    # Supremo N 19 del 14/07/2016, y casos documentados (Ñuñoa/Plaza Ñuñoa
    # 2006-2007, Barrio Yungay 2005-2009) son anteriores a 2018 -- la
    # ventana original dejaba fuera el origen del fenomeno. Se agrega
    # 2014-2017 (hallazgo del subagente auditor 2026-09-12).
    {"id": "2014_2017", "cd_min": "1/1/2014", "cd_max": "12/31/2017"},
    {"id": "2018_2020", "cd_min": "1/1/2018", "cd_max": "12/31/2020"},
    {"id": "2021_2023", "cd_min": "1/1/2021", "cd_max": "12/31/2023"},
    {"id": "2024_2026", "cd_min": "1/1/2024", "cd_max": "9/11/2026"},
]

# Dominios institucionales/comerciales que dominan el ranking con contenido
# no contencioso (tramites, avisos de venta) -- excluirlos de las queries
# generales de comuna es mas barato que gastar presupuesto de LLM
# clasificando avisos. Hallazgo del subagente auditor 2026-09-12.
EXCLUDE_DOMAINS = (
    "-site:minvu.gob.cl -site:serviu.cl -site:portalinmobiliario.com -site:pabellon.cl "
    # Agregado 2026-09-13 (Claude) con evidencia real del log de fulltext_v3:
    # 742/743 de los http_error_400 y 381/469 de los "insuficiente" en las
    # primeras ~2500 extracciones eran facebook.com/instagram.com -- 45%
    # del esfuerzo de extraccion desperdiciado en dominios que bloquean el
    # scraping sin sesion. Excluirlos de discovery ahorra presupuesto de
    # Bright Data y de extraccion en futuras corridas incrementales. No
    # afecta lo ya descubierto/extraido -- solo aplica a queries nuevas.
    "-site:facebook.com -site:instagram.com -site:tiktok.com"
)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def build_query_plan() -> list[dict[str, str]]:
    plan = []
    for comuna in COMUNAS:
        anchor = COMUNA_QUERY_ANCHOR.get(comuna, f'"{comuna}"')
        for termino in TERMINOS:
            for periodo in PERIODOS:
                plan.append({
                    "comuna": comuna,
                    "termino": termino,
                    "periodo": periodo["id"],
                    "nivel": "comuna",
                    "query": f'"{termino}" {anchor} {EXCLUDE_DOMAINS}',
                    "cd_min": periodo["cd_min"],
                    "cd_max": periodo["cd_max"],
                })
    for comuna, sectores in SECTORES.items():
        for sector in sectores:
            for termino in TERMINOS_SECTOR:
                for periodo in PERIODOS:
                    plan.append({
                        "comuna": comuna,
                        "termino": termino,
                        "periodo": periodo["id"],
                        "nivel": f"sector:{sector}",
                        "query": f'"{termino}" "{sector}"',
                        "cd_min": periodo["cd_min"],
                    "cd_max": periodo["cd_max"],
                })
    for item in plan:
        item["query_hash"] = query_hash_for_item(item)
    return plan


class BrightDataRateLimiter:
    """Adaptado de RateLimiter en url_resolver.py del proyecto de tesis --
    mismo principio (delay progresivo + backoff en errores), ajustado a lo
    que se observo empiricamente con Bright Data (429/502 con <30s entre
    llamadas a la misma zona)."""

    def __init__(self, base_delay: float = 12.0, max_circuit_trips: int = 30) -> None:
        self.base_delay = base_delay
        self.last_call: float = 0.0
        self.consecutive_errors = 0
        self.max_circuit_trips = max_circuit_trips
        self.total_circuit_trips = 0

    def wait(self) -> None:
        now = time.time()
        elapsed = now - self.last_call
        delay = self.base_delay + random.uniform(0, 6) + (self.consecutive_errors * 10)
        if elapsed < delay:
            sleep_for = delay - elapsed
            logger.info("Esperando %.1fs antes de la siguiente consulta (anti-bloqueo)", sleep_for)
            time.sleep(sleep_for)
        self.last_call = time.time()

    def record_error(self) -> None:
        """Corregido 2026-09-12 tras caida real en produccion: un bloqueo
        temporal de Google/Bright Data sostenido por ~17 minutos (502 en
        cascada) mataba el proceso completo con RuntimeError a mitad de una
        corrida de 9-10 horas desatendida, perdiendo el resto del lote sin
        que nadie se enterara hasta revisar manualmente. Ahora, al llegar al
        umbral de errores consecutivos, hace una pausa larga (circuit
        breaker con cooldown creciente, tope 30 min) y reintenta en vez de
        morir -- solo se rinde de verdad si el circuito salta mas de
        max_circuit_trips veces en toda la corrida (eso si indica algo
        realmente roto: credenciales invalidas, zona eliminada, etc.)."""
        self.consecutive_errors = min(self.consecutive_errors + 1, 5)
        if self.consecutive_errors >= 5:
            self.total_circuit_trips += 1
            if self.total_circuit_trips > self.max_circuit_trips:
                raise RuntimeError(
                    f"FAIL FAST: circuito salto {self.total_circuit_trips} veces en esta corrida "
                    "-- esto ya no parece un bloqueo temporal, revisar zona/credito antes de seguir"
                )
            cooldown = min(300 * self.total_circuit_trips, 1800)
            logger.warning(
                "Circuito abierto (%d errores consecutivos, trip #%d/%d) -- pausando %.0fs antes de reintentar",
                self.consecutive_errors, self.total_circuit_trips, self.max_circuit_trips, cooldown,
            )
            time.sleep(cooldown)
            self.consecutive_errors = 0

    def record_success(self) -> None:
        self.consecutive_errors = max(0, self.consecutive_errors - 1)


MAX_QUERY_RETRIES = 3


def brightdata_search(query: str, api_key: str, limiter: BrightDataRateLimiter, cd_min: str = "", cd_max: str = "") -> dict[str, Any] | None:
    """Fix 2026-09-13 (hallazgo real tras cerrar la corrida de 2336 queries:
    628/2336 combos quedaron sin ninguna fila, y hubo 692 fallos de red en
    todo el log -- la version anterior de esta funcion no reintentaba la
    MISMA query ante un 502/timeout, la devolvia como None de inmediato y
    el loop de main() simplemente pasaba a la siguiente combinacion del
    plan, perdiendo esa consulta para siempre sin poder distinguir "0
    resultados reales" de "fallo transitorio nunca reintentado". El circuit
    breaker (BrightDataRateLimiter.record_error) pausa la corrida entera
    ante rachas de errores, pero nunca reintentaba la consulta puntual que
    fallo. Ahora se reintenta hasta MAX_QUERY_RETRIES veces la MISMA query
    antes de rendirse y contarla como error real de cara al circuit
    breaker."""
    google_url = f"https://www.google.com/search?q={requests.utils.quote(query)}&hl=es&gl=cl"
    if cd_min and cd_max:
        google_url += f"&tbs=cdr:1,cd_min:{requests.utils.quote(cd_min)},cd_max:{requests.utils.quote(cd_max)}"
    payload = {
        "zone": BRIGHTDATA_ZONE,
        "url": google_url,
        "format": "json",
        "data_format": "parsed_light",
    }
    last_exc: Exception | None = None
    for attempt in range(1, MAX_QUERY_RETRIES + 1):
        limiter.wait()
        try:
            resp = requests.post(
                BRIGHTDATA_ENDPOINT,
                json=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            resp.raise_for_status()
            outer = resp.json()
            inner_status = outer.get("status_code")
            if inner_status and inner_status != 200:
                logger.warning(
                    "Bright Data devolvio status_code interno %s para query %r (intento %d/%d): %s",
                    inner_status, query, attempt, MAX_QUERY_RETRIES, str(outer.get("body"))[:200],
                )
                if attempt < MAX_QUERY_RETRIES:
                    # Fix 2026-09-13 (muestra de 25 real): Bright Data
                    # devuelve un 429 explicito diciendo "minimum of 15
                    # seconds" si se reintenta la MISMA query antes de eso
                    # -- con 3s/6s de espera, el intento 2 llegaba
                    # demasiado pronto y chocaba con ese 429 en vez de dar
                    # una segunda oportunidad real. 16s de piso respeta ese
                    # minimo documentado.
                    time.sleep(max(16.0, 3.0 * attempt))
                    continue
                limiter.record_error()
                return None
            body = outer.get("body")
            inner = json.loads(body) if isinstance(body, str) else body
            limiter.record_success()
            return inner
        except Exception as exc:  # noqa: BLE001 - se quiere capturar y loguear cualquier fallo de red/parseo
            last_exc = exc
            logger.warning("Error en busqueda %r (intento %d/%d): %s", query, attempt, MAX_QUERY_RETRIES, exc)
            if attempt < MAX_QUERY_RETRIES:
                time.sleep(max(16.0, 3.0 * attempt))
                continue
    logger.warning("Agotados %d reintentos para %r: %s", MAX_QUERY_RETRIES, query, last_exc)
    limiter.record_error()
    return None


def resolve_goto_link(relative_link: str, session: requests.Session) -> tuple[str, str]:
    """Resuelve un link /goto?url=... de Bright Data siguiendo la redireccion HTTP.
    Confirmado empiricamente 2026-09-11: alcanza con esto, sin necesitar
    googlenewsdecoder (esa libreria esta pensada para tokens de news.google.com,
    no para este redirect general de busqueda)."""
    if relative_link.startswith("http"):
        return relative_link, "ya_absoluta"
    full_url = "https://www.google.com" + relative_link
    try:
        resp = session.get(full_url, allow_redirects=True, timeout=15)
        return resp.url, "follow_redirect"
    except Exception as exc:  # noqa: BLE001
        logger.debug("No se pudo resolver %s: %s", relative_link[:60], exc)
        return "", "error_resolucion"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def query_hash_for_item(item: dict[str, Any]) -> str:
    """Identity of the complete query plan item, not only its tuple key."""
    payload = {
        "plan_version": DISCOVERY_PLAN_VERSION,
        "comuna": item.get("comuna", ""),
        "termino": item.get("termino", ""),
        "periodo": item.get("periodo", ""),
        "nivel": item.get("nivel", ""),
        "query": item.get("query", ""),
        "cd_min": item.get("cd_min", ""),
        "cd_max": item.get("cd_max", ""),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(canonical)


def already_queried_combos(manifest_path: Path) -> set[tuple[str, str, str, str]]:
    """Combos (comuna,termino,periodo,nivel) ya presentes en el manifest --
    permite reanudar tras una caida sin repetir consultas ya hechas.
    Agregado 2026-09-12 tras una caida real a mitad de una corrida de
    varias horas.

    Fix 2026-09-12 (hallazgo la auditoría cruzada, confirmado real): la version
    anterior marcaba un combo como "hecho" con solo UNA fila de resultado
    organico presente. resolve_goto_link() nunca lanza excepcion (tiene su
    propio try/except), pero el PROCESO ENTERO puede morir externamente
    (kill de OS, cierre de terminal -- ya paso una vez con classify_luna.py
    en esta misma sesion) a mitad de escribir los resultados organicos de
    una consulta, dejando algunas filas en disco y perdiendo el resto de
    forma indistinguible de una consulta que de verdad solo tenia esos
    resultados. Ahora solo cuenta como "hecho" un combo que tenga su evento
    explicito query_completed (escrito DESPUES de procesar todos los
    resultados organicos de esa consulta, incluyendo el caso de 0
    resultados). Una fila organica sola, sin su query_completed
    correspondiente, deja el combo pendiente y se vuelve a consultar --
    esto puede producir duplicados (misma query, mismos ranks ya vistos)
    pero eso es seguro: se deduplican mas adelante por record_hash/URL, y
    es preferible a perder resultados de forma silenciosa."""
    done: set[tuple[str, str, str, str]] = set()
    if not manifest_path.exists():
        return done
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("event") == "query_completed":
            done.add((r.get("comuna", ""), r.get("termino", ""), r.get("periodo", ""), r.get("nivel", "")))
    return done


def already_queried_query_hashes(manifest_path: Path) -> set[str]:
    """Strict completion set keyed by the full versioned query identity."""
    done: set[str] = set()
    if not manifest_path.exists():
        return done
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "query_completed" and record.get("query_hash"):
            done.add(str(record["query_hash"]))
    return done


def legacy_any_row_combos(manifest_path: Path) -> set[tuple[str, str, str, str]]:
    """Comportamiento PRE-fix (2026-09-12): un combo cuenta como hecho con
    solo tener una fila, sin exigir query_completed.

    Existe UNICAMENTE para la transicion de la corrida activa iniciada con
    el codigo viejo (0 eventos query_completed en su manifest a la fecha
    de este fix -- confirmado por la auditoría cruzada,
    Auditoria/codex_fleet/OPEN_FINDINGS_20260912.md). Sin esto, reanudar esa
    corrida con already_queried_combos() (que exige query_completed) vería
    0 combos completos y re-consultaria las 2336 queries del plan desde
    cero, gastando creditos de Bright Data de forma real y evitable.

    Riesgo residual, dicho explicito y no oculto (hallazgo de la auditoría cruzada,
    turn-20260912-232630-82c57a): un combo con solo 1-2 filas de un
    resultado que en verdad tenia mas puede haberse cortado a mitad y
    quedaria incorrectamente marcado "completo" con esta funcion. No hay
    forma de probar retroactivamente que esos combos terminaron de verdad
    sin volver a consultar la API. Usar solo con --trust-legacy-rows-once,
    y solo para reanudar ESTA corrida ya iniciada -- cualquier corrida
    NUEVA (proximos ciclos incrementales) debe usar already_queried_combos()
    sin este parche."""
    done: set[tuple[str, str, str, str]] = set()
    if not manifest_path.exists():
        return done
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("event") == "query_completed":
            continue
        done.add((r.get("comuna", ""), r.get("termino", ""), r.get("periodo", ""), r.get("nivel", "")))
    return done


def legacy_flag_is_safe(manifest_path: Path) -> tuple[bool, str]:
    """Guard mecanico para --trust-legacy-rows-once (2026-09-12, hallazgo
    la auditoría cruzada turn-20260913-000857-3d5bac): "once" no puede ser solo una
    convencion de nombre/documentacion, tiene que rechazar tecnicamente un
    segundo uso. Si el manifest YA tiene algun evento query_completed,
    la transicion legacy ya ocurrio -- cualquier fila sin ese evento a
    partir de ahi es responsabilidad del codigo nuevo (ej. un crash bajo
    codigo ya parchado), no del escenario legacy que este flag existe para
    resolver una sola vez. Aceptarla en ese caso reintroduciria el mismo
    problema que el fix de query_completed vino a cerrar."""
    ya_transicionado = already_queried_combos(manifest_path)
    if ya_transicionado:
        return False, (
            f"el manifest ya tiene {len(ya_transicionado)} combo(s) con query_completed -- "
            "la transicion legacy ya ocurrio. Usar el modo estricto (sin la bandera) para "
            "cualquier corrida posterior a esa transicion."
        )
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Descubrimiento Bright Data SERP — caso inmobiliario Santiago")
    parser.add_argument("--limit", type=int, default=0, help="Limitar a N queries del plan (0 = todas)")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta 1 sola query de prueba, no guarda resultados")
    parser.add_argument(
        "--combos-file",
        type=str,
        default="",
        help=(
            "Restringe el plan a los combos {comuna,termino,periodo,nivel} listados en este "
            "JSON (mismo formato que produce reconcile_discovery_log.py). Para reconsultar "
            "dirigidamente un subconjunto (ej. una muestra estratificada o la lista completa "
            "de fallos de red confirmados) en vez de las 2336 queries del plan completo."
        ),
    )
    parser.add_argument(
        "--trust-legacy-rows-once",
        action="store_true",
        help=(
            "SOLO para reanudar la corrida iniciada antes del fix de query_completed "
            "(2026-09-12, manifest con 0 eventos query_completed): trata cualquier fila "
            "existente como combo completo, igual que el comportamiento viejo. Riesgo "
            "residual explicito: un combo cortado a mitad puede quedar marcado completo "
            "sin serlo de verdad -- no usar para corridas nuevas ni ciclos incrementales."
        ),
    )
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    api_key = env.get("BRIGHTDATA_API_KEY", "")
    if not api_key:
        logger.error("BRIGHTDATA_API_KEY vacia en %s", ENV_PATH)
        return 1

    FUENTES_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = FUENTES_DIR / "discovery_manifest.jsonl"

    plan = build_query_plan()
    n_sector_queries = sum(len(s) for s in SECTORES.values()) * len(TERMINOS_SECTOR) * len(PERIODOS)
    total_plan_len = len(plan)

    if args.combos_file:
        combos_path = Path(args.combos_file)
        wanted = {
            (c["comuna"], c["termino"], c["periodo"], c["nivel"])
            for c in json.loads(combos_path.read_text(encoding="utf-8"))
        }
        before = len(plan)
        plan = [p for p in plan if (p["comuna"], p["termino"], p["periodo"], p["nivel"]) in wanted]
        logger.info("--combos-file %s: %d combos solicitados, %d encontrados en el plan de %d totales", combos_path, len(wanted), len(plan), before)

    if args.dry_run:
        plan = plan[:1]
    elif args.limit:
        plan = plan[: args.limit]
    else:
        if args.trust_legacy_rows_once:
            allowed, reason = legacy_flag_is_safe(manifest_path)
            if not allowed:
                logger.error("--trust-legacy-rows-once rechazado: %s", reason)
                return 2
            logger.warning(
                "--trust-legacy-rows-once activo: tratando cualquier fila existente como "
                "combo completo (comportamiento pre-fix). Riesgo residual aceptado y "
                "documentado en Auditoria/codex_fleet/OPEN_FINDINGS_20260912.md -- no usar "
                "esta bandera para corridas nuevas."
            )
            done_combos = legacy_any_row_combos(manifest_path)
            done_query_hashes: set[str] = set()
        else:
            done_combos = set()
            done_query_hashes = already_queried_query_hashes(manifest_path)
        if done_combos or done_query_hashes:
            before = len(plan)
            if args.trust_legacy_rows_once:
                plan = [p for p in plan if (p["comuna"], p["termino"], p["periodo"], p["nivel"]) not in done_combos]
            else:
                plan = [p for p in plan if p["query_hash"] not in done_query_hashes]
            logger.info("Reanudando: %d consultas ya en el manifest, %d pendientes de %d totales", before - len(plan), len(plan), before)

    logger.info(
        "Plan de descubrimiento: %d queries pendientes de %d totales (%d comuna-nivel [%d comunas x %d terminos x %d periodos] + %d sector-nivel)",
        len(plan), total_plan_len, len(COMUNAS) * len(TERMINOS) * len(PERIODOS), len(COMUNAS), len(TERMINOS), len(PERIODOS), n_sector_queries,
    )

    limiter = BrightDataRateLimiter()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    results_count = 0

    with manifest_path.open("a", encoding="utf-8") as manifest_file:
        for item in plan:
            query = item["query"]
            logger.info("Buscando [%s]: %s", item["periodo"], query)
            inner = brightdata_search(query, api_key, limiter, item["cd_min"], item["cd_max"])
            if not inner:
                continue
            organic = inner.get("organic", [])
            country_detected = inner.get("general", {}).get("country", "")
            logger.info("  -> %d resultados organicos (country detectado: %s)", len(organic), country_detected)

            for rank, r in enumerate(organic, start=1):
                link_raw = r.get("link", "")
                resolved_url, method = resolve_goto_link(link_raw, session)
                record = {
                    "comuna": item["comuna"],
                    "termino": item["termino"],
                    "periodo": item["periodo"],
                    "nivel": item["nivel"],
                    "query": query,
                    "rank": rank,
                    "title": r.get("title", ""),
                    "description": r.get("description", ""),
                    "resolved_url": resolved_url,
                    "resolution_method": method,
                    "country_detected": country_detected,
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "record_hash": sha256_text(query + "|" + item["periodo"] + "|" + r.get("title", "") + "|" + resolved_url),
                    "query_hash": item["query_hash"],
                    "plan_version": DISCOVERY_PLAN_VERSION,
                }
                if not args.dry_run:
                    manifest_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    manifest_file.flush()
                results_count += 1
                logger.info("     [%d] %s -> %s", rank, r.get("title", "")[:60], resolved_url[:70] or "(no resuelto)")

            if not args.dry_run:
                # Marcador de finalizacion (fix 2026-09-12): sin esto, un
                # combo con resultados parcialmente escritos (proceso
                # muerto a mitad del loop de arriba) se veria identico a
                # uno realmente completo en already_queried_combos().
                completed_record = {
                    "event": "query_completed",
                    "comuna": item["comuna"],
                    "termino": item["termino"],
                    "periodo": item["periodo"],
                    "nivel": item["nivel"],
                    "organic_count": len(organic),
                    "query_hash": item["query_hash"],
                    "plan_version": DISCOVERY_PLAN_VERSION,
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                }
                manifest_file.write(json.dumps(completed_record, ensure_ascii=False) + "\n")
                manifest_file.flush()

            if args.dry_run:
                break

    logger.info("Total de registros descubiertos: %d", results_count)
    if not args.dry_run:
        logger.info("Guardado en: %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
