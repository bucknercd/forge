from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Union


@dataclass(frozen=True)
class ActionAppendSection:
    target: Literal["requirements", "architecture", "decisions", "milestones"]
    section_heading: str
    body: str


@dataclass(frozen=True)
class ActionReplaceSection:
    target: Literal["requirements", "architecture", "decisions", "milestones"]
    section_heading: str
    body: str


@dataclass(frozen=True)
class ActionAddDecision:
    title: str
    context: str
    decision: str
    rationale: str


@dataclass(frozen=True)
class ActionMarkMilestoneCompleted:
    """Insert a visible completion marker into docs/milestones.md for this milestone."""

    pass


ForgeAction = Union[
    ActionAppendSection,
    ActionReplaceSection,
    ActionAddDecision,
    ActionMarkMilestoneCompleted,
]


@dataclass
class ExecutionPlan:
    milestone_id: int
    actions: list[ForgeAction] = field(default_factory=list)

    def to_serializable(self) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for a in self.actions:
            if isinstance(a, ActionAppendSection):
                out.append(
                    {
                        "type": "append_section",
                        "target": a.target,
                        "section_heading": a.section_heading,
                        "body": a.body,
                    }
                )
            elif isinstance(a, ActionReplaceSection):
                out.append(
                    {
                        "type": "replace_section",
                        "target": a.target,
                        "section_heading": a.section_heading,
                        "body": a.body,
                    }
                )
            elif isinstance(a, ActionAddDecision):
                out.append(
                    {
                        "type": "add_decision",
                        "title": a.title,
                        "context": a.context,
                        "decision": a.decision,
                        "rationale": a.rationale,
                    }
                )
            elif isinstance(a, ActionMarkMilestoneCompleted):
                out.append({"type": "mark_milestone_completed"})
        return {"milestone_id": self.milestone_id, "actions": out}


@dataclass
class ApplyResult:
    files_changed: list[Path] = field(default_factory=list)
    actions_applied: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def normalized_files_changed(self) -> list[str]:
        return sorted({str(p) for p in self.files_changed})
