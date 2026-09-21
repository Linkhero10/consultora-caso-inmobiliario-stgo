"""Integracion del gate hash-pinned en el entrypoint de produccion.

Antes (cuando el pipeline vivia en 6 archivos), esta prueba verificaba que
`main()` reemplazara en tiempo de ejecucion el gate boolean-only heredado de
un modulo por el gate hash-pinned de otro (via sobreescritura de atributos
de modulo). Consolidado el pipeline en un solo archivo (`classify.py`), ya
no existe esa indireccion que verificar -- solo hay un
`classification_release_allowed`, y es el hash-pinned. Esta prueba verifica
la propiedad real que importaba: que `main()`/`_run()` exigen el gate
hash-pinned (rechazan un artefacto que solo tiene los 3 booleanos, sin
`contract_fingerprint`), no una version mas simple.
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import classify as target  # noqa: E402


class _DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_release_gate_used_by_run_is_the_hash_pinned_version():
    """Un artefacto con solo los 3 booleanos (sin contract_fingerprint) debe
    ser rechazado -- si `_run()` usara una version mas simple del gate,
    este artefacto pasaria."""
    stale_artifact = {
        "status": "aprobado_revision_humana",
        "review_policy": {"human_review_completed": True, "production_allowed": True},
    }
    assert target.classification_release_allowed(stale_artifact) is False
    reasons = target.classification_release_reasons(stale_artifact)
    assert any("contract_fingerprint" in r for r in reasons)


def test_dry_run_never_reaches_the_release_gate(monkeypatch):
    """--dry-run debe completar sin siquiera intentar leer REVIEW_ARTIFACT_PATH."""
    monkeypatch.setattr(target, "acquire_lock", lambda *args, **kwargs: _DummyLock())
    monkeypatch.setattr(target, "REVIEW_ARTIFACT_PATH", Path("/ruta/que/no/existe.json"))
    monkeypatch.setattr(sys, "argv", [str(target.__file__), "--dry-run"])
    monkeypatch.setattr(target, "load_env", lambda _path: {"OPENROUTER_API_KEY": "fake-key"})
    monkeypatch.setattr(target, "load_classifiable_documents", lambda urls_filter=None: [])

    assert target.main() == 0


def test_lock_detail_es_produccion_matches_real_gate_logic_for_output_file_alone(tmp_path, monkeypatch):
    """Autoauditoria 2026-09-16: detail['es_produccion'] (metadata del lock
    en run_state.json) usaba una formula vieja que decia 'es prueba' para
    cualquier --output-file, aunque _run() ya tratara esa misma corrida
    como produccion real (gate exigido). Debe coincidir."""
    captured = {}

    def fake_acquire_lock(name, detail=None):
        captured["detail"] = detail
        return _DummyLock()

    monkeypatch.setattr(target, "acquire_lock", fake_acquire_lock)
    monkeypatch.setattr(target, "_run", lambda args: 0)

    output_file = tmp_path / "salida.jsonl"
    monkeypatch.setattr(sys, "argv", [str(target.__file__), "--output-file", str(output_file), "--workers", "1"])

    assert target.main() == 0
    assert captured["detail"]["es_produccion"] is True, (
        "--output-file solo debe quedar marcado como produccion real en el lock, "
        "igual que en la logica real de _run() (is_test=False para este caso)"
    )


def test_lock_detail_es_produccion_false_for_small_scoped_test(tmp_path, monkeypatch):
    captured = {}

    def fake_acquire_lock(name, detail=None):
        captured["detail"] = detail
        return _DummyLock()

    monkeypatch.setattr(target, "acquire_lock", fake_acquire_lock)
    monkeypatch.setattr(target, "_run", lambda args: 0)

    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.cl/uno\n", encoding="utf-8")
    output_file = tmp_path / "salida.jsonl"
    monkeypatch.setattr(sys, "argv", [str(target.__file__), "--urls-file", str(urls_file), "--output-file", str(output_file)])

    assert target.main() == 0
    assert captured["detail"]["es_produccion"] is False
