"""Integracion del gate hash-pinned en el entrypoint de produccion v5.2.3."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import classify as target  # noqa: E402


def test_entrypoint_v523_wires_hash_pinned_gate_before_run(monkeypatch):
    """El entrypoint real debe reemplazar el gate boolean-only heredado.

    La prueba intercepta el ejecutor justo despues de que ``main`` configura
    el contrato. No llama a la API ni escribe produccion.
    """
    class DummyLock:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    observed = {}
    monkeypatch.setattr(target.previous, "acquire_lock", lambda *args, **kwargs: DummyLock())

    def fake_run(args):
        observed["same_gate"] = (
            target.previous.classification_release_allowed
            is target.v51.classification_release_allowed
        )
        return 0

    monkeypatch.setattr(target.previous, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", [str(target.__file__), "--dry-run"])

    assert target.main() == 0
    assert observed["same_gate"] is True
    stale_artifact = {
        "status": "aprobado_revision_humana",
        "review_policy": {"human_review_completed": True, "production_allowed": True},
    }
    assert target.previous.classification_release_allowed(stale_artifact) is False


def test_lock_detail_es_produccion_matches_real_gate_logic_for_output_file_alone(tmp_path, monkeypatch):
    """Autoauditoria 2026-09-16: detail['es_produccion'] (metadata del lock
    en run_state.json) usaba una formula vieja que decia 'es prueba' para
    cualquier --output-file, aunque _run() ya tratara esa misma corrida
    como produccion real (gate exigido). Debe coincidir."""
    class DummyLock:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fake_acquire_lock(name, detail=None):
        captured["detail"] = detail
        return DummyLock()

    monkeypatch.setattr(target.previous, "acquire_lock", fake_acquire_lock)
    monkeypatch.setattr(target.previous, "_run", lambda args: 0)

    output_file = tmp_path / "salida.jsonl"
    monkeypatch.setattr(sys, "argv", [str(target.__file__), "--output-file", str(output_file), "--workers", "1"])

    assert target.main() == 0
    assert captured["detail"]["es_produccion"] is True, (
        "--output-file solo debe quedar marcado como produccion real en el lock, "
        "igual que en la logica real de _run() (is_test=False para este caso)"
    )


def test_lock_detail_es_produccion_false_for_small_scoped_test(tmp_path, monkeypatch):
    class DummyLock:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fake_acquire_lock(name, detail=None):
        captured["detail"] = detail
        return DummyLock()

    monkeypatch.setattr(target.previous, "acquire_lock", fake_acquire_lock)
    monkeypatch.setattr(target.previous, "_run", lambda args: 0)

    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.cl/uno\n", encoding="utf-8")
    output_file = tmp_path / "salida.jsonl"
    monkeypatch.setattr(sys, "argv", [str(target.__file__), "--urls-file", str(urls_file), "--output-file", str(output_file)])

    assert target.main() == 0
    assert captured["detail"]["es_produccion"] is False
