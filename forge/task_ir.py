"""
Task internal representation (TaskIR) and compiler boundary helpers.

This keeps raw task/milestone text formats intact while providing a strict,
deterministic semantic layer for planning and plan-quality checks.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
import re
from typing import Any

from forge.execution.models import (
    ActionAddDecision,
    ActionAppendSection,
    ActionInsertAfterInFile,
    ActionInsertBeforeInFile,
    ActionMarkMilestoneCompleted,
    ActionReplaceBlockInFile,
    ActionReplaceLinesInFile,
    ActionReplaceSection,
    ActionReplaceTextInFile,
    ActionWriteFile,
    ExecutionPlan,
    ForgeAction,
)


TaskType = str  # behavioral | structural | documentation | unknown

# Public: used by task shaping / enrichment to align with depth checks.
MIN_BEHAVIOR_DEPTH_SIGNALS: frozenset[str] = frozenset(
    {
        "count",
        "aggregate",
        "transform",
        "group",
        "sort",
        "top 5",
        "rank",
    }
)

_BEHAVIOR_SIGNAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcount(?:ing)?\b", "count"),
    (r"\bfilter(?:ing)?\b", "filter"),
    (r"\bignore\b", "ignore"),
    (r"\bparse(?:r|d|s|ing)?\b", "parse"),
    (r"\baggregate|aggregation\b", "aggregate"),
    (r"\bsummari[sz]e|summary\b", "summarize"),
    (r"\bgroup(?:ing)?\b", "group"),
    (r"\bsort(?:ed|ing)?\b", "sort"),
    (r"\btop[\s-]*5\b", "top 5"),
    (r"\brank(?:ing|ed)?\b", "rank"),
    (r"\btransform(?:ation|ed|ing)?\b", "transform"),
)

_DOC_HINTS = (
    "documentation",
    "docs",
    "readme",
    "architecture",
    "decision",
    "changelog",
)

_STRUCTURAL_HINTS = (
    "scaffold",
    "boilerplate",
    "create file",
    "entrypoint",
    "skeleton",
    "setup",
)


@dataclass(frozen=True)
class TaskIR:
    milestone_id: int
    task_id: int
    summary: str
    objective: str
    requirements: list[str]
    validations: list[str]
    task_type: TaskType
    behavior_signals: list[str]
    has_embedded_actions: bool
    embedded_actions: list[str]
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split_normalized_lines(text: str) -> list[str]:
    if not text.strip():
        return []
    out: list[str] = []
    for line in re.split(r"[\n;]+", text):
        item = line.strip().lstrip("-").strip()
        if item:
            out.append(item)
    return out


def extract_behavior_signals(*texts: str) -> list[str]:
    blob = "\n".join(t for t in texts if t).lower()
    signals: list[str] = []
    for pat, label in _BEHAVIOR_SIGNAL_PATTERNS:
        if re.search(pat, blob):
            signals.append(label)
    return sorted(set(signals))


def classify_task_type(
    *,
    summary: str,
    objective: str,
    requirements: list[str],
    validations: list[str],
    has_embedded_actions: bool,
) -> TaskType:
    req_blob = "\n".join(requirements).lower()
    val_blob = "\n".join(validations).lower()
    blob = f"{summary}\n{objective}\n{req_blob}\n{val_blob}".lower()
    behavior = extract_behavior_signals(summary, objective, req_blob, val_blob)
    if behavior:
        return "behavioral"
    if any(h in blob for h in _DOC_HINTS) and not has_embedded_actions:
        return "documentation"
    if any(h in blob for h in _STRUCTURAL_HINTS):
        return "structural"
    if has_embedded_actions:
        return "structural"
    return "unknown"


def compile_task_to_ir(task: Any) -> TaskIR:
    summary = str(getattr(task, "summary", "") or "").strip()
    objective = str(getattr(task, "objective", "") or "").strip()
    validation_text = str(getattr(task, "validation", "") or "").strip()
    forge_validation = [str(v).strip() for v in (getattr(task, "forge_validation", []) or []) if str(v).strip()]
    validations = forge_validation if forge_validation else _split_normalized_lines(validation_text)

    requirements: list[str] = []
    requirements.extend(_split_normalized_lines(objective))
    if summary and summary not in requirements:
        requirements.extend(_split_normalized_lines(summary))

    embedded_actions = [str(a).strip() for a in (getattr(task, "forge_actions", []) or []) if str(a).strip()]
    has_embedded_actions = bool(embedded_actions)
    milestone_context = str(getattr(task, "milestone_context", "") or "").strip()
    milestone_ctx_lines = _split_normalized_lines(milestone_context)
    behavior_signals = extract_behavior_signals(
        summary, objective, *requirements, *validations, *milestone_ctx_lines
    )
    task_type = classify_task_type(
        summary=summary,
        objective=objective,
        requirements=requirements + milestone_ctx_lines,
        validations=validations,
        has_embedded_actions=has_embedded_actions,
    )

    return TaskIR(
        milestone_id=int(getattr(task, "milestone_id")),
        task_id=int(getattr(task, "id")),
        summary=summary,
        objective=objective,
        requirements=requirements,
        validations=validations,
        task_type=task_type,
        behavior_signals=behavior_signals,
        has_embedded_actions=has_embedded_actions,
        embedded_actions=embedded_actions,
        source_metadata={
            "task_title": str(getattr(task, "title", "") or ""),
            "raw_validation": validation_text,
            "forge_validation_count": len(forge_validation),
            "embedded_action_count": len(embedded_actions),
            "milestone_context": milestone_context,
        },
    )


def _is_substantive_action(a: ForgeAction) -> bool:
    if isinstance(a, (ActionMarkMilestoneCompleted, ActionAddDecision)):
        return False
    if isinstance(a, (ActionAppendSection, ActionReplaceSection)):
        return False
    if isinstance(
        a,
        (
            ActionWriteFile,
            ActionInsertAfterInFile,
            ActionInsertBeforeInFile,
            ActionReplaceTextInFile,
            ActionReplaceBlockInFile,
            ActionReplaceLinesInFile,
        ),
    ):
        rel = str(getattr(a, "rel_path", "")).replace("\\", "/")
        if rel.startswith(("src/", "scripts/", "examples/", "infra/")):
            return True
        if rel.startswith("tests/") and isinstance(a, ActionWriteFile):
            body = str(getattr(a, "body", "") or "").lower()
            if "pass\n" in body or "todo" in body or "placeholder" in body:
                return False
            return True
        return False
    return True


def plan_is_substantive_for_task(task_ir: TaskIR, plan: ExecutionPlan) -> bool:
    actions = list(plan.actions or [])
    substantive = [_is_substantive_action(a) for a in actions]
    has_substantive = any(substantive)
    source_impl = False
    for a in actions:
        rel = str(getattr(a, "rel_path", "")).replace("\\", "/")
        if rel.startswith(("src/", "scripts/", "examples/", "infra/")):
            source_impl = True
            break
    if task_ir.task_type == "behavioral":
        # Early behavioral tasks must include real source implementation, not only
        # sample data/tests/docs/meta actions.
        if int(task_ir.task_id or 0) in (1, 2):
            return has_substantive and source_impl
        return has_substantive
    if task_ir.task_type == "documentation":
        return any(not isinstance(a, ActionMarkMilestoneCompleted) for a in actions)
    if task_ir.task_type == "structural":
        # Structural tasks are intentionally less strict (incremental scaffolding allowed).
        return True
    return True


def task_ir_has_minimum_behavior_depth(task_ir: TaskIR) -> bool:
    """
    Behavioral tasks must carry at least one deeper behavior signal so planning
    is not constrained to read/filter-only slices.
    """
    if task_ir.task_type != "behavioral":
        return True
    intrinsic_signals = extract_behavior_signals(
        task_ir.objective,
        task_ir.summary,
        *task_ir.requirements,
    )
    return bool(set(intrinsic_signals) & MIN_BEHAVIOR_DEPTH_SIGNALS)
