"""Deterministic behavioral task enrichment before planning."""

from __future__ import annotations

from forge.design_manager import Milestone
from forge.task_behavior_enrichment import enrich_behavioral_task_if_needed
from forge.task_ir import compile_task_to_ir, task_ir_has_minimum_behavior_depth
from forge.task_service import Task


def _parent(
    *,
    objective: str,
    validation: str = "",
    scope: str = "",
) -> Milestone:
    return Milestone(
        id=1,
        title="## Milestone 1: Logcheck",
        objective=objective,
        scope=scope or "src/ and tests/",
        validation=validation,
        summary="",
        depends_on=[],
        forge_actions=[],
        forge_validation=[],
    )


def test_enrich_merges_count_and_top_from_milestone_for_filter_only_task():
    parent = _parent(
        objective="Parse logs, count repeated ERROR lines, ignore INFO/DEBUG, output top 5.",
        validation="verify counting and top-k behavior",
    )
    task = Task(
        id=1,
        milestone_id=1,
        title="Read and filter logs",
        objective="Read log file and filter out INFO and DEBUG lines.",
        summary="Initial parse and filter slice.",
        depends_on=[],
        validation="filtering works",
        done_when="done",
        status="not_started",
        milestone_context=(
            "objective: Parse logs, count repeated ERROR lines, output top 5.\n"
            "validation: aggregation and top-k\n"
        ),
        forge_actions=[],
        forge_validation=[],
    )
    enriched, meta = enrich_behavioral_task_if_needed(task, parent, vision_text=None)
    assert meta.get("enriched") is True
    assert meta.get("failed") is False
    ir = compile_task_to_ir(enriched)
    assert task_ir_has_minimum_behavior_depth(ir) is True
    low = enriched.objective.lower()
    assert "count" in low
    assert enriched.forge_actions == []


def test_enrich_uses_vision_when_milestone_objective_shallow():
    parent = _parent(
        objective="Implement log review CLI.",
        validation="tests pass",
    )
    task = Task(
        id=1,
        milestone_id=1,
        title="Filter logs",
        objective="Read lines and filter INFO/DEBUG.",
        summary="Filter-only.",
        depends_on=[],
        validation="v",
        done_when="d",
        status="not_started",
        milestone_context="",
        forge_actions=[],
        forge_validation=[],
    )
    vision = (
        "The tool must count repeated ERROR messages and print the top 5 most frequent."
    )
    enriched, meta = enrich_behavioral_task_if_needed(
        task, parent, vision_text=vision
    )
    assert meta.get("enriched") is True
    ir = compile_task_to_ir(enriched)
    assert task_ir_has_minimum_behavior_depth(ir) is True
    assert enriched.forge_actions == []


def test_enrich_still_fails_when_no_upstream_depth_anywhere():
    parent = _parent(
        objective="Add a file and run tests.",
        validation="file exists",
    )
    task = Task(
        id=1,
        milestone_id=1,
        title="Read file",
        objective="Read and filter lines from input.",
        summary="Filter slice.",
        depends_on=[],
        validation="v",
        done_when="d",
        status="not_started",
        milestone_context="",
        forge_actions=[],
        forge_validation=[],
    )
    # Behavioral from parse+filter but no deep signals anywhere upstream.
    enriched, meta = enrich_behavioral_task_if_needed(task, parent, vision_text="")
    assert meta.get("enriched") is False
    assert meta.get("failed") is True
    assert enriched.objective == task.objective
