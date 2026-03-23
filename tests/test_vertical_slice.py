"""Vertical slice and write_file execution paths."""

from __future__ import annotations

import json

import pytest

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
    VerticalSliceBundle,
    _repair_multiline_write_file_actions,
    canonical_milestones_md_from_llm_raw,
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


# Raw LLM shape: indented Forge bullets + ``**Forge Validation**:`` without leading ``- ``.
RAW_LLM_MILESTONES_MALFORMED_HEADERS = """# Milestones

## Milestone 1: Logcheck slice

- **Objective**: Add logcheck CLI under examples/ for syslog review.
- **Scope**: examples/ only.
- **Validation**: Module exists and contains entrypoint.

- **Forge Actions**:
  - write_file examples/logcheck.py | def main():\\n    pass\\n
  - mark_milestone_completed
**Forge Validation**:
  - path_file_contains examples/logcheck.py def main
"""


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


def test_parse_path_file_contains_single_quoted_needle():
    rule = parse_forge_validation_line(
        "path_file_contains src/logcheck.py 'def count_errors'", line_no=1
    )
    assert rule.rel_path == "src/logcheck.py"
    assert rule.substring == "def count_errors"
    assert rule.substring_quote_style == "single"


def test_write_file_apply_and_validation_quoted_path_file_contains(tmp_path, monkeypatch):
    """File on disk has no quote chars; validation line uses shell-like quotes."""
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
  - write_file examples/hello.txt | def count_errors():\\n    return 1\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/hello.txt 'def count_errors'
"""
    Paths.MILESTONES_FILE.write_text(ms, encoding="utf-8")
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    res = applier.apply(plan, milestone, dry_run=False)
    assert not res.errors
    body = (tmp_path / "examples" / "hello.txt").read_text(encoding="utf-8")
    assert "def count_errors" in body
    rules = ExecutionPlanBuilder.parse_validation_rules(milestone)
    ok, reason = validate_all_rules(rules, Paths)
    assert ok, reason


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
    todo = tmp_path / "src" / "todo_cli.py"
    assert todo.exists()
    assert "def main" in todo.read_text(encoding="utf-8")


def test_vertical_slice_strips_embedded_forge_actions_and_fails_stub(tmp_path, monkeypatch):
    """
    Regression:
    - LLM milestones must not embed execution (Forge Actions).
    - Implementation must be produced by the planner, not milestone text.
    - Stub-only implementations are rejected via stub_detection (missing_impl).
    """
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.initialize_project()

    class _CountingPlannerLLM(LLMClient):
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: str) -> str:
            self.calls += 1
            # Stub scaffold: argparse only, no file I/O, no loops.
            code = (
                "import argparse\n"
                "\n"
                "def main():\n"
                "    parser = argparse.ArgumentParser(prog='logcheck')\n"
                "    parser.add_argument('path')\n"
                "    _args = parser.parse_args()\n"
                "    print('logcheck stub')\n"
                "\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            )
            actions = [
                # Ensure stub_detection classifies this as only-CLI scaffold.
                "write_file src/logcheck.py | "
                + code.replace("\n", "\\n"),
                "mark_milestone_completed",
            ]
            return json.dumps({"actions": actions})

        @property
        def client_id(self) -> str:
            return "planner_stub_counter"

    docs_llm_payload = {
        "vision": "logcheck vision",
        "requirements_md": "# Requirements\n\nImplement logcheck.\n",
        "architecture_md": "# Architecture\n\nlogcheck CLI.\n",
        "milestones_md": """# Milestones

## Milestone 1: Logcheck slice
- **Objective**: Implement logcheck behavior (filter/count ERROR lines).
- **Scope**: src/ and tests/
- **Validation**: filter ERROR lines and count occurrences (top-k).

- **Forge Actions**:
  - write_file src/logcheck.py | def main():\\n    print('stub')\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/logcheck.py argparse
  - path_file_contains src/logcheck.py def main
