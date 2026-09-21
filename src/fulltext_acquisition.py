"""Captura controlada de páginas públicas del registro de fuentes externas.

No es un crawler: requiere --source-ids, no usa credenciales, conserva bytes
raw y registra estados separados para HTTP, red y contenido. Las APIs con ticket
o licencia pendiente no deben pasarse a este script sin una decisión explícita.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml


DEFAULT_USER_AGENT = "FARO-ExternalSourcePilot/1.0 (research; contact local project owner)"
TRANSIENT_HTTP = {429, 500, 502, 503, 504}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_source_dir(raw_root: Path, source_id: str) -> Path:
    if not source_id or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in source_id):
        raise ValueError(f"source_id inseguro: {source_id!r}")
    path = raw_root / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_url(
    url: str,
    raw_root: Path,
    source_id: str,
    *,
    timeout: float = 30,
    user_agent: str = DEFAULT_USER_AGENT,
    max_retries: int = 2,
    retry_wait_s: float = 16.0,
) -> dict:
    """Fetch one URL, saving only successful response bytes and metadata."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"URL no HTTP(S): {url!r}")

    requested_at = _utc_now().isoformat()
    last_error = None
    for attempt in range(max_retries + 1):
        request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/json,*/*;q=0.5"})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type")
                status_code = int(response.status)
            digest = hashlib.sha256(payload).hexdigest()
            stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
            raw_path = _safe_source_dir(raw_root, source_id) / f"{stamp}_{digest[:16]}.raw"
            raw_path.write_bytes(payload)
            return {
                "status": "ok",
                "source_id": source_id,
                "requested_url": url,
                "final_url": final_url,
                "requested_at": requested_at,
                "retrieved_at": _utc_now().isoformat(),
                "http_status": status_code,
                "content_type": content_type,
                "bytes": len(payload),
                "sha256": digest,
                "raw_path": str(raw_path),
                "attempt": attempt + 1,
            }
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            if exc.code not in TRANSIENT_HTTP or attempt >= max_retries:
                return {
                    "status": "http_error",
                    "source_id": source_id,
                    "requested_url": url,
                    "requested_at": requested_at,
                    "retrieved_at": _utc_now().isoformat(),
                    "http_status": exc.code,
                    "error": last_error,
                    "sha256": None,
                    "raw_path": None,
                    "attempt": attempt + 1,
                }
        except (URLError, TimeoutError, OSError) as exc:
            last_error = repr(exc)
            if attempt >= max_retries:
                return {
                    "status": "network_error",
                    "source_id": source_id,
                    "requested_url": url,
                    "requested_at": requested_at,
                    "retrieved_at": _utc_now().isoformat(),
                    "http_status": None,
                    "error": last_error,
                    "sha256": None,
                    "raw_path": None,
                    "attempt": attempt + 1,
                }
        time.sleep(retry_wait_s)

    raise RuntimeError(f"captura sin estado: {url} ({last_error})")


def write_manifest_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def load_targets(registry_path: Path, source_ids: set[str]) -> list[dict]:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    sources = registry.get("sources", [])
    selected = [row for row in sources if row.get("source_id") in source_ids]
    missing = source_ids - {row.get("source_id") for row in selected}
    if missing:
        raise ValueError(f"source_id inexistente: {sorted(missing)}")
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("Fuentes/fuentes_externas/source_registry.yaml"))
    parser.add_argument("--raw-root", type=Path, default=Path("Fuentes/fuentes_externas/raw"))
    parser.add_argument("--manifest", type=Path, default=Path("Auditoria/fuentes_externas/external_manifest_v1.jsonl"))
    parser.add_argument("--source-ids", required=True, help="IDs separados por coma; no se permite corrida implícita de todas las fuentes")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--min-delay", type=float, default=1.5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_ids = {item.strip() for item in args.source_ids.split(",") if item.strip()}
    targets = load_targets(args.registry, source_ids)
    previous_host = None
    for target in targets:
        url = target["primary_url"]
        host = urlparse(url).netloc
        if previous_host == host:
            time.sleep(max(0.0, args.min_delay))
        if args.dry_run:
            print(json.dumps({"status": "planned", "source_id": target["source_id"], "url": url}, ensure_ascii=False))
            previous_host = host
            continue
        record = fetch_url(url, args.raw_root, target["source_id"], timeout=args.timeout)
        record.update({"priority": target.get("priority"), "source_type": target.get("source_type")})
        write_manifest_record(args.manifest, record)
        print(json.dumps(record, ensure_ascii=False))
        previous_host = host
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
