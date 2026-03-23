"""Regression tests for LLM milestone normalization and weak-plan rejection."""

from __future__ import annotations

import json

from forge.cli import ForgeCLI, main
from forge.design_manager import Milestone, MilestoneService
from forge.paths import Paths
from forge.milestone_llm_quality import (
    WeakMilestonePlanError,
    normalize_milestone_markdown,
    weak_parsed_milestone_plan_messages,
    weak_synthesized_json_plan_messages,
)
from forge.vertical_slice import finalize_llm_milestones_md, run_vertical_slice

# Observed in the wild: LLM omits the leading "- " on **Forge Validation**:, so the parser
# stays inside Forge Actions and errors on the validation bullet line.
REAL_RUN_MARKDOWN_BROKEN_VALIDATION_HEADER = """# Milestones

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


def test_real_run_markdown_broken_validation_header_normalizes_and_parses(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    fixed, warns = normalize_milestone_markdown(REAL_RUN_MARKDOWN_BROKEN_VALIDATION_HEADER)
    assert "- **Forge Validation**:" in fixed
    assert any("Normalized" in w for w in warns)
    MilestoneService.parse_milestones(fixed)
    Paths.MILESTONES_FILE.write_text(fixed, encoding="utf-8")
    assert ForgeCLI._collect_milestone_lint_result(None)["ok"] is True


def test_real_run_markdown_indented_bullets_flatten_for_lint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    md = """# Milestones

## Milestone 1: Ship tool

- **Objective**: Add examples/tool.py.
- **Scope**: examples/ only.
- **Validation**: File exists.

- **Forge Actions**:
  - write_file examples/tool.py | x\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/tool.py x
"""
    fixed, warns = normalize_milestone_markdown(md)
    assert any("Flattened" in w for w in warns)
    MilestoneService.parse_milestones(fixed)
    Paths.MILESTONES_FILE.write_text(fixed, encoding="utf-8")
    assert ForgeCLI._collect_milestone_lint_result(None)["ok"] is True


def test_normalize_heading_forge_actions_to_parser_shape():
    raw = """# Milestones

## Milestone 1: Demo

- **Objective**: o
- **Scope**: s
- **Validation**: v

### Forge Actions
  - write_file examples/a.py | x\\n
  - mark_milestone_completed
### Forge Validation
  - path_file_contains examples/a.py x
"""
    fixed, warns = normalize_milestone_markdown(raw)
    assert "- **Forge Actions**:" in fixed
    assert "- **Forge Validation**:" in fixed
    assert warns
    MilestoneService.parse_milestones(fixed)


def test_finalize_accepts_normalized_markdown():
    raw_ok = """# Milestones

## Milestone 1: T

- **Objective**: Scaffold logcheck CLI under examples/.
- **Scope**: examples/ only.
- **Validation**: Module exists.

### Forge Actions
  - write_file examples/logcheck.py | def main():\\n    print('logcheck')\\n
  - mark_milestone_completed
### Forge Validation
  - path_file_contains examples/logcheck.py logcheck
