"""Canonical Python path normalization for write/apply and repair stability."""

from __future__ import annotations

from forge.design_manager import Milestone, MilestoneService
from forge.execution.apply import ArtifactActionApplier
from forge.execution.models import (
    ActionMarkMilestoneCompleted,
    ActionWriteFile,
    ExecutionPlan,
)
from forge.executor import Executor
from forge.paths import Paths
from forge.planner import Planner
from forge.policy_config import ReviewedApplyPolicy, TaskExecutionPolicy
from forge.task_service import ensure_tasks_for_milestone
from tests.forge_test_project import configure_project


def test_write_file_examples_python_is_normalized_to_src(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: P
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    m = Milestone(1, "t", "o", "s", "v")
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[
            ActionWriteFile("examples/foo.py", "print('x')\n"),
            ActionMarkMilestoneCompleted(),
        ],
    )
    res = ArtifactActionApplier(Paths).apply(plan, m, dry_run=False)
    assert not res.errors
    assert (tmp_path / "src" / "foo.py").is_file()
    assert not (tmp_path / "examples" / "foo.py").exists()
    wf = next(a for a in res.actions_applied if a["type"] == "write_file")
    assert wf["rel_path"] == "src/foo.py"
    assert wf["path_normalized_from"] == "examples/foo.py"
    assert wf["path_normalized_to"] == "src/foo.py"
    assert (tmp_path / "src" / "__init__.py").is_file()


def test_write_file_rewrites_examples_imports_in_tests(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: P
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    m = Milestone(1, "t", "o", "s", "v")
    body = (
        "from examples.logcheck import main\n"
        "import examples.logcheck as lc\n"
        "from examples import logcheck\n"
        "from ..src.logcheck import parse_log\n"
        "from ..src import logcheck as lg\n"
    )
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile("tests/test_logcheck.py", body)],
    )
    res = ArtifactActionApplier(Paths).apply(plan, m, dry_run=False)
    assert not res.errors
    text = (tmp_path / "tests" / "test_logcheck.py").read_text(encoding="utf-8")
    assert "from src.logcheck import main" in text
    assert "import src.logcheck as lc" in text
    assert "from src import logcheck" in text
    assert "from src.logcheck import parse_log" in text
    assert "from src import logcheck as lg" in text
    wf = next(a for a in res.actions_applied if a["type"] == "write_file")
    assert wf.get("imports_rewritten") is True


class _AlternatingPlanner(Planner):
    mode = "llm"
    stable_for_recheck = False

    def __init__(self) -> None:
        self.calls = 0

    def build_plan(self, milestone, *, repair_context=None) -> ExecutionPlan:
        _ = repair_context
        self.calls += 1
        rel = "examples/logcheck.py" if self.calls == 1 else "src/logcheck.py"
        body = (
            "def count_errors(path):\n"
            "    n = 0\n"
            "    with open(path, encoding='utf-8') as f:\n"
            "        for line in f:\n"
            "            if 'ERROR' in line:\n"
            "                n += 1\n"
            "    return n\n\n"
            "def main():\n"
            f"    return {self.calls}\n"
        )
        return ExecutionPlan(
            milestone_id=milestone.id,
            actions=[ActionWriteFile(rel, body), ActionMarkMilestoneCompleted()],
        )

    def metadata(self) -> dict:
        return {
            "mode": "llm",
            "is_nondeterministic": True,
            "llm_client": "test",
            "llm_model": None,
        }


def test_repair_loop_keeps_canonical_src_path_across_attempts(tmp_path, monkeypatch):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Path Stability
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    ensure_tasks_for_milestone(1)
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    planner = _AlternatingPlanner()

    calls = {"n": 0}

    def fail_then_pass(*_a, **_k):
        calls["n"] += 1
        return [
            {
                "name": "milestone_validation",
                "ok": calls["n"] >= 2,
                "message": "ok" if calls["n"] >= 2 else "fail",
                "details": {},
            }
        ]

    monkeypatch.setattr("forge.executor.run_validation_and_test_commands", fail_then_pass)
    out = Executor.run_task_apply_with_repair_loop(
        1,
        1,
        milestone,
        planner=planner,
        apply_policy=ReviewedApplyPolicy(run_validation_gate=True),
        task_exec_policy=TaskExecutionPolicy(
            artifact_test_generation=False, max_repair_attempts=3
        ),
        run_milestone_validation=True,
        initial_plan_id=None,
        review_enforcement=None,
        event_bus=None,
    )
    assert out["ok"] is True
    assert planner.calls >= 2
    assert (tmp_path / "src" / "logcheck.py").is_file()
    assert not (tmp_path / "examples" / "logcheck.py").exists()
