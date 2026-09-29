import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = PROJECT_ROOT / "audit" / "build_historical_project_pair_adjudications_2026_09_28.py"
BUILDER_SPEC = importlib.util.spec_from_file_location("historical_pair_builder", BUILDER_PATH)
assert BUILDER_SPEC and BUILDER_SPEC.loader
builder = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(builder)


def test_resolve_source_paths_uses_repo_defaults_and_allows_separate_evidence_root():
    repo = Path("checkout")
    warehouse = Path("candidate.sqlite")
    fulltext = Path("fulltext")

    default_paths = builder.resolve_source_paths(repo)
    assert default_paths == {
        "warehouse": repo.resolve() / "data" / "warehouse.sqlite",
        "fulltext_root": repo.resolve() / "Fuentes" / "fulltext",
    }

    explicit_paths = builder.resolve_source_paths(repo, warehouse=warehouse, fulltext_root=fulltext)
    assert explicit_paths == {
        "warehouse": warehouse.resolve(),
        "fulltext_root": fulltext.resolve(),
    }
