#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lock atomico real por etapa del pipeline, para que el ciclo incremental
(disparado periodicamente cuando llega el aviso del Monitor de discovery)
no dispare dos veces la misma etapa en paralelo -- run_state.json por si
solo NO es un lock (dos procesos podrian leer "idle" al mismo tiempo).

Mecanismo: creacion exclusiva de archivo (open(path, "x")), atomica a
nivel de filesystem -- si el archivo ya existe, falla. Se libera con
try/finally para que un error a mitad de una etapa no deje el lock
huerfano indefinidamente sin que nadie se entere (igual se loguea si
alguna vez un lock queda mas viejo que LOCK_STALE_HOURS -- no se rompe
automatico, requiere revision manual antes de borrarlo).

Fix 2026-09-12 (auditoria adversarial de Codex, xhigh, tercera ronda de
QA -- 2 bugs reales encontrados en este mismo archivo):
1. El archivo .lock se creaba y LUEGO se llamaba _update_run_state("running")
   FUERA de cualquier try/finally -- si esa llamada fallaba (disco lleno,
   permisos, JSON corrupto), el lock quedaba huerfano sin que el finally
   se ejecutara nunca. Corregido: todo el ciclo de vida del lock, desde que
   se crea el archivo hasta que se libera, vive dentro de un unico
   try/finally.
2. _update_run_state() hacia read-modify-write de run_state.json sin
   ninguna exclusion mutua ni escritura atomica -- dos etapas distintas
   (con locks de ETAPA distintos, pero compitiendo por el mismo archivo
   run_state.json) podian pisarse la escritura entre si, y un lector a
   mitad de una escritura podia toparse con JSON truncado. Corregido con
   (a) un mutex chico y de corta duracion especifico para run_state.json
   (reintento con backoff, no falla inmediato como los locks de etapa --
   la seccion critica dura milisegundos, esperar un poco es razonable y
   no equivale a esperar una etapa de horas) y (b) escritura atomica
   (archivo temporal + os.replace, nunca write_text directo).
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("pipeline_lock")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKS_DIR = PROJECT_ROOT / "_FARO" / "memory-bank" / "locks"
RUN_STATE_PATH = PROJECT_ROOT / "_FARO" / "memory-bank" / "run_state.json"
RUN_STATE_MUTEX_PATH = PROJECT_ROOT / "_FARO" / "memory-bank" / "run_state.mutex"
LOCK_STALE_HOURS = 4
RUN_STATE_MUTEX_MAX_WAIT_S = 5.0


class LockBusyError(Exception):
    pass


class StageSkipped(Exception):
    """Levantar esto dentro de un bloque `with acquire_lock(...):` cuando la
    etapa decide no hacer trabajo real (ej. upstream_stage_is_running()
    bloqueo la corrida de produccion) -- run_state.json queda "skipped",
    NUNCA "done". Fix 2026-09-12: encontrado mientras se verificaba el
    estado antes de compactar la sesion -- el gate de coordinacion entre
    etapas (upstream_stage_is_running) hacia un `return` temprano normal
    desde _run(), y como acquire_lock() solo distinguia excepcion vs. salida
    normal del `with`, cualquier salida sin excepcion (incluido un gate
    bloqueado que no hizo nada) se marcaba "done" -- indistinguible de una
    corrida real completa. Uso: `raise StageSkipped(codigo_de_retorno, motivo)`."""

    def __init__(self, return_code: int, motivo: str = "") -> None:
        super().__init__(motivo)
        self.return_code = return_code
        self.motivo = motivo


def _mutex_owner_alive(payload: dict) -> bool:
    """Devuelve si el PID que creo el mutex sigue vivo.

    Un mutex existente no se puede romper solo por edad: la seccion critica
    puede estar temporalmente bloqueada por otro escritor legitimo. Solo se
    considera recuperable cuando el propietario registrado ya no existe y el
    archivo conserva el mismo token que se leyó.
    """
    pid = payload.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return True  # payload viejo/corrupto: bloquear, no adivinar
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_mutex_payload() -> tuple[dict | None, str | None]:
    try:
        raw = RUN_STATE_MUTEX_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None, None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, raw
    return payload if isinstance(payload, dict) else None, raw