"""
    out, _ = finalize_llm_milestones_md(
        raw_ok,
        source_context="Build logcheck Python CLI",
    )
    assert "examples/logcheck.py" in out


def test_weak_parsed_rejects_forge_init_only():
    m = Milestone(
        1,
        "Milestone 1: Setup",
        "o",
        "s",
        "v",
        forge_actions=[
            "append_section requirements Overview | FORGE_INIT_MARKER",
            "mark_milestone_completed",
        ],
        forge_validation=["file_contains requirements FORGE_INIT_MARKER"],
    )
    msgs = weak_parsed_milestone_plan_messages([m], idea_context=None)
    assert any("FORGE_INIT_MARKER" in x for x in msgs)
    assert any("substantive code" in x for x in msgs)


def test_weak_parsed_requires_idea_terms():
    m = Milestone(
        1,
        "## Milestone 1: Code",
        "Do work.",
        "examples/",
        "Checks out.",
        forge_actions=[
            "write_file examples/z.py | pass\\n",
            "mark_milestone_completed",
        ],
        forge_validation=["path_file_contains examples/z.py pass"],
    )
    msgs = weak_parsed_milestone_plan_messages(
        [m],
        idea_context="Build logchecker for syslog files",
    )
    assert msgs and any("logchecker" in x or "user's idea" in x for x in msgs)


def test_weak_synthesis_rejects_bootstrap_title_set():
    milestones = [
        {
            "title": "Project Setup",
            "objective": "Initialize repository layout.",
            "scope": "Docs only.",
            "validation": "file_contains requirements x",
        }
    ]
    msg = weak_synthesized_json_plan_messages(
        milestones,
        requirements_excerpt="Lots of words " * 40,
        architecture_excerpt="Components and modules described here " * 20,
    )
    assert msg


def test_weak_synthesis_allows_grounded_plan():
    milestones = [
        {
            "title": "Implement logcheck parser",
            "objective": "Parse syslog lines and count ERROR occurrences.",
            "scope": "examples/logcheck.py",
            "validation": "path_file_contains examples/logcheck.py ERROR",
        }
    ]
    req = " ".join(
        [
            "The logcheck CLI filters ERROR lines from syslog input files.",
            "Top-N counting and reporting are required.",
        ]
        * 15
    )
    assert not weak_synthesized_json_plan_messages(
        milestones,
        requirements_excerpt=req,
        architecture_excerpt="logcheck module argparse stdin",
    )


def test_weak_parsed_rejects_behavior_heavy_scaffold_first_milestone():
    m = Milestone(
        1,
        "Milestone 1: Create CLI entrypoint and basic functionality",
        "Create CLI entrypoint and basic functionality.",
        "Read lines from file.",
        "path_file_contains examples/logcheck.py argparse",
        forge_actions=[
            "write_file examples/logcheck.py | import argparse\\ndef main():\\n    pass\\n",
            "mark_milestone_completed",
        ],
        forge_validation=[
            "path_file_contains examples/logcheck.py argparse",
        ],
    )
    msgs = weak_parsed_milestone_plan_messages(
        [m],
        idea_context=(
            "Build logcheck: count repeated ERROR messages, print top 5 most frequent, "
            "ignore INFO/DEBUG, and include unit tests."
        ),
    )
    assert msgs
    assert any("Milestone 1 is scaffolding-only" in x for x in msgs)


def test_weak_parsed_rejects_placeholder_tests():
    m = Milestone(
        1,
        "Milestone 1: Add parser",
        "Implement parser and tests.",
        "src/ and tests/",
        "behavioral checks",
        forge_actions=[
            "write_file src/logcheck.py | def parse(lines):\\n    return []\\n",
            "write_file tests/test_logcheck.py | def test_placeholder():\\n    pass\\n",
            "mark_milestone_completed",
        ],
        forge_validation=["path_file_contains tests/test_logcheck.py test_placeholder"],
    )
    msgs = weak_parsed_milestone_plan_messages([m], idea_context="count ERROR top 5 ignore INFO DEBUG")
    assert any("placeholder tests" in x.lower() for x in msgs)


def test_weak_synthesis_rejects_behavior_collapse_to_structural_validation():
    milestones = [
        {
            "title": "Create CLI entrypoint and basic functionality",
            "objective": "Create CLI entrypoint.",
            "scope": "Read lines from file.",
            "validation": "path_file_contains examples/logcheck.py argparse",
        }
    ]
    req = (
        "Build logcheck to count repeated ERROR messages, print top 5 most frequent results, "
        "ignore INFO and DEBUG, and include unit tests."
    )
    msgs = weak_synthesized_json_plan_messages(
        milestones,
        requirements_excerpt=req * 8,
        architecture_excerpt="python cli src/logcheck.py tests/test_logcheck.py",
    )
    assert msgs
    assert any("generic scaffolding" in x.lower() or "dropped behavioral requirements" in x.lower() for x in msgs)


def test_run_vertical_slice_surfaces_weak_plan_on_llm_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    Paths.refresh(tmp_path)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )

    def _raise_weak(_vision, _client, *, bundle_llm_artifact_dir=None):
        raise WeakMilestonePlanError(
            [
                "Milestone 1 uses FORGE_INIT_MARKER (template/bootstrap only); "
                "use real Forge Actions for the product."
            ]
        )

    monkeypatch.setattr(
        "forge.vertical_slice.generate_bundle_from_llm_fixed_vision",
        _raise_weak,
    )
    out = run_vertical_slice(
        demo=False,
        idea=None,
        fixed_vision="Build logcheck Python CLI for syslog ERROR lines",
        milestone_id=1,
        planner_mode="deterministic",
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=True,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
    )
    assert out["ok"] is False
    gen_stages = [s for s in out["stages"] if s.get("stage") == "llm_generation"]
    assert gen_stages
    assert "Weak milestone plan" in gen_stages[-1].get("message", "")


def test_finalize_raises_weak_milestone_plan_error():
    md = """# Milestones

## Milestone 1: Bad

- **Objective**: Only docs.
- **Scope**: Docs.
- **Validation**: Marker.

- **Forge Actions**:
  - append_section requirements Overview | FORGE_INIT_MARKER
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements FORGE_INIT_MARKER
"""
    try:
        finalize_llm_milestones_md(md, source_context=None)
    except WeakMilestonePlanError as exc:
        assert exc.messages
    else:
        raise AssertionError("expected WeakMilestonePlanError")
