"""El orden de reconstruccion tiene UNA definicion (`src/rebuild.py`) y la documentacion no puede contradecirla."""

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import rebuild  # noqa: E402

NAMES = [step.name for step in rebuild.STEPS]


def test_every_step_points_to_an_existing_script_and_names_are_unique():
    assert len(NAMES) == len(set(NAMES))
    for step in rebuild.STEPS:
        assert (PROJECT_ROOT / "src" / step.script).is_file(), step.script


def test_the_manifest_is_the_last_step_that_touches_the_warehouse_and_docs_only_read_it():
    assert NAMES[-2:] == ["manifest", "docs_stats"]
    assert NAMES.index("dashboard") == NAMES.index("manifest") - 1


@pytest.mark.parametrize("before, after", [
    ("enrichment_tables", "projects"),
    ("projects", "identity_resolution"),
    ("identity_resolution", "case_mention_duplicates"),
    ("case_mention_duplicates", "conflicts"),
    ("conflicts", "actor_registry"),
    ("case_mention_duplicates", "geography"),
    ("conflicts", "geography"),
    ("geography", "dashboard"),
])
def test_dependency_order(before, after):
    assert NAMES.index(before) < NAMES.index(after)


def test_selection_by_range_and_unknown_step():
    assert [s.name for s in rebuild.select("conflicts", "actor_registry")] == ["conflicts", "actor_registry"]
    assert rebuild.select(None, None) == list(rebuild.STEPS)
    assert rebuild.select("manifest", None)[0].name == "manifest"
    with pytest.raises(SystemExit):
        rebuild.select("no_existe", None)
    with pytest.raises(SystemExit, match="anterior"):
        rebuild.select("docs_stats", "projects")


def test_baseline_regeneration_is_explicit_and_placed_right_after_projects():
    default = [step.name for step, _ in rebuild.plan(None, None, None)]
    assert "project_baseline" not in default
    with_baseline = [step.name for step, _ in rebuild.plan(None, None, "motivo")]
    assert with_baseline[with_baseline.index("projects") + 1] == "project_baseline"
    with pytest.raises(SystemExit):
        rebuild.plan("conflicts", None, "motivo")


def test_dry_run_and_list_do_not_execute_anything(capsys):
    assert rebuild.main(["--list"]) == 0
    capsys.readouterr()
    assert rebuild.main(["--dry-run", "--from", "conflicts", "--to", "conflicts"]) == 0
    out = capsys.readouterr().out
    assert "build_conflicts.py" in out and "build_projects.py" not in out


def test_readme_lists_the_same_scripts_in_the_same_order():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    listed = re.findall(r"python src/(\w+\.py)", readme)
    ordered = [step.script for step in rebuild.STEPS]
    in_readme = [script for script in listed if script in ordered]
    # cada script de la reconstruccion aparece en el README, en el orden de rebuild.py
    deduped = [s for i, s in enumerate(in_readme) if s not in in_readme[:i]]
    assert deduped == ordered