""",
    }

    docs_client = _FakeVerticalSliceLLM(docs_llm_payload)
    planner_llm = _CountingPlannerLLM()

    from forge.planner import LLMPlanner
    from forge.policy_config import PlannerPolicy

    def _fake_resolve_planner(mode_override: str | None = None):
        # Always return an LLM planner that uses our stub planner LLM.
        return (
            LLMPlanner(planner_llm, fallback_to_milestone_actions=False),
            PlannerPolicy(mode="llm", llm_client="stub"),
            None,
        )

    monkeypatch.setattr("forge.vertical_slice.resolve_docs_llm_client", lambda: (docs_client, None))
    monkeypatch.setattr("forge.vertical_slice.resolve_planner", _fake_resolve_planner)

    out = run_vertical_slice(
        demo=False,
        idea="build logcheck for syslog",
        fixed_vision=None,
        milestone_id=1,
        planner_mode="deterministic",
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=True,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
    )

    assert out["ok"] is False
    apply_stage = next(s for s in out["stages"] if s.get("stage") == "apply_plan")
    fc = apply_stage.get("failure_classification") or {}
    assert fc.get("mode") == "missing_impl"

    # Embedded execution must be stripped from the generated milestones spec.
    md = (tmp_path / "docs" / "milestones.md").read_text(encoding="utf-8")
    assert "write_file" not in md

    # Planner must be invoked to generate the implementation code.
    assert planner_llm.calls >= 1


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


def test_vertical_slice_llm_timeout_reports_llm_generation_phase(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.initialize_project()

    class _TimeoutLLM(LLMClient):
        def generate(self, prompt: str) -> str:  # noqa: ARG002
            raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(
        "forge.vertical_slice.resolve_docs_llm_client",
        lambda: (_TimeoutLLM(), None),
    )
    collector = EventListCollector()
    bus = RunEventBus("testrun_timeout_1", [collector])
    out = run_vertical_slice(
        demo=False,
        idea="build logcheck",
        fixed_vision=None,
        milestone_id=1,
        planner_mode=None,
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=False,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
        event_bus=bus,
    )
    assert out["ok"] is False
    llm_stage = next(s for s in out["stages"] if s.get("stage") == "llm_generation")
    assert llm_stage["ok"] is False
    assert llm_stage.get("failure_type") == "llm_timeout"
    assert "LLM generation timed out" in llm_stage.get("message", "")
    run_failed = [e for e in collector.events if e["type"] == "run_failed"]
    assert run_failed
    assert run_failed[-1]["data"].get("phase") == "llm_generation"


def test_vertical_slice_llm_timeout_no_false_materialize_docs_failure(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.initialize_project()

    class _TimeoutLLM(LLMClient):
        def generate(self, prompt: str) -> str:  # noqa: ARG002
            raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(
        "forge.vertical_slice.resolve_docs_llm_client",
        lambda: (_TimeoutLLM(), None),
    )
    collector = EventListCollector()
    bus = RunEventBus("testrun_timeout_2", [collector])
    out = run_vertical_slice(
        demo=False,
        idea="build logcheck",
        fixed_vision=None,
        milestone_id=1,
        planner_mode=None,
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=False,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
        event_bus=bus,
    )
    assert out["ok"] is False
    bad_materialize = [
        s
        for s in out["stages"]
        if s.get("stage") == "materialize_docs" and not s.get("ok")
    ]
    assert bad_materialize == []
    phase_done = [
        e
        for e in collector.events
        if e["type"] == "phase_completed"
        and (e.get("data") or {}).get("phase") == "llm_generation"
    ]
    assert phase_done
    assert phase_done[-1]["data"].get("ok") is False


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


def test_repair_multiline_write_file_actions_collapses_to_escaped_newlines():
    raw = """# Milestones

## Milestone 1: T
- **Objective**: Add parser.
- **Scope**: src/
- **Validation**: exists.

- **Forge Actions**:
  - write_file src/logcheck/parser.py | import os

def parse_log(file_path):
    pass
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/logcheck/parser.py import os
"""
    out, warnings = _repair_multiline_write_file_actions(raw)
    assert any("Folded multiline" in w for w in warnings)
    folded_line = next(ln for ln in out.splitlines() if "write_file src/logcheck/parser.py" in ln)
    assert r"\n" in folded_line
    assert "parse_log" in folded_line
    assert "mark_milestone_completed" in out


def test_finalize_llm_milestones_md_multiline_write_file_integration():
    """Real LLM shape: body lines after ``|`` are separate lines; finalize → parse succeeds."""
    raw = """# Milestones

## Milestone 1: Parser module

- **Objective**: Add src/logcheck/parser.py with a parse_log entrypoint.
- **Scope**: Single module under src/logcheck/.
- **Validation**: Module imports and defines parse_log.

- **Forge Actions**:
  - write_file src/logcheck/parser.py | import os

