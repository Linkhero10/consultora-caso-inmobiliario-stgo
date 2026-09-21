"""Hash-pinning del gate de liberacion (2026-09-16, hallazgo de auditoria
cruzada Codex/Luna): classification_release_allowed() antes solo verificaba
3 booleanos sin confirmar que el artefacto aprobado corresponda al
prompt/schema/script/muestra ACTUALES -- un artefacto viejo podia autorizar
silenciosamente un contrato nuevo sin revisar. No llama a la API."""

import hashlib
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import classify_v5_1 as v51  # noqa: E402

PROJECT_ROOT = Path(__file__).parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _valid_fingerprint(entry_script: Path, sample_path: Path) -> dict:
    return {
        "prompt_path": _relpath(v51.PROMPT_PATH),
        "prompt_sha256": _sha(v51.PROMPT_PATH),
        "schema_path": _relpath(v51.SCHEMA_PATH),
        "schema_sha256": _sha(v51.SCHEMA_PATH),
        "entry_script_path": _relpath(entry_script),
        "entry_script_sha256": _sha(entry_script),
        "base_gate_path": _relpath(Path(v51.__file__)),
        "base_gate_sha256": _sha(Path(v51.__file__)),
        "human_review_sample_path": _relpath(sample_path),
        "human_review_sample_sha256": _sha(sample_path),
    }


def _base_artifact(fingerprint: dict) -> dict:
    return {
        "status": "aprobado_revision_humana",
        "review_policy": {"human_review_completed": True, "production_allowed": True},
        "contract_fingerprint": fingerprint,
    }


def test_artifact_without_contract_fingerprint_is_blocked():
    artifact = {
        "status": "aprobado_revision_humana",
        "review_policy": {"human_review_completed": True, "production_allowed": True},
    }
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert any("contract_fingerprint" in r for r in reasons)


def test_valid_fingerprint_matching_current_files_is_allowed(tmp_path, monkeypatch):
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    artifact = _base_artifact(fingerprint)
    assert v51.classification_release_allowed(artifact) is True
    assert v51.classification_release_reasons(artifact) == []


def test_stale_prompt_hash_blocks_release(tmp_path, monkeypatch):
    """El caso central del hallazgo: un artefacto aprobado para un prompt
    viejo no debe autorizar un prompt nuevo aunque los 3 booleanos digan
    que si."""
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    fingerprint["prompt_sha256"] = "0" * 64  # hash de un prompt que ya no existe
    artifact = _base_artifact(fingerprint)
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert any("prompt" in r and "hash vigente" in r for r in reasons)


def test_stale_schema_path_blocks_release(tmp_path, monkeypatch):
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    fingerprint["schema_path"] = "Trabajo/config/classification_schema_v_que_no_existe.json"
    artifact = _base_artifact(fingerprint)
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert any("schema" in r and "ruta vigente" in r for r in reasons)


def test_modified_human_review_sample_blocks_release(tmp_path, monkeypatch):
    """Si el archivo de revision humana cambia despues de aprobar el
    artefacto (editado, sobrescrito), el gate debe bloquear -- el hash ya
    no coincide con lo que Felipe realmente revisó."""
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    artifact = _base_artifact(fingerprint)
    assert v51.classification_release_allowed(artifact) is True
    # el archivo cambia despues de aprobado
    sample_path.write_text('{"ok": false, "editado": true}', encoding="utf-8")
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert any("revision humana" in r and "no coincide" in r for r in reasons)


def test_three_booleans_alone_are_not_sufficient_anymore():
    """Regresion directa del comportamiento pre-fix: los 3 booleanos solos
    ya no bastan sin contract_fingerprint."""
    artifact = {
        "status": "aprobado_revision_humana",
        "review_policy": {"human_review_completed": True, "production_allowed": True},
    }
    assert v51.classification_release_allowed(artifact) is False


def test_incomplete_booleans_still_block_before_checking_fingerprint(tmp_path, monkeypatch):
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    artifact = _base_artifact(fingerprint)
    artifact["review_policy"]["production_allowed"] = False
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert reasons == ["review_policy.production_allowed != true"]


def test_extra_gate_files_are_verified(tmp_path, monkeypatch):
    """contract_fingerprint.extra_gate_files permite pinnear archivos
    adicionales del camino de ejecucion (ej. los wrappers classify_v5_2_1.py
    / classify_v5_2_2.py donde vivio el bypass real de hash-pinning)."""
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    extra_file = PROJECT_ROOT / "Trabajo" / "scripts" / "classify_v5_2_1.py"
    fingerprint["extra_gate_files"] = [
        {"label": "gate v5.2.1 (_run real)", "path": _relpath(extra_file), "sha256": _sha(extra_file)},
    ]
    artifact = _base_artifact(fingerprint)
    assert v51.classification_release_allowed(artifact) is True

    fingerprint["extra_gate_files"][0]["sha256"] = "0" * 64
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert any("gate v5.2.1" in r and "hash vigente" in r for r in reasons)


def test_missing_extra_gate_file_hash_blocks_release(tmp_path, monkeypatch):
    entry_script = Path(v51.__file__)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(entry_script)])
    fingerprint = _valid_fingerprint(entry_script, sample_path)
    fingerprint["extra_gate_files"] = [{"label": "incompleto", "path": "Trabajo/scripts/classify_v5_2_1.py"}]
    artifact = _base_artifact(fingerprint)
    assert v51.classification_release_allowed(artifact) is False
    reasons = v51.classification_release_reasons(artifact)
    assert any("incompleto" in r for r in reasons)
