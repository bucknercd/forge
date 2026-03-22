"""Unit and integration tests for artifact test generation and task repair loops."""

from __future__ import annotations

import json
import pytest

from forge.cli import ForgeCLI
from forge.executor import Executor
from forge.paths import Paths
from forge.policy_config import load_task_execution_policy
from forge.task_feedback import (
    build_repair_context,
    persist_task_feedback,
    repair_context_to_prompt_appendix,
)
from forge.task_service import Task, expand_milestone_to_tasks, get_task

from tests.forge_test_project import compat_forge_block, configure_project


def test_persist_task_feedback_writes_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    path = persist_task_feedback(
        9,
        2,
        3,
        {"phase": "gates", "plan_id": "x"},
    )
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["milestone_id"] == 9
    assert data["task_id"] == 2
    assert data["attempt"] == 3
    assert data["phase"] == "gates"


def test_repair_context_prompt_appendix_includes_failure_details():
    ctx = build_repair_context(
        1,
        1,
        2,
        apply_ok=True,
        gate_results=[
            {
                "name": "repo_test_command",
                "ok": False,
                "message": "exit 1",
                "details": {"command": "pytest x", "output": "AssertionError: bad\n"},
            }
        ],
        artifact_test_path="tests/forge_generated/test_m1_t1_artifact.py",
    )
    text = repair_context_to_prompt_appendix(ctx)
    assert "PREVIOUS ATTEMPT FAILED" in text
    assert "pytest x" in text
    assert "AssertionError" in text
    assert "test_m1_t1_artifact.py" in text


def test_generate_artifact_tests_writes_pytest_module(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    task = Task(
        id=1,
        milestone_id=1,
        title="t" * 12,
        objective="obj",
        summary="sum",
        depends_on=[],
        validation="v",
        done_when="d",
        status="not_started",
        forge_actions=[],
        forge_validation=["file_contains requirements NEEDLE"],
    )
    from forge.artifact_test_gen import generate_artifact_tests_for_task

    res = generate_artifact_tests_for_task(1, 1, task)
    assert res.generated
    assert res.rel_path
    p = Paths.BASE_DIR / res.rel_path
    assert p.is_file()
    body = p.read_text(encoding="utf-8")
    assert "NEEDLE" in body
    assert "def test_" in body


def test_apply_deferred_gates_does_not_mark_task_complete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Ship
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("MARK")}
""",
    )
    expand_milestone_to_tasks(milestone_id=1, force=True)
    prev = Executor.save_reviewed_plan_for_task(1, 1)
    assert prev.get("ok")
    plan_id = prev["plan_id"]
    res = Executor.apply_reviewed_plan_with_gates(
        plan_id,
        run_validation_gate=False,
        test_command=None,
        mark_task_complete=False,
        record_milestone_attempt=False,
        defer_post_apply_gates=True,
    )
    assert res.get("apply_ok")
    tasks_payload = json.loads((Paths.SYSTEM_DIR / "tasks" / "m1.json").read_text())
    assert tasks_payload["tasks"][0]["status"] != "completed"


@pytest.fixture
def llm_stub_policy_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: A
- **Objective**: A objective
- **Scope**: A scope
- **Validation**: A validation
{compat_forge_block("FORGE_M1")}
""",
    )
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
    Paths.refresh(tmp_path)
    ForgeCLI.milestone_sync_state()


def test_repair_loop_stops_after_max_attempts(llm_stub_policy_project, monkeypatch):
    """Same-task retries exhaust; milestone moves to retry_pending when under cap."""

    def always_fail(*_a, **_k):
        return [
            {
                "name": "milestone_validation",
                "ok": False,
                "message": "mock gate failure",
                "details": {},
            }
        ]

    monkeypatch.setattr(
        "forge.executor.run_validation_and_test_commands",
        always_fail,
    )
    result = Executor.execute_next()
    assert result["outcome"] == "none"
    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "retry_pending"
    t1 = get_task(1, 1)
    assert t1 is not None
    assert t1.status != "completed"


def test_repair_loop_second_gate_pass_completes_task(llm_stub_policy_project, monkeypatch):
    """Bounded loop: second validation pass completes the task (mocked gates)."""

    calls = {"n": 0}

    def fail_then_pass(*_a, **_k):
        calls["n"] += 1
        ok = calls["n"] >= 2
        return [
            {
                "name": "milestone_validation",
                "ok": ok,
                "message": "ok" if ok else "first fail",
                "details": {},
            }
        ]

    monkeypatch.setattr(
        "forge.executor.run_validation_and_test_commands",
        fail_then_pass,
    )
    result = Executor.execute_next()
    assert result["outcome"] == "complete"
    assert calls["n"] == 2
    t1 = get_task(1, 1)
    assert t1 is not None
    assert t1.status == "completed"


def test_save_reviewed_plan_passes_repair_context_to_planner(tmp_path, monkeypatch):
    """Reviewed plan save forwards repair_context into preview/build_plan."""
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Ship
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("CTX")}
""",
    )
    expand_milestone_to_tasks(milestone_id=1, force=True)
    ctx = build_repair_context(1, 1, 1, gate_results=[], extra_message="fixme")
    received: list[dict | None] = []

    class CapturePlanner:
        mode = "deterministic"
        stable_for_recheck = True

        def build_plan(self, milestone, *, repair_context=None):
            received.append(repair_context)
            from forge.planner import DeterministicPlanner

            return DeterministicPlanner().build_plan(milestone, repair_context=repair_context)

        def metadata(self):
            return {"mode": self.mode, "is_nondeterministic": False}

    cap = CapturePlanner()
    out = Executor.save_reviewed_plan_for_task(1, 1, planner=cap, repair_context=ctx)
    assert out.get("ok")
    assert received == [ctx]


def test_load_task_execution_policy_rejects_max_repairs_over_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"task_execution": {"max_repair_attempts": 99}}),
        encoding="utf-8",
    )
    pol, err = load_task_execution_policy()
    assert err and "<= 20" in err
    assert pol.max_repair_attempts == 3
