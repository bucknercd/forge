"""Vertical slice and write_file execution paths."""

from __future__ import annotations

from forge.execution.apply import ArtifactActionApplier
from forge.execution.parse import parse_forge_action_line, parse_forge_validation_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.validation_rules import validate_all_rules
from forge.design_manager import Milestone, MilestoneService
from forge.paths import Paths
from forge.run_event_handlers import EventListCollector, JsonlRunLogHandler
from forge.run_events import RunEventBus
from forge.vertical_slice import demo_bundle, materialize_bundle, run_vertical_slice


def test_parse_write_file_unescapes_newlines():
    m = Milestone(1, "t", "o", "s", "v")
    action = parse_forge_action_line(
        "write_file examples/x.py | line1\\nline2", m, line_no=1
    )
    assert action.rel_path == "examples/x.py"
    assert action.body == "line1\nline2"


def test_parse_path_file_contains():
    rule = parse_forge_validation_line(
        "path_file_contains examples/a.py def main", line_no=1
    )
    assert rule.rel_path == "examples/a.py"
    assert rule.substring == "def main"


def test_write_file_apply_and_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\n\n", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n", encoding="utf-8")
    Paths.MILESTONES_FILE.write_text("# Milestones\n\n", encoding="utf-8")
    ms = """# Milestones

## Milestone 1: Write example file

- **Objective**: Create examples/hello.txt
- **Scope**: One file
- **Validation**: Content check

- **Forge Actions**:
  - write_file examples/hello.txt | hello\\nworld
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/hello.txt world
"""
    Paths.MILESTONES_FILE.write_text(ms, encoding="utf-8")
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    res = applier.apply(plan, milestone, dry_run=False)
    assert not res.errors
    assert (tmp_path / "examples" / "hello.txt").read_text() == "hello\nworld"
    rules = ExecutionPlanBuilder.parse_validation_rules(milestone)
    ok, reason = validate_all_rules(rules, Paths)
    assert ok, reason


def test_vertical_slice_demo_creates_runnable_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.initialize_project()
    assert Paths.MILESTONES_FILE.exists()
    out = run_vertical_slice(
        demo=True,
        idea=None,
        milestone_id=1,
        planner_mode="deterministic",
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=False,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
    )
    assert out["ok"], out
    todo = tmp_path / "examples" / "todo_cli.py"
    assert todo.exists()
    assert "def main" in todo.read_text(encoding="utf-8")


def test_vertical_slice_emits_core_events_to_jsonl(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.initialize_project()
    run_id = "testrun123456"
    events_path = Paths.forge_run_dir(run_id) / "events.jsonl"
    collector = EventListCollector()
    bus = RunEventBus(run_id, [JsonlRunLogHandler(events_path), collector])
    out = run_vertical_slice(
        demo=True,
        idea=None,
        milestone_id=1,
        planner_mode="deterministic",
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=False,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
        event_bus=bus,
    )
    assert out["ok"]
    assert events_path.is_file()
    lines = events_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 5
    types = [e["type"] for e in collector.events]
    assert "run_started" in types
    assert "artifact_written" in types
    assert "plan_saved" in types
    assert "action_applied" in types
    assert "run_completed" in types


def test_materialize_demo_bundle_parseable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    bundle = demo_bundle()
    materialize_bundle(bundle)
    ms = MilestoneService.list_milestones()
    assert len(ms) >= 1
    plan = ExecutionPlanBuilder.build(ms[0])
    assert any(a.__class__.__name__ == "ActionWriteFile" for a in plan.actions)
