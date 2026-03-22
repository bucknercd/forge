"""Vertical slice and write_file execution paths."""

from __future__ import annotations

import json

from forge.execution.apply import ArtifactActionApplier
from forge.execution.parse import parse_forge_action_line, parse_forge_validation_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.validation_rules import validate_all_rules
from forge.design_manager import Milestone, MilestoneService
from forge.paths import Paths
from forge.run_event_handlers import EventListCollector, JsonlRunLogHandler
from forge.run_events import RunEventBus
from forge.llm import LLMClient
from forge.milestone_llm_quality import WeakMilestonePlanError
from forge.vertical_slice import (
    MILESTONES_DOC_PATH,
    demo_bundle,
    finalize_llm_milestones_md,
    generate_bundle_from_llm,
    generate_bundle_from_llm_fixed_vision,
    materialize_bundle,
    read_vision_file_text,
    repair_llm_milestones_md,
    resolve_vision_file_path,
    run_vertical_slice,
)


class _FakeVerticalSliceLLM(LLMClient):
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def generate(self, prompt: str) -> str:
        return json.dumps(self._payload)

    @property
    def client_id(self) -> str:
        return "fake"


class _FakeVerticalSliceSequenceLLM(LLMClient):
    """Returns successive JSON payloads (weak plan retry integration)."""

    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = payloads
        self.calls = 0

    def generate(self, prompt: str) -> str:
        p = self._payloads[self.calls]
        self.calls += 1
        return json.dumps(p)

    @property
    def client_id(self) -> str:
        return "fake"


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


def test_read_vision_file_text_missing(tmp_path):
    p = tmp_path / "nope.txt"
    try:
        read_vision_file_text(p)
    except FileNotFoundError as exc:
        assert "Vision file does not exist" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_read_vision_file_text_empty(tmp_path):
    p = tmp_path / "v.txt"
    p.write_text("  \n\t  ", encoding="utf-8")
    try:
        read_vision_file_text(p)
    except ValueError as exc:
        assert "empty" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_resolve_vision_file_path_relative_to_base(tmp_path):
    assert resolve_vision_file_path("sub/x.txt", base_dir=tmp_path) == (
        tmp_path / "sub" / "x.txt"
    ).resolve()


def test_generate_bundle_from_llm_fixed_vision_uses_file_vision():
    vision = "AUTHORITATIVE multi\nline vision."
    ms = """# Milestones

## Milestone 1: One

- **Objective**: x — implements the authoritative multi-line vision.
- **Scope**: y
- **Validation**: z

- **Forge Actions**:
  - write_file examples/x.py | x\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/x.py x
"""
    client = _FakeVerticalSliceLLM(
        {
            "requirements_md": "# Requirements\n\nok\n",
            "architecture_md": "# Architecture\n\nok\n",
            "milestones_md": ms,
        }
    )
    bundle = generate_bundle_from_llm_fixed_vision(vision, client)
    assert bundle.vision == vision
    assert "Requirements" in bundle.requirements_md
    assert "Milestones" in bundle.milestones_md


def test_repair_llm_milestones_md_inserts_missing_objective_scope_validation():
    raw = """# Milestones

## Milestone 1: Thin

- **Forge Actions**:
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/x.py x
"""
    fixed, warnings = repair_llm_milestones_md(raw)
    assert "placeholder" in fixed.lower()
    assert any("Objective" in w for w in warnings)
    assert any("Scope" in w for w in warnings)
    assert any("Validation" in w for w in warnings)
    MilestoneService.parse_milestones(fixed)


def test_repair_llm_milestones_md_keeps_nonempty_fields():
    raw = """# Milestones

## Milestone 1: Full
- **Objective**: Real objective.
- **Scope**: Real scope.
- **Validation**: Real validation.
- **Forge Actions**:
  - mark_milestone_completed
"""
    fixed, warnings = repair_llm_milestones_md(raw)
    assert not warnings
    assert "Real objective." in fixed
    m = MilestoneService.parse_milestones(fixed)
    assert m[0].objective == "Real objective."


