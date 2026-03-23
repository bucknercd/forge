"""
Deterministic enrichment of under-scoped behavioral tasks before planning.

Merges aggregation/transform intent from milestone context, parent milestone
fields, and optional vision text into task objective/summary so planners are
not constrained to read/filter-only slices.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from forge.design_manager import Milestone
from forge.task_ir import (
    MIN_BEHAVIOR_DEPTH_SIGNALS,
    compile_task_to_ir,
    extract_behavior_signals,
    task_ir_has_minimum_behavior_depth,
)
from forge.task_service import Task, list_tasks, save_tasks

_ENRICH_MARKER = "[Forge: enriched behavioral scope from milestone/vision]"

# Deterministic phrases for missing upstream deep-behavior signals.
_DEEP_PHRASES: dict[str, str] = {
    "count": (
        "Count occurrences (e.g. repeated ERROR messages or other duplicates)."
    ),
    "aggregate": "Aggregate or summarize results beyond filtering alone.",
    "group": "Group related entries where the milestone requires it.",
    "sort": "Sort or order results as specified.",
    "top 5": "Produce top-k output (e.g. top 5 most frequent items).",
    "rank": "Rank results by frequency, severity, or other stated criteria.",
    "transform": (
        "Apply meaningful data transformation, not only pass-through filtering."
    ),
}


def _intrinsic_deep_signals(task: Task) -> set[str]:
    blob = "\n".join((task.objective, task.summary)).strip()
    return set(extract_behavior_signals(blob)) & MIN_BEHAVIOR_DEPTH_SIGNALS


def _upstream_intent_blob(
    parent: Milestone, task: Task, vision_text: str | None
) -> str:
    parts = [
        parent.title or "",
        parent.objective or "",
        parent.scope or "",
        parent.validation or "",
        parent.summary or "",
        task.milestone_context or "",
    ]
    if vision_text and vision_text.strip():
        parts.append(vision_text.strip())
    return "\n".join(p for p in parts if str(p).strip())


def _upstream_deep_signals(blob: str) -> set[str]:
    return set(extract_behavior_signals(blob)) & MIN_BEHAVIOR_DEPTH_SIGNALS


def enrich_behavioral_task_if_needed(
    task: Task,
    parent: Milestone,
    *,
    vision_text: str | None = None,
) -> tuple[Task, dict[str, Any]]:
    """
    If the task is behavioral but lacks minimum depth signals in objective/summary,
    enrich from milestone + vision. If still under-scoped, merge full milestone
    objective/validation. Returns (task_to_use, meta). On irrecoverable under-scope,
    returns the **original** task and meta with ``enriched`` False and ``failed`` True.
    """
    meta: dict[str, Any] = {
        "enriched": False,
        "failed": False,
        "phases_tried": [],
        "added_signal_labels": [],
    }
    ir = compile_task_to_ir(task)
    if ir.task_type != "behavioral":
        return task, meta
    if task_ir_has_minimum_behavior_depth(ir):
        return task, meta

    intent_blob = _upstream_intent_blob(parent, task, vision_text)
    upstream_deep = _upstream_deep_signals(intent_blob)
    intrinsic = _intrinsic_deep_signals(task)
    missing = sorted(upstream_deep - intrinsic, key=lambda s: s)

    working = task
    if missing:
        lines = [_DEEP_PHRASES[s] for s in missing if s in _DEEP_PHRASES]
        if lines:
            suffix = (
                f"\n\n{_ENRICH_MARKER}\n"
                "This slice must also satisfy:\n"
                + "\n".join(f"- {ln}" for ln in lines)
            )
            working = replace(
                working,
                objective=(working.objective.rstrip() + suffix).strip(),
            )
            meta["phases_tried"].append("merge_upstream_deep_signals")
            meta["added_signal_labels"] = list(missing)

    ir2 = compile_task_to_ir(working)
    if task_ir_has_minimum_behavior_depth(ir2):
        meta["enriched"] = True
        return working, meta

    # Phase 2: fold full milestone objective/validation into task objective.
    mo = (parent.objective or "").strip()
    mv = (parent.validation or "").strip()
    if mo or mv:
        reg_bits: list[str] = []
        if mo:
            reg_bits.append(f"Milestone objective (full): {mo}")
        if mv:
            reg_bits.append(f"Milestone validation (full): {mv}")
        reg_suffix = "\n\n" + "\n".join(reg_bits)
        block = reg_suffix.strip()
        if block and block not in working.objective:
            working = replace(
                working,
                objective=(working.objective.rstrip() + reg_suffix).strip(),
            )
        meta["phases_tried"].append("merge_full_milestone_objective_validation")

    ir3 = compile_task_to_ir(working)
    if task_ir_has_minimum_behavior_depth(ir3):
        meta["enriched"] = True
        return working, meta

    meta["failed"] = True
    return task, meta


def persist_enriched_task(milestone_id: int, enriched: Task) -> None:
    """Replace one task in the milestone task file and save."""
    tasks = list_tasks(milestone_id)
    if not tasks:
        return
    updated = [
        enriched if t.id == enriched.id else t for t in tasks
    ]
    save_tasks(milestone_id, updated)
