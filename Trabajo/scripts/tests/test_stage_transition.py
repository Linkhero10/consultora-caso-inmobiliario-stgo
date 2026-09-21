from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(r"D:\Felipe\Consultora\caso_inmobiliario_stgo")
SCRIPT = ROOT / "Trabajo" / "scripts" / "stage_transition.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage_transition_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stage_transition = load_module()


ROADMAP = {
    "schema_version": 1,
    "project_id": "test_project",
    "stages": [
        {
            "id": "stage_1_corpus",
            "name": "Corpus",
            "goal": "Cerrar corpus",
            "owners": ["Felipe"],
            "next_stage": "stage_2_arcos",
            "exit_gates": [
                {"id": "snapshot_closed", "blocking": True, "description": "Snapshot cerrado"},
                {"id": "outputs_verified", "blocking": True, "description": "Outputs verificados"},
            ],
        },
        {
            "id": "stage_2_arcos",
            "name": "Arcos",
            "goal": "Ejecutar arcos",
            "owners": ["Equipo"],
            "next_stage": None,
            "exit_gates": [],
        },
    ],
}


class StageTransitionTests(unittest.TestCase):
    def test_show_resolves_active_goal_and_next_stage(self):
        state = {"schema_version": 1, "project_id": "test_project", "current_stage": "stage_1_corpus", "status": "active", "next_stage": "stage_2_arcos"}
        view = stage_transition.build_status_view(ROADMAP, state)
        self.assertEqual(view["current_stage"]["id"], "stage_1_corpus")
        self.assertEqual(view["current_stage"]["goal"], "Cerrar corpus")
        self.assertEqual(view["next_stage"]["id"], "stage_2_arcos")

    def test_close_requires_explicit_human_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "stage_state.json"
            roadmap_path = root / "roadmap.yaml"
            gate_path = root / "gates.json"
            state_path.write_text(json.dumps({"schema_version": 1, "project_id": "test_project", "current_stage": "stage_1_corpus", "status": "active", "next_stage": "stage_2_arcos"}), encoding="utf-8")
            roadmap_path.write_text("schema_version: 1\n", encoding="utf-8")
            gate_path.write_text(json.dumps({"gates": [{"id": "snapshot_closed", "status": "passed"}, {"id": "outputs_verified", "status": "passed"}]}), encoding="utf-8")
            with self.assertRaises(stage_transition.StageTransitionError):
                stage_transition.close_stage(
                    roadmap=ROADMAP,
                    roadmap_path=roadmap_path,
                    state_path=state_path,
                    closures_dir=root / "closures",
                    gate_report_path=gate_path,
                    decision="cerrar",
                    confirm_human=False,
                    actor="Felipe",
                )

    def test_close_rejects_failed_blocking_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "stage_state.json"
            roadmap_path = root / "roadmap.yaml"
            gate_path = root / "gates.json"
            state_path.write_text(json.dumps({"schema_version": 1, "project_id": "test_project", "current_stage": "stage_1_corpus", "status": "active", "next_stage": "stage_2_arcos"}), encoding="utf-8")
            roadmap_path.write_text("schema_version: 1\n", encoding="utf-8")
            gate_path.write_text(json.dumps({"gates": [{"id": "snapshot_closed", "status": "failed"}, {"id": "outputs_verified", "status": "passed"}]}), encoding="utf-8")
            with self.assertRaises(stage_transition.StageTransitionError):
                stage_transition.close_stage(
                    roadmap=ROADMAP,
                    roadmap_path=roadmap_path,
                    state_path=state_path,
                    closures_dir=root / "closures",
                    gate_report_path=gate_path,
                    decision="cerrar",
                    confirm_human=True,
                    actor="Felipe",
                )

    def test_valid_close_writes_immutable_act_and_advances_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "stage_state.json"
            roadmap_path = root / "roadmap.yaml"
            gate_path = root / "gates.json"
            state_path.write_text(json.dumps({"schema_version": 1, "project_id": "test_project", "current_stage": "stage_1_corpus", "status": "active", "next_stage": "stage_2_arcos"}), encoding="utf-8")
            roadmap_path.write_text("schema_version: 1\n", encoding="utf-8")
            gate_path.write_text(json.dumps({"gates": [{"id": "snapshot_closed", "status": "passed", "evidence": ["snapshot.json"]}, {"id": "outputs_verified", "status": "passed", "evidence": ["outputs.json"]}]}), encoding="utf-8")
            act_path = stage_transition.close_stage(
                roadmap=ROADMAP,
                roadmap_path=roadmap_path,
                state_path=state_path,
                closures_dir=root / "closures",
                gate_report_path=gate_path,
                decision="cerrar",
                confirm_human=True,
                actor="Felipe",
                now="2026-09-13T12:00:00+00:00",
            )
            self.assertTrue(act_path.exists())
            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["current_stage"], "stage_2_arcos")
            self.assertEqual(updated["status"], "ready")
            self.assertEqual(json.loads(act_path.read_text(encoding="utf-8"))["stage_id"], "stage_1_corpus")
            state_path.write_text(json.dumps({"schema_version": 1, "project_id": "test_project", "current_stage": "stage_1_corpus", "status": "active", "next_stage": "stage_2_arcos"}), encoding="utf-8")
            with self.assertRaises(stage_transition.StageTransitionError):
                stage_transition.close_stage(
                    roadmap=ROADMAP,
                    roadmap_path=roadmap_path,
                    state_path=state_path,
                    closures_dir=root / "closures",
                    gate_report_path=gate_path,
                    decision="cerrar otra vez",
                    confirm_human=True,
                    actor="Felipe",
                    now="2026-09-13T12:01:00+00:00",
                )


if __name__ == "__main__":
    unittest.main()
