"""Bounded file edit actions: parse, apply, deterministic match failures."""

from __future__ import annotations

import pytest

from forge.design_manager import Milestone, MilestoneService
from forge.execution.apply import ArtifactActionApplier
from forge.execution.file_edits import (
    BoundedMatchOptions,
    apply_insert_after,
    apply_replace_block,
    apply_replace_lines,
    apply_replace_text,
    full_line_spans,
    nonoverlapping_spans,
    normalize_newlines,
)
from forge.execution.models import ExecutionPlan
from forge.execution.parse import FORGE_BOUNDED_EDIT_SEP, parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.text_diff import unified_diff_bounded
from forge.paths import Paths


def test_nonoverlapping_spans_counts():
    assert nonoverlapping_spans("aaa", "aa") == [(0, 2)]
    assert len(nonoverlapping_spans("abab", "ab")) == 2


def test_normalize_newlines_crlf():
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"


def test_apply_insert_after_unique_default_opts():
    t = "one\nTWO\nthree"
    assert (
        apply_insert_after(
            t, "TWO", "X", opts=BoundedMatchOptions()
        )
        == "one\nTWOX\nthree"
    )


def test_apply_insert_after_zero_raises():
    with pytest.raises(ValueError, match="no match"):
        apply_insert_after("abc", "Z", "x", opts=BoundedMatchOptions())


def test_apply_insert_after_ambiguous_raises_when_unique():
    with pytest.raises(ValueError, match="ambiguous"):
        apply_insert_after(
            "xx yy xx", "xx", "!", opts=BoundedMatchOptions(must_be_unique=True)
        )


def test_apply_insert_after_second_occurrence():
    out = apply_insert_after(
        "X\nX\n",
        "X",
        "!",
        opts=BoundedMatchOptions(must_be_unique=False, occurrence=2),
    )
    assert out == "X\nX!\n"


def test_apply_insert_after_occurrence_out_of_range():
    with pytest.raises(ValueError, match="out of range"):
        apply_insert_after(
            "X\n",
            "X",
            "!",
            opts=BoundedMatchOptions(must_be_unique=False, occurrence=3),
        )


def test_apply_replace_text_ambiguous_when_unique():
    with pytest.raises(ValueError, match="ambiguous"):
        apply_replace_text(
            "a OLD b OLD c",
            "OLD",
            "new",
            opts=BoundedMatchOptions(),
        )


def test_apply_replace_text_unique():
    assert (
        apply_replace_text(
            "hello world",
            "world",
            "Forge",
            opts=BoundedMatchOptions(),
        )
        == "hello Forge"
    )


def test_line_match_replace_full_line():
    text = "def a():\n  pass\n"
    out = apply_replace_text(
        text,
        "  pass",
        "  return 1",
        opts=BoundedMatchOptions(line_match=True),
    )
    assert "return 1" in out
    assert out.count("pass") == 0


def test_apply_replace_lines():
    text = "L1\nL2\nL3\n"
    assert apply_replace_lines(text, 2, 2, "NEW") == "L1\nNEW\nL3\n"


def test_apply_replace_lines_delete_range():
    assert apply_replace_lines("a\nb\nc\n", 2, 2, "") == "a\nc\n"


def test_apply_replace_lines_out_of_range():
    with pytest.raises(ValueError, match="invalid"):
        apply_replace_lines("a\nb\n", 5, 5, "x")


def test_replace_block_no_end_raises():
    with pytest.raises(ValueError, match="no match for end"):
        apply_replace_block(
            "START only",
            "START",
            "END",
            "NEW",
            start_opts=BoundedMatchOptions(),
        )


def test_replace_block_ambiguous_start():
    with pytest.raises(ValueError, match="ambiguous"):
        apply_replace_block(
            "START a START b END",
            "START",
            "END",
            "NEW",
            start_opts=BoundedMatchOptions(),
        )


def test_replace_block_success():
    text = "before START mid END after"
    out = apply_replace_block(
        text,
        "START",
        "END",
        "NEW",
        start_opts=BoundedMatchOptions(),
    )
    assert out == "before NEW after"


def test_parse_must_be_unique_conflicts_with_occurrence():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    with pytest.raises(ValueError, match="must_be_unique"):
        parse_forge_action_line(
            f"insert_after_in_file examples/x.txt | a{sep}b | occurrence=2",
            m,
        )


