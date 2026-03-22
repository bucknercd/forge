"""Integration: task-apply-plan and vertical-slice use the shared repair loop."""

from __future__ import annotations

import json

from forge.cli import main
from forge.paths import Paths
from forge.task_service import get_task
from forge.vertical_slice import run_vertical_slice


def _init_policy_milestone(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out
    (tmp_path / "docs" / "milestones.md").write_text(
        """
# Milestones

## Milestone 1: Policy Defaults
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | POLICY_OK
- **Forge Validation**:
  - file_contains requirements POLICY_OK
""",
        encoding="utf-8",
    )


def _save_plan_id(monkeypatch, capsys) -> str:
    monkeypatch.setattr(
        "sys.argv",
        ["forge", "task-preview", "1", "--task", "1", "--save-plan", "--json"],
    )
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    return preview["plan_id"]


def _write_llm_repair_policy(tmp_path):
    (tmp_path / "forge-policy.json").write_text(
        json.dumps(
            {
                "planner": {"mode": "llm", "llm_client": "stub"},
                "task_execution": {
                    "max_repair_attempts": 3,
                    "artifact_test_generation": False,
                },
            }
        ),
        encoding="utf-8",
    )


def test_milestone_apply_plan_repair_succeeds_on_second_attempt(
    tmp_path, monkeypatch, capsys
):
    _init_policy_milestone(tmp_path, monkeypatch, capsys)
    _write_llm_repair_policy(tmp_path)
    Paths.refresh(tmp_path)
    plan_id = _save_plan_id(monkeypatch, capsys)

    calls = {"n": 0}

    def fail_then_pass(*_a, **_k):
        calls["n"] += 1
        ok = calls["n"] >= 2
        return [
            {
                "name": "milestone_validation",
                "ok": ok,
                "message": "ok" if ok else "fail",
                "details": {},
            }
        ]

    monkeypatch.setattr(
        "forge.executor.run_validation_and_test_commands",
        fail_then_pass,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["forge", "task-apply-plan", plan_id, "--gate-validate", "--json"],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert calls["n"] == 2
    assert payload.get("repair_attempts_used") == 2
    t1 = get_task(1, 1)
    assert t1 is not None
    assert t1.status == "completed"


def test_milestone_apply_plan_repair_exhausted_task_stays_incomplete(
    tmp_path, monkeypatch, capsys
):
    _init_policy_milestone(tmp_path, monkeypatch, capsys)
    _write_llm_repair_policy(tmp_path)
    Paths.refresh(tmp_path)
    plan_id = _save_plan_id(monkeypatch, capsys)

    def always_fail(*_a, **_k):
        return [
            {
                "name": "milestone_validation",
                "ok": False,
                "message": "mock",
                "details": {},
            }
        ]

    monkeypatch.setattr(
        "forge.executor.run_validation_and_test_commands",
        always_fail,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["forge", "task-apply-plan", plan_id, "--gate-validate", "--json"],
    )
    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload.get("repair_attempts_used") == 3
    t1 = get_task(1, 1)
    assert t1 is not None
    assert t1.status != "completed"


def test_vertical_slice_demo_repair_succeeds_second_gate_attempt(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    _write_llm_repair_policy(tmp_path)

    calls = {"n": 0}

    def fail_then_pass(*_a, **_k):
        calls["n"] += 1
        ok = calls["n"] >= 2
        return [
            {
                "name": "milestone_validation",
                "ok": ok,
                "message": "ok" if ok else "fail",
                "details": {},
            }
        ]

    monkeypatch.setattr(
        "forge.executor.run_validation_and_test_commands",
        fail_then_pass,
    )

    out = run_vertical_slice(
        demo=True,
        idea=None,
        fixed_vision=None,
        milestone_id=1,
        planner_mode=None,
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=True,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
    )
    assert out["ok"] is True
    assert calls["n"] == 2
    apply_stage = next(s for s in out["stages"] if s.get("stage") == "apply_plan")
    assert apply_stage.get("repair_attempts_used") == 2
    assert apply_stage.get("orchestration") == "task_repair_loop"
    nt = get_task(1, 1)
    assert nt is not None
    assert nt.status == "completed"


def test_vertical_slice_demo_repair_exhausted(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    _write_llm_repair_policy(tmp_path)

    monkeypatch.setattr(
        "forge.executor.run_validation_and_test_commands",
        lambda *_a, **_k: [
            {
                "name": "milestone_validation",
                "ok": False,
                "message": "mock",
                "details": {},
            }
        ],
    )

    out = run_vertical_slice(
        demo=True,
        idea=None,
        fixed_vision=None,
        milestone_id=1,
        planner_mode=None,
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=True,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
    )
    assert out["ok"] is False
    apply_stage = next(s for s in out["stages"] if s.get("stage") == "apply_plan")
    assert apply_stage.get("repair_attempts_used") == 3
    nt = get_task(1, 1)
    assert nt is not None
    assert nt.status != "completed"
