"""LLM planner boundary normalization (append_section / replace_section near-misses)."""

from __future__ import annotations

import json

import pytest

from forge.design_manager import Milestone, MilestoneService
from forge.execution.models import ActionAppendSection, ActionReplaceSection
from forge.execution.parse import parse_forge_action_line
from forge.paths import Paths
from forge.planner import LLMPlanner
from forge.planner_normalize import (
    normalize_llm_planner_action_line,
    persist_llm_planner_raw_on_failure,
)
from tests.forge_test_project import configure_project
from tests.test_planner_abstraction import FakeLLM


def test_normalize_repairs_append_section_missing_heading_when_body_starts_with_h2():
    raw = (
        "append_section requirements | ## Log File Reading and Counting\n"
        "- Bullet one\n"
        "- Bullet two\n"
    )
    canonical, notes = normalize_llm_planner_action_line(raw)
    assert "Repaired missing" in notes[0]
    assert canonical.startswith("append_section requirements Log File Reading and Counting |")
    assert "- Bullet one" in canonical
    m = Milestone(1, "t", "o", "s", "v")
    act = parse_forge_action_line(canonical, m)
    assert isinstance(act, ActionAppendSection)
    assert act.target == "requirements"
    assert act.section_heading == "Log File Reading and Counting"
    assert "- Bullet one" in act.body


def test_normalize_repairs_replace_section_same_shape():
    raw = "replace_section architecture | ## Design Notes\nDetails here.\n"
    canonical, notes = normalize_llm_planner_action_line(raw)
    assert notes
    assert canonical.startswith("replace_section architecture Design Notes |")
    assert "Details here." in canonical
    m = Milestone(1, "t", "o", "s", "v")
    act = parse_forge_action_line(canonical, m)
    assert isinstance(act, ActionReplaceSection)
    assert act.section_heading == "Design Notes"


def test_normalize_leaves_valid_append_section_unchanged():
    raw = "append_section requirements Overview | Hello\n"
    canonical, notes = normalize_llm_planner_action_line(raw)
    assert canonical == raw
    assert notes == []


def test_normalize_ambiguous_append_section_rejected_not_guessed():
    raw = "append_section requirements | Plain prose without markdown heading."
    with pytest.raises(ValueError) as exc:
        normalize_llm_planner_action_line(raw)
    assert "Bad action" in str(exc.value) or "markdown" in str(exc.value).lower()


def test_normalize_ambiguous_empty_body_after_pipe():
    raw = "append_section requirements | "
    with pytest.raises(ValueError):
        normalize_llm_planner_action_line(raw)


def test_normalize_rejects_h3_not_h2():
    raw = "append_section requirements | ### Almost\nbody"
    with pytest.raises(ValueError) as exc:
        normalize_llm_planner_action_line(raw)
    assert "Bad action" in str(exc.value)


def test_canonical_line_stable_typed_parse_matches_direct_valid_form():
    m = Milestone(1, "t", "o", "s", "v")
    repaired, _ = normalize_llm_planner_action_line(
        "append_section requirements | ## My Section\n\ncontent\n"
    )
    direct = "append_section requirements My Section | \n\ncontent\n"
    a1 = parse_forge_action_line(repaired, m)
    a2 = parse_forge_action_line(direct, m)
    assert isinstance(a1, ActionAppendSection)
    assert isinstance(a2, ActionAppendSection)
    assert a1.target == a2.target == "requirements"
    assert a1.section_heading == a2.section_heading == "My Section"
    assert a1.body.strip() == a2.body.strip() == "content"


def test_llm_planner_metadata_includes_normalization_notes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: N
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    bad = (
        "append_section requirements | ## Inferred Title\n"
        "- x\n"
    )
    llm = FakeLLM(json.dumps({"actions": [bad, "mark_milestone_completed"]}))
    planner = LLMPlanner(llm)
    plan = planner.build_plan(MilestoneService.get_milestone(1))
    assert plan.actions
    meta = planner.metadata()
    assert meta.get("normalization_notes")
    assert "Inferred" in meta["normalization_notes"][0] or "Repaired" in meta["normalization_notes"][0]


def test_llm_planner_persists_raw_output_on_parse_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: F
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    raw_json = json.dumps({"actions": ["append_section requirements | not a heading", "x"]})
    llm = FakeLLM(raw_json)
    planner = LLMPlanner(llm, fallback_to_milestone_actions=False)
    with pytest.raises(ValueError):
        planner.build_plan(MilestoneService.get_milestone(1))
    fail_dir = Paths.SYSTEM_DIR / "results" / "llm_planner_failures"
    assert fail_dir.is_dir()
    files = list(fail_dir.glob("m1_*.txt"))
    assert files
    text = files[-1].read_text(encoding="utf-8")
    assert raw_json in text
    assert "reason:" in text


def test_persist_llm_planner_raw_on_failure_returns_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    p = persist_llm_planner_raw_on_failure("oops", 2, reason="test")
    assert p is not None
    assert p.exists()
    assert "oops" in p.read_text(encoding="utf-8")


def test_llm_planner_sloppy_append_then_apply_roundtrip(tmp_path, monkeypatch):
    """After normalization, reviewed plan apply uses canonical actions only."""
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: R
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    from forge.executor import Executor

    sloppy = (
        "append_section requirements | ## Roundtrip Section\n"
        "RT_BODY\n"
    )
    llm = FakeLLM(json.dumps({"actions": [sloppy, "mark_milestone_completed"]}))
    planner = LLMPlanner(llm)
    preview = Executor.save_reviewed_plan_for_task(1, 1, planner=planner)
    assert preview["ok"]
    plan_id = preview["plan_id"]
    applied = Executor.apply_reviewed_plan(plan_id)
    assert applied["ok"]
    assert "RT_BODY" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")


def test_llm_planner_repair_deterministic_same_input_same_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: D
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    raw = json.dumps(
        {
            "actions": [
                "append_section requirements | ## D\nline\n",
                "mark_milestone_completed",
            ]
        }
    )
    m = MilestoneService.get_milestone(1)
    p1 = LLMPlanner(FakeLLM(raw)).build_plan(m)
    p2 = LLMPlanner(FakeLLM(raw)).build_plan(m)
    assert p1.to_serializable() == p2.to_serializable()