def test_parse_occurrence_with_must_be_unique_false():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    act = parse_forge_action_line(
        f"insert_after_in_file examples/x.txt | a{sep}b | must_be_unique=false occurrence=2",
        m,
    )
    assert act.occurrence == 2
    assert act.must_be_unique is False


def test_parse_replace_lines_in_file():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    act = parse_forge_action_line(
        f"replace_lines_in_file examples/x.txt | 2{sep}3{sep}HELLO", m
    )
    assert act.start_line == 2
    assert act.end_line == 3
    assert act.replacement == "HELLO"


def test_parse_replace_block_three_parts():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    raw = f"replace_block_in_file examples/b.txt | A{sep}B{sep}C | line_match=true"
    act = parse_forge_action_line(raw, m)
    assert act.start_marker == "A"
    assert act.end_marker == "B"
    assert act.new_body == "C"
    assert act.line_match is True


def test_unified_diff_includes_action_hint():
    text, _t = unified_diff_bounded(
        "a\nb\n", "a\nc\n", "f.py", action_hint="replace_text_in_file → f.py"
    )
    assert "forge-action:" in text
    assert "replace_text_in_file" in text


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
    assert "forge-action:" in entry["diff"]
    assert entry["outcome"] == "changed"


def test_integration_replace_lines_and_line_match_add_function(tmp_path, monkeypatch):
    """Realistic: extend an existing Python module with a new function."""
    sep = FORGE_BOUNDED_EDIT_SEP
    mod = tmp_path / "examples" / "app.py"
    mod.parent.mkdir(parents=True, exist_ok=True)
    mod.write_text(
        '"""App module."""\n\ndef existing():\n    return 1\n',
        encoding="utf-8",
    )
    ms = f"""# Milestones

## Milestone 1: Extend app

- **Objective**: Add helper and tweak return
- **Scope**: examples/app.py
- **Validation**: File contains new symbol

- **Forge Actions**:
  - replace_text_in_file examples/app.py |     return 1{sep}    return 2 | line_match=true
  - insert_after_in_file examples/app.py | def existing():{sep}\\n\\ndef new_fn():\\n    return "ok"\\n | line_match=true
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/app.py new_fn
"""
    milestone = _configure_project_with_milestone(tmp_path, monkeypatch, ms)
    plan = ExecutionPlanBuilder.build(milestone)
    res = ArtifactActionApplier(Paths).apply(plan, milestone, dry_run=False)
    assert not res.errors, res.errors
    body = mod.read_text(encoding="utf-8")
    assert "def new_fn():" in body
    assert "return 2" in body


def test_integration_replace_lines_invalid_range(tmp_path, monkeypatch):
    sep = FORGE_BOUNDED_EDIT_SEP
    f = tmp_path / "examples" / "lines.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("a\nb\n", encoding="utf-8")
    ms = f"""# Milestones

## Milestone 1: Bad lines

- **Objective**: x
- **Scope**: y
- **Validation**: z

- **Forge Actions**:
  - replace_lines_in_file examples/lines.txt | 9{sep}9{sep}x
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/lines.txt a
"""
    milestone = _configure_project_with_milestone(tmp_path, monkeypatch, ms)
    plan = ExecutionPlanBuilder.build(milestone)
    res = ArtifactActionApplier(Paths).apply(plan, milestone, dry_run=False)
    assert res.errors
    assert "invalid" in res.errors[0].lower()


def test_plan_roundtrip_serializes_bounded_actions():
    m = Milestone(1, "t", "o", "s", "v")
    sep = FORGE_BOUNDED_EDIT_SEP
    raw = f"replace_text_in_file examples/r.txt | old{sep}new | line_match=true"
    act = parse_forge_action_line(raw, m)
    plan = ExecutionPlan(milestone_id=1, actions=[act])
    plan2 = ExecutionPlan.from_serializable(plan.to_serializable())
    assert plan2.actions[0].rel_path == "examples/r.txt"
    assert plan2.actions[0].old_text == "old"
    assert plan2.actions[0].new_text == "new"
    assert plan2.actions[0].line_match is True


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


def test_full_line_spans_trailing_newline():
    spans = full_line_spans("a\nb\n")
    assert len(spans) == 3
    assert spans[0][2] == "a"
    assert spans[1][2] == "b"
    assert spans[2][2] == ""