def parse_log(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError("missing")
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/logcheck/parser.py def parse_log
"""
    idea = "Build logcheck, a Python CLI for syslog analysis under src/logcheck/"
    out, _warnings = finalize_llm_milestones_md(raw, source_context=idea)
    m = MilestoneService.parse_milestones(out)
    assert m[0].forge_actions[0].startswith("write_file src/logcheck/parser.py")
    assert "def parse_log" in m[0].forge_actions[0]


def test_finalize_llm_milestones_md_persists_raw_on_parse_failure(tmp_path):
    bad = "# Milestones\n\n## Milestone One\n- **Objective**: x\n"
    with pytest.raises(ValueError):
        finalize_llm_milestones_md(bad, failure_artifact_dir=tmp_path)
    assert (tmp_path / "milestones_md_failure_raw.txt").read_text(encoding="utf-8") == bad


def test_finalize_llm_milestones_md_still_rejects_garbage():
    with pytest.raises(ValueError):
        finalize_llm_milestones_md("# not a milestone file\n", source_context="idea")


def test_materialize_bundle_persists_milestones_md_on_parse_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    bundle = VerticalSliceBundle(
        vision="v",
        requirements_md="# R\n",
        architecture_md="# A\n",
        milestones_md="# Milestones\n\n## Milestone One\n",
    )
    with pytest.raises(ValueError):
        materialize_bundle(bundle, failure_artifact_dir=tmp_path)
    art = tmp_path / "milestones_md_materialize_parse_failure.txt"
    assert art.exists()
    assert "Milestone One" in art.read_text(encoding="utf-8")


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

- **Objective**: Provide examples/logcheck.py CLI that filters ERROR lines and counts repeated messages.
- **Scope**: Stdlib only; examples/ path.
- **Validation**: behavior-oriented checks for filtering and counting logic.

- **Forge Actions**:
  - write_file examples/logcheck.py | import sys\\ndef count_errors(lines):\\n    out = {}\\n    for ln in lines:\\n        if 'ERROR' in ln:\\n            out[ln] = out.get(ln, 0) + 1\\n    return out\\n\\ndef main():\\n    print('logcheck')\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/logcheck.py ERROR
  - path_file_contains examples/logcheck.py count_errors
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


def test_materialize_bundle_writes_exact_bundle_milestones_md(tmp_path, monkeypatch):
    """Regression: on-disk milestones.md must equal bundle.milestones_md (canonical/finalized)."""
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    idea = "Build logcheck tool for syslog parsing"
    canonical, _ = canonical_milestones_md_from_llm_raw(
        RAW_LLM_MILESTONES_MALFORMED_HEADERS,
        source_context=idea,
    )
    assert RAW_LLM_MILESTONES_MALFORMED_HEADERS.strip() != canonical.strip()
    assert "- **Forge Validation**:" in canonical
    bundle = VerticalSliceBundle(
        vision="v",
        requirements_md="# R\n",
        architecture_md="# A\n",
        milestones_md=canonical,
    )
    materialize_bundle(bundle)
    assert Paths.MILESTONES_FILE.read_text(encoding="utf-8") == canonical


def test_generate_bundle_milestones_md_matches_canonical_and_disk(tmp_path, monkeypatch):
    """LLM JSON ``milestones_md`` is normalized; bundle + docs file must not retain raw LLM text."""
    idea = "Build logcheck tool for syslog parsing"
    expected_canonical, _ = canonical_milestones_md_from_llm_raw(
        RAW_LLM_MILESTONES_MALFORMED_HEADERS,
        source_context=idea,
    )
    client = _FakeVerticalSliceLLM(
        {
            "vision": "logcheck",
            "requirements_md": "# Requirements\n\nLogcheck.\n",
            "architecture_md": "# Architecture\n\nexamples/logcheck.py\n",
            "milestones_md": RAW_LLM_MILESTONES_MALFORMED_HEADERS,
        }
    )
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    bundle = generate_bundle_from_llm(idea, client)
    assert bundle.milestones_md == expected_canonical
    assert bundle.milestones_md != RAW_LLM_MILESTONES_MALFORMED_HEADERS
    Paths.ensure_project_structure()
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    materialize_bundle(bundle)
    assert Paths.MILESTONES_FILE.read_text(encoding="utf-8") == bundle.milestones_md


def test_generate_bundle_weak_bootstrap_rejected_after_normalization(tmp_path, monkeypatch):
    """Parse succeeds only after normalize; weak-plan gate still rejects FORGE_INIT bootstrap."""
    idea = "Build logcheck syslog CLI tool"
    bootstrap_raw = """# Milestones

## Milestone 1: Project Setup
- **Objective**: Establish the initial project structure.
- **Scope**: Bootstrap docs, runtime state, and baseline workflows.
- **Validation**: Confirm core commands run successfully.
- **Forge Actions**:
  - append_section requirements Overview | FORGE_INIT_MARKER
  - mark_milestone_completed
**Forge Validation**:
  - file_contains requirements FORGE_INIT_MARKER
"""
    client = _FakeVerticalSliceLLM(
        {
            "vision": "v",
            "requirements_md": "# R\n",
            "architecture_md": "# A\n",
            "milestones_md": bootstrap_raw,
        }
    )
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    with pytest.raises(WeakMilestonePlanError):
        generate_bundle_from_llm(idea, client)


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