def test_finalize_llm_milestones_md_error_mentions_docs_path():
    bad = "# Milestones\n\n## Milestone One\n- **Objective**: x\n"
    try:
        finalize_llm_milestones_md(bad)
    except ValueError as exc:
        assert MILESTONES_DOC_PATH in str(exc)
        assert "vertical-slice" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_generate_bundle_from_llm_repairs_partial_milestone():
    ms = """# Milestones

## Milestone 1: Partial

- **Objective**: Do the thing.
- **Forge Actions**:
  - write_file examples/partial.py | pass\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/partial.py pass
"""
    client = _FakeVerticalSliceLLM(
        {
            "vision": "v",
            "requirements_md": "# R\n",
            "architecture_md": "# A\n",
            "milestones_md": ms,
        }
    )
    bundle = generate_bundle_from_llm("idea", client)
    assert "placeholder" in bundle.milestones_md.lower()
    m = MilestoneService.parse_milestones(bundle.milestones_md)
    assert m[0].scope.strip()
    assert m[0].validation.strip()


def test_generate_bundle_from_llm_retries_after_weak_first_payload():
    idea = "Build logcheck, a small Python CLI for syslog analysis"
    bad_ms = """# Milestones

## Milestone 1: Project Setup

- **Objective**: Initialize documentation markers only.
- **Scope**: requirements Overview section.
- **Validation**: Marker present.

- **Forge Actions**:
  - append_section requirements Overview | FORGE_INIT_MARKER
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements FORGE_INIT_MARKER
"""
    good_ms = """# Milestones

## Milestone 1: Logcheck CLI skeleton

- **Objective**: Add examples/logcheck.py implementing the logcheck CLI entrypoint.
- **Scope**: Stdlib argparse under examples/ only.
- **Validation**: Runnable module with def main.

- **Forge Actions**:
  - write_file examples/logcheck.py | import argparse\\ndef main():\\n    print('logcheck')\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/logcheck.py def main
"""
    shared_docs = {
        "requirements_md": "# Requirements\n\nLogcheck filters syslog ERROR lines.\n",
        "architecture_md": "# Architecture\n\nSingle-module CLI under examples/logcheck.py.\n",
    }
    client = _FakeVerticalSliceSequenceLLM(
        [
            {
                "vision": "logcheck CLI",
                **shared_docs,
                "milestones_md": bad_ms,
            },
            {
                "vision": "logcheck CLI",
                **shared_docs,
                "milestones_md": good_ms,
            },
        ]
    )
    bundle = generate_bundle_from_llm(idea, client)
    assert client.calls == 2
    assert "logcheck" in bundle.milestones_md.lower()
    assert "examples/logcheck.py" in bundle.milestones_md


def test_generate_bundle_from_llm_raises_after_two_weak_payloads():
    weak_ms = """# Milestones

## Milestone 1: Setup

- **Objective**: o
- **Scope**: s
- **Validation**: v

- **Forge Actions**:
  - append_section requirements Overview | FORGE_INIT_MARKER
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements FORGE_INIT_MARKER
"""
    payload = {
        "vision": "v",
        "requirements_md": "# R\n",
        "architecture_md": "# A\n",
        "milestones_md": weak_ms,
    }
    client = _FakeVerticalSliceSequenceLLM([payload, dict(payload)])
    try:
        generate_bundle_from_llm("idea", client)
    except WeakMilestonePlanError:
        assert client.calls == 2
    else:
        raise AssertionError("expected WeakMilestonePlanError")


def test_generate_bundle_logcheck_single_payload_integration():
    idea = "Build logcheck Python CLI to scan logs for ERROR lines"
    ms = """# Milestones

## Milestone 1: Implement logcheck core

- **Objective**: Provide examples/logcheck.py CLI that reads log lines and filters ERROR.
- **Scope**: Stdlib only; examples/ path.
- **Validation**: path_file_contains checks for filtering logic.

- **Forge Actions**:
  - write_file examples/logcheck.py | import sys\\ndef main():\\n    print('logcheck')\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/logcheck.py logcheck
"""
    client = _FakeVerticalSliceLLM(
        {
            "vision": "logcheck tool",
            "requirements_md": "# Requirements\n\nLogcheck CLI scans text for ERROR.\n",
            "architecture_md": "# Architecture\n\nModule examples/logcheck.py.\n",
            "milestones_md": ms,
        }
    )
    bundle = generate_bundle_from_llm(idea, client)
    lowered = bundle.milestones_md.lower()
    assert "logcheck" in lowered
    assert "error" in bundle.requirements_md.lower() or "error" in lowered


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
