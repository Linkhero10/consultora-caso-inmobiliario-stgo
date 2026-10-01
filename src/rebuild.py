#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruye el producto (`data/warehouse.sqlite`, `audit/`, `docs/index.html`) en el orden correcto.

El orden importa y antes vivia repartido en tres documentos que se desactualizaban: cada etapa lee lo que escribio la
anterior, y el manifiesto debe ser SIEMPRE lo ultimo que toca el warehouse. Esta es la unica definicion del orden;
`README.md` y `docs/architecture.md` lo citan y una prueba (`tests/test_rebuild.py`) verifica que coinciden.

Las etapas de arriba (clasificacion, extraccion por LLM, warehouse base) dependen del corpus de terceros y de la API
y NO forman parte de esta reconstruccion. Si no se dispone de sus salidas, se recuperan del warehouse publicado:

    python src/extract_stage_warehouse.py --stage enrichment
    python src/rebuild.py                       # todas las etapas derivadas
    python src/rebuild.py --from conflicts      # desde una etapa
    python src/rebuild.py --list                # ver el orden

`generate_project_case_baseline.py` NO se ejecuta por defecto: el baseline versionado ata la resolucion de identidad al
conjunto exacto de proyectos. Solo se regenera, de forma explicita, cuando cambia ese conjunto
(`--regenerate-baseline "motivo"`).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent


@dataclass(frozen=True)
class Step:
    name: str
    script: str
    purpose: str


STEPS: tuple[Step, ...] = (
    Step("enrichment_tables", "build_enrichment_tables.py", "extraccion por LLM y revision de unidad de caso -> tablas enrichment_*"),
    Step("projects", "build_projects.py", "identidad de proyecto y puente documento -> proyecto -> actor/evento"),
    Step("identity_resolution", "resolve_project_review.py", "fusiona los pares de proyecto revisados y fija case_id"),
    Step("case_mention_duplicates", "detect_case_mention_duplicates.py", "grupos de case_mention duplicadas (requerido por geografia y conflicto)"),
    Step("conflicts", "build_conflicts.py", "capa CONFLICT: unidad sociologica de disputa y su respaldo de evidencia"),
    Step("scope_gate", "scope_gate.py", "filtro de alcance por conflicto (decisiones versionadas; no llama a la API) y vista conservadora"),
    Step("actor_registry", "build_actor_registry.py", "identidad de actor institucional"),
    Step("actor_network", "build_actor_network.py", "red actor <-> conflicto"),
    Step("actor_registry_impact", "apply_actor_registry_to_network.py", "efecto del registro de actores sobre la red"),
    Step("geography", "build_geography.py", "comuna resuelta y geografia de cada mencion de proyecto"),
    Step("geography_census_blocks", "build_geography_manzana.py", "contexto censal por manzana"),
    Step("dashboard", "build_dashboard.py", "tablero publico (docs/index.html)"),
    Step("manifest", "generate_run_manifest.py", "manifiesto del warehouse; SIEMPRE el ultimo paso que lo modifica o describe"),
    Step("docs_stats", "render_docs_stats.py", "cifras de README y START_HERE, calculadas desde el warehouse (solo lo lee)"),
)
BASELINE_STEP = Step("project_baseline", "generate_project_case_baseline.py", "baseline de case_id (solo si cambia el conjunto de proyectos)")


def select(from_step: str | None, to_step: str | None) -> list[Step]:
    names = [step.name for step in STEPS]
    for label, value in (("--from", from_step), ("--to", to_step)):
        if value is not None and value not in names:
            raise SystemExit(f"{label}: etapa desconocida {value!r}. Etapas: {', '.join(names)}")
    start = names.index(from_step) if from_step else 0
    end = names.index(to_step) if to_step else len(names) - 1
    if start > end:
        raise SystemExit("--from debe ser anterior o igual a --to")
    return list(STEPS[start:end + 1])


def plan(from_step: str | None, to_step: str | None, regenerate_baseline: str | None) -> list[tuple[Step, list[str]]]:
    steps = select(from_step, to_step)
    result: list[tuple[Step, list[str]]] = []
    for step in steps:
        result.append((step, [sys.executable, str(SRC_DIR / step.script)]))
        if step.name == "projects" and regenerate_baseline:
            result.append((BASELINE_STEP, [sys.executable, str(SRC_DIR / BASELINE_STEP.script), "--description", regenerate_baseline]))
    if regenerate_baseline and not any(step.name == "projects" for step in steps):
        raise SystemExit("--regenerate-baseline solo tiene sentido cuando la reconstruccion incluye la etapa 'projects'")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_step", help="etapa desde la que reconstruir (por defecto, la primera)")
    parser.add_argument("--to", dest="to_step", help="ultima etapa (por defecto, el manifiesto)")
    parser.add_argument("--list", action="store_true", help="muestra el orden y termina")
    parser.add_argument("--dry-run", action="store_true", help="muestra los comandos sin ejecutarlos")
    parser.add_argument("--regenerate-baseline", metavar="MOTIVO", help="regenera el baseline de case_id tras 'projects'")
    args = parser.parse_args(argv)

    if args.list:
        for index, step in enumerate(STEPS, 1):
            print(f"{index:>2}. {step.name:<26} {step.script:<38} {step.purpose}")
        return 0

    commands = plan(args.from_step, args.to_step, args.regenerate_baseline)
    for step, command in commands:
        print(f"[rebuild] {step.name}: {' '.join(Path(c).name if i < 2 else c for i, c in enumerate(command))}")
    if args.dry_run:
        return 0
    for step, command in commands:
        started = time.monotonic()
        print(f"\n[rebuild] === {step.name} ===", flush=True)
        result = subprocess.run(command, cwd=PROJECT_ROOT)
        if result.returncode != 0:
            print(f"[rebuild] FALLO en {step.name} (codigo {result.returncode}); no se ejecutan las etapas siguientes.", file=sys.stderr)
            return result.returncode
        print(f"[rebuild] {step.name} ok ({time.monotonic() - started:.1f}s)", flush=True)
    print("\n[rebuild] completo. Corre `python -m pytest -q` para verificar el resultado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
