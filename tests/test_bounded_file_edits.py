"""Bounded file edit actions: parse, apply, deterministic match failures."""

from __future__ import annotations

import pytest

from forge.design_manager import Milestone, MilestoneService
from forge.execution.apply import ArtifactActionApplier
from forge.execution.file_edits import (
    apply_insert_after,
    apply_replace_block,
    apply_replace_text,
    nonoverlapping_spans,
)
from forge.execution.models import ExecutionPlan
from forge.execution.parse import FORGE_BOUNDED_EDIT_SEP, parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.paths import Paths


def test_nonoverlapping_spans_counts():
    assert nonoverlapping_spans("aaa", "aa") == [(0, 2)]
    assert len(nonoverlapping_spans("abab", "ab")) == 2


def test_apply_insert_after_unique():
    t = "one\nTWO\nthree"
    assert apply_insert_after(t, "TWO", "X") == "one\nTWOX\nthree"


def test_apply_insert_after_zero_raises():
    with pytest.raises(ValueError, match="no match"):
        apply_insert_after("abc", "Z", "x")


def test_apply_insert_after_ambiguous_raises():
    with pytest.raises(ValueError, match="ambiguous"):
        apply_insert_after("xx yy xx", "xx", "!")


def test_apply_replace_text_ambiguous():
    with pytest.raises(ValueError, match="ambiguous"):
        apply_replace_text("a OLD b OLD c", "OLD", "new")


def test_apply_replace_text_unique():
    assert apply_replace_text("hello world", "world", "Forge") == "hello Forge"


def test_replace_block_no_end_raises():
    with pytest.raises(ValueError, match="no match for end"):
        apply_replace_block("START only", "START", "END", "NEW")


def test_replace_block_ambiguous_start():
    with pytest.raises(ValueError, match="ambiguous"):
        apply_replace_block("START a START b END", "START", "END", "NEW")


def test_replace_block_success():
    text = "before START mid END after"
    out = apply_replace_block(text, "START", "END", "NEW")
    assert out == "before NEW after"


def test_parse_bounded_edit_requires_separator():
    m = Milestone(1, "t", "o", "s", "v")
    with pytest.raises(ValueError, match="insert_after_in_file"):
        parse_forge_action_line(
            "insert_after_in_file examples/x.txt anchor only", m, line_no=1
        )


def test_parse_replace_block_three_parts():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    raw = f"replace_block_in_file examples/b.txt | A{sep}B{sep}C"
    act = parse_forge_action_line(raw, m)
    assert act.start_marker == "A"
    assert act.end_marker == "B"
    assert act.new_body == "C"


def _configure_project_with_milestone(tmp_path, monkeypatch, milestones_md: str):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    Paths.REQUIREMENTS_FILE.write_text("# R\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# A\n", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# D\n", encoding="utf-8")
    Paths.MILESTONES_FILE.write_text(milestones_md, encoding="utf-8")
    return MilestoneService.get_milestone(1)


def test_integration_insert_after_apply(tmp_path, monkeypatch):
    sep = FORGE_BOUNDED_EDIT_SEP
    f = tmp_path / "examples" / "edit.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("line1\nANCHOR\nline3\n", encoding="utf-8")
    ms = f"""# Milestones

## Milestone 1: Edit

- **Objective**: x
- **Scope**: y
- **Validation**: z

- **Forge Actions**:
  - insert_after_in_file examples/edit.txt | ANCHOR{sep}\\nINJECTED\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/edit.txt INJECTED
"""
    milestone = _configure_project_with_milestone(tmp_path, monkeypatch, ms)
    assert milestone is not None
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    res = applier.apply(plan, milestone, dry_run=False)
    assert not res.errors
    assert "INJECTED" in f.read_text(encoding="utf-8")


def test_integration_insert_after_ambiguous_fails(tmp_path, monkeypatch):
    sep = FORGE_BOUNDED_EDIT_SEP
    f = tmp_path / "examples" / "dup.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("X\nX\n", encoding="utf-8")
    ms = f"""# Milestones

## Milestone 1: Bad

- **Objective**: x
- **Scope**: y
- **Validation**: z

- **Forge Actions**:
  - insert_after_in_file examples/dup.txt | X{sep}Z
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/dup.txt Z
"""
    milestone = _configure_project_with_milestone(tmp_path, monkeypatch, ms)
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    res = applier.apply(plan, milestone, dry_run=False)
    assert res.errors
    assert "ambiguous" in res.errors[0].lower()


def test_integration_dry_run_shows_diff_without_write(tmp_path, monkeypatch):
    sep = FORGE_BOUNDED_EDIT_SEP
    f = tmp_path / "examples" / "dry.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    original = "ONLY\n"
    f.write_text(original, encoding="utf-8")
    ms = f"""# Milestones

## Milestone 1: Dry

- **Objective**: x
- **Scope**: y
- **Validation**: z

- **Forge Actions**:
  - replace_text_in_file examples/dry.txt | ONLY{sep}CHANGED
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/dry.txt ONLY
"""
    milestone = _configure_project_with_milestone(tmp_path, monkeypatch, ms)
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    res = applier.apply(plan, milestone, dry_run=True)
    assert not res.errors
    assert f.read_text(encoding="utf-8") == original
    entry = next(a for a in res.actions_applied if a["type"] == "replace_text_in_file")
    assert entry.get("diff")
    assert entry["outcome"] == "changed"


def test_plan_roundtrip_serializes_bounded_actions():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    raw = f"replace_text_in_file examples/r.txt | old{sep}new"
    act = parse_forge_action_line(raw, m)
    plan = ExecutionPlan(milestone_id=1, actions=[act])
    plan2 = ExecutionPlan.from_serializable(plan.to_serializable())
    assert plan2.actions[0].rel_path == "examples/r.txt"
    assert plan2.actions[0].old_text == "old"
    assert plan2.actions[0].new_text == "new"


def test_reviewed_plan_targets_include_bounded_path(tmp_path, monkeypatch):
    from forge.reviewed_plan import target_paths_for_plan

    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    act = parse_forge_action_line(
        f"insert_before_in_file examples/z.txt | a{sep}b", m
    )
    plan = ExecutionPlan(milestone_id=1, actions=[act])
    t = target_paths_for_plan(plan)
    assert any(p.name == "z.txt" for p in t)
