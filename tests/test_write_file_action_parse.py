"""write_file forge action: delimiter must not split inside the body (e.g. Python ``a | b``)."""

from __future__ import annotations

import json

import pytest

from forge.design_manager import Milestone, MilestoneService
from forge.execution.apply import ArtifactActionApplier
from forge.execution.models import ActionAppendSection, ActionWriteFile
from forge.execution.parse import parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.paths import Paths
from forge.planner import LLMPlanner
from tests.forge_test_project import configure_project
from tests.test_planner_abstraction import FakeLLM


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


def test_write_file_body_with_space_pipe_space_bitwise_or_preserved():
    body = (
        "import sys\n"
        "def main():\n"
        "    x = 1 | 2\n"
        "    y = a | b\n"
        "    if len(sys.argv) != 2:\n"
        "        print('usage')\n"
    )
    raw = f"write_file src/x.py | {_esc(body)}"
    m = Milestone(1, "t", "o", "s", "v")
    act = parse_forge_action_line(raw, m)
    assert isinstance(act, ActionWriteFile)
    assert act.body == body


def test_write_file_body_quotes_colons_parentheses():
    body = (
        'def f():\n'
        '    d = {"k": "v", "x": (1 | 2)}\n'
        '    return d["k"]\n'
    )
    raw = f"write_file src/z.py | {_esc(body)}"
    m = Milestone(1, "t", "o", "s", "v")
    act = parse_forge_action_line(raw, m)
    assert act.body == body


def test_write_file_long_body_not_truncated():
    body = "\n".join([f"# line {i}\nprint({i})" for i in range(120)])
    raw = f"write_file src/long.py | {_esc(body)}"
    m = Milestone(1, "t", "o", "s", "v")
    act = parse_forge_action_line(raw, m)
    assert len(act.body) == len(body)
    assert act.body == body


def test_write_file_blank_lines_preserved():
    body = "a = 1\n\n\nb = 2\n"
    raw = f"write_file src/a.py | {_esc(body)}"
    m = Milestone(1, "t", "o", "s", "v")
    assert parse_forge_action_line(raw, m).body == body


def test_plan_apply_roundtrip_bytes_match_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    body = (
        "import sys\n\n"
        "def main() -> None:\n"
        "    if len(sys.argv) != 2:\n"
        "        print('usage: app <file>')\n"
        "        raise SystemExit(1)\n"
        "    print('ok')\n"
    )
    raw = f"write_file src/logcheck.py | {_esc(body)}"
    m = Milestone(1, "t", "o", "s", "v", forge_actions=[raw, "mark_milestone_completed"])
    plan = ExecutionPlanBuilder.build(m)
    applier = ArtifactActionApplier(Paths)
    applier.apply(plan, m, dry_run=False)
    disk = (Paths.BASE_DIR / "src" / "logcheck.py").read_bytes()
    assert disk == body.encode("utf-8")
    wf = plan.actions[0]
    assert isinstance(wf, ActionWriteFile)
    assert wf.body.encode("utf-8") == disk


def test_llm_planner_fenced_json_repair_loop_shape(tmp_path, monkeypatch):
    """Near-miss: prose + fenced JSON still extracts (same as vertical-slice)."""
    monkeypatch.chdir(tmp_path)
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
    inner = json.dumps(
        {
            "actions": [
                "append_section requirements Overview | FENCED_OK",
                "mark_milestone_completed",
            ]
        }
    )
    raw = f"Here is the plan:\n```json\n{inner}\n```\n"
    planner = LLMPlanner(FakeLLM(raw))
    m = __import__("forge.design_manager", fromlist=["MilestoneService"]).MilestoneService.get_milestone(1)
    plan = planner.build_plan(m)
    assert planner.metadata().get("json_extraction_kind") in (
        "markdown_fenced",
        "balanced_object",
    )
    assert any(
        isinstance(a, __import__("forge.execution.models", fromlist=["ActionAppendSection"]).ActionAppendSection)
        for a in plan.actions
    )


def test_llm_planner_invalid_json_surfaces_artifact_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: B
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    planner = LLMPlanner(FakeLLM("{ not json"), fallback_to_milestone_actions=False)
    m = MilestoneService.get_milestone(1)
    assert m is not None
    with pytest.raises(ValueError) as exc:
        planner.build_plan(m)
    msg = str(exc.value).lower()
    assert "llm planner" in msg
    assert "raw planner output saved to" in msg
    assert "llm_planner_failures" in msg