@contextmanager
def _run_state_mutex():
    """Mutex de corta duracion (milisegundos) alrededor del read-modify-write
    de run_state.json -- no confundir con los locks de etapa (que pueden
    durar horas y fallan rapido en vez de esperar). Acá sí conviene
    reintentar con backoff porque la seccion critica es minuscula."""
    RUN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_STATE_MUTEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + RUN_STATE_MUTEX_MAX_WAIT_S
    fd = None
    owner_token = uuid.uuid4().hex
    owner_payload = {
        "pid": os.getpid(),
        "token": owner_token,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    while True:
        try:
            fd = os.open(str(RUN_STATE_MUTEX_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(owner_payload, ensure_ascii=False))
                    handle.flush()
                    os.fsync(handle.fileno())
                fd = None
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    RUN_STATE_MUTEX_PATH.unlink()
                except FileNotFoundError:
                    pass
                raise
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                payload, raw_before = _read_mutex_payload()
                if payload is None or _mutex_owner_alive(payload):
                    raise TimeoutError(
                        "run_state.mutex sigue ocupado por un propietario vivo o tiene payload no confiable"
                    )
                # El propietario murió. Solo retirar si el archivo no cambió
                # desde la lectura; así no se borra un mutex nuevo que otro
                # proceso haya adquirido entre ambas operaciones.
                try:
                    raw_after = RUN_STATE_MUTEX_PATH.read_text(encoding="utf-8")
                except FileNotFoundError:
                    continue
                if raw_after != raw_before:
                    continue
                logger.warning("run_state.mutex huerfano de PID %s -- se recupera", payload.get("pid"))
                try:
                    RUN_STATE_MUTEX_PATH.unlink()
                except FileNotFoundError:
                    pass
                continue
            time.sleep(0.05 + random.uniform(0, 0.05))
    try:
        yield
    finally:
        # Solo el dueño actual puede liberar este mutex. Si el archivo fue
        # reemplazado por otro dueño, no tocarlo.
        try:
            payload, _ = _read_mutex_payload()
            if payload and payload.get("token") == owner_token:
                RUN_STATE_MUTEX_PATH.unlink()
        except (FileNotFoundError, OSError):
            pass


def _update_run_state(etapa: str, estado: str, run_id: str, iniciado_at: str, detail: dict | None = None) -> None:
    """Contrato completo (run_id/iniciado_at/terminado_at/detail), con
    exclusion mutua y escritura atomica (ver docstring del modulo)."""
    with _run_state_mutex():
        state = {}
        if RUN_STATE_PATH.exists():
            try:
                state = json.loads(RUN_STATE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
        entry = {
            "estado": estado,
            "run_id": run_id,
            "iniciado_at": iniciado_at,
            "terminado_at": datetime.now(timezone.utc).isoformat() if estado in ("done", "failed", "skipped") else None,
            "pid": os.getpid(),
            "state_schema_version": 2,
        }
        if detail:
            entry["detail"] = detail
        state[etapa] = entry
        tmp_path = RUN_STATE_PATH.with_suffix(f".tmp{os.getpid()}")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp_path), str(RUN_STATE_PATH))


def read_jsonl_tolerant(path: Path, *, fail_on_invalid: bool = False) -> list[dict]:
    """Lee un JSONL saltando lineas que no parsean (ej. una ultima linea
    truncada por un crash a mitad de un write() sin fsync/reemplazo
    atomico) en vez de que json.loads() reviente toda la lectura. Fix
    2026-09-12 (Codex, hallazgo #9): los manifests/eventos del pipeline se
    escriben con flush() pero sin fsync() ni archivo-temporal+replace, y
    los lectores (already_classified_urls, already_processed_urls, el
    replay de eventos de dedupe, etc.) hacian json.loads() de cada linea
    sin tolerar una ultima linea truncada -- un crash exactamente a mitad
    de un write() podia dejar el archivo enteramente illegible para la
    proxima corrida, bloqueando la reanudacion."""
    if not path.exists():
        return []
    rows = []
    invalid_lines: list[int] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            invalid_lines.append(i + 1)
            is_last = i == len(lines) - 1
            logger.warning(
                "Linea %d de %s no parsea como JSON%s -- se descarta.",
                i + 1, path, " (es la ultima -- probable truncamiento por crash)" if is_last else " (linea intermedia, mas raro -- revisar el archivo a mano)",
            )
    if fail_on_invalid and invalid_lines:
        raise ValueError(f"JSONL corrupto en {path}: lineas invalidas {invalid_lines}")
    return rows


def read_run_state(etapa: str | None = None) -> dict:
    """Lectura tolerante (no falla si hay una escritura concurrente rara vez
    capturada a mitad de camino -- aunque con escritura atomica esto ya no
    deberia pasar, se mantiene el fallback por defensividad)."""
    if not RUN_STATE_PATH.exists():
        return {}
    try:
        state = json.loads(RUN_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return state.get(etapa, {}) if etapa else state


def upstream_stage_is_running(etapa: str) -> bool:
    """Chequeo blando de coordinacion productor/consumidor (fix 2026-09-12,
    hallazgo de Codex: los locks por etapa no impiden que una etapa lea
    mientras la etapa anterior todavia esta escribiendo -- ej. classify_luna
    corriendo mientras dedupe_fulltext todavia esta reescribiendo su vista
    materializada). No es un lock distribuido real, es una senal para que
    el llamador decida esperar/abortar antes de empezar a leer datos que
    otra etapa todavia esta produciendo."""
    if read_run_state(etapa).get("estado") == "running":
        return True
    # Si el proceso murio antes de actualizar run_state, el lock de etapa es
    # la unica señal durable de que puede haber una escritura incompleta.
    # Bloquear es conservador y exige la misma revisión manual que el contrato
    # de locks ya establece; nunca se debe leer un productor a medio escribir.
    return (LOCKS_DIR / f"{etapa}.lock").exists()


@contextmanager
def acquire_lock(etapa: str, detail: dict | None = None):
    """Uso: `with acquire_lock('classify'): ...` o `with acquire_lock('classify',
    detail={'es_produccion': False, 'output_path': '...'}): ...`. Lanza
    LockBusyError si otra corrida de la misma etapa ya tiene el lock
    tomado -- el llamador debe loguear y salir, no esperar ni reintentar
    (el proximo ciclo del Monitor lo vuelve a intentar).

    Para pruebas locales/unitarias de un script que usa este lock: llamar
    directamente a la funcion `_run()` interna del script (sin pasar por
    `main()`) en vez de invocar `main()` -- `_run()` no toca el lock ni
    run_state.json. Confundir esto fue justamente el bug que contamino
    run_state.json con una entrada `dedupe_fulltext: done` falsa."""
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCKS_DIR / f"{etapa}.lock"

    if lock_path.exists():
        age_hours = (time.time() - lock_path.stat().st_mtime) / 3600
        if age_hours > LOCK_STALE_HOURS:
            logger.warning(
                "Lock de '%s' existe hace %.1fh (> %dh) -- posible lock huerfano, "
                "pero NO se rompe automaticamente. Revisar a mano antes de borrar: %s",
                etapa, age_hours, LOCK_STALE_HOURS, lock_path,
            )
        raise LockBusyError(f"Etapa '{etapa}' ya tiene un lock activo ({lock_path}) -- no se reintenta, sale.")

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LockBusyError(f"Etapa '{etapa}' ya tiene un lock activo (carrera detectada al crear) -- sale.") from exc

    # Fix 2026-09-12 (Codex, hallazgo #6): TODO el ciclo de vida vive ahora
    # dentro de un unico try/finally -- antes, si _update_run_state("running")
    # fallaba aca fuera, el lock quedaba huerfano porque el finally de mas
    # abajo nunca se ejecutaba.
    run_id = uuid.uuid4().hex[:12]
    iniciado_at = datetime.now(timezone.utc).isoformat()
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "pid": os.getpid(),
                "run_id": run_id,
                "iniciado_at": iniciado_at,
            }, ensure_ascii=False))

        _update_run_state(etapa, "running", run_id, iniciado_at, detail)
        try:
            yield
            _update_run_state(etapa, "done", run_id, iniciado_at, detail)
        except StageSkipped as skip:
            # "saltado" no es un error del proceso (es una decision normal:
            # el gate de coordinacion entre etapas bloqueo la corrida) ni un
            # "done" (no se hizo trabajo real) -- estado propio, y SI se
            # re-lanza para que el llamador (main()) recupere return_code
            # explicitamente en vez de depender de un canal lateral.
            skip_detail = dict(detail or {})
            skip_detail["motivo_skip"] = skip.motivo
            _update_run_state(etapa, "skipped", run_id, iniciado_at, skip_detail)
            raise
        except Exception:
            _update_run_state(etapa, "failed", run_id, iniciado_at, detail)
            raise
    finally:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            if payload.get("run_id") == run_id:
                lock_path.unlink()
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
