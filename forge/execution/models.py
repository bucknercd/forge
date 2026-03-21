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


@dataclass(frozen=True)
class ActionWriteFile:
    """Write or replace a bounded repo-relative file (full body)."""

    rel_path: str
    body: str


ForgeAction = Union[
    ActionAppendSection,
    ActionReplaceSection,
    ActionAddDecision,
    ActionMarkMilestoneCompleted,
    ActionWriteFile,
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
            elif isinstance(a, ActionWriteFile):
                out.append(
                    {
                        "type": "write_file",
                        "rel_path": a.rel_path,
                        "body": a.body,
                    }
                )
        return {"milestone_id": self.milestone_id, "actions": out}

    @staticmethod
    def from_serializable(data: dict[str, Any]) -> "ExecutionPlan":
        milestone_id = int(data.get("milestone_id"))
        actions_raw = data.get("actions", [])
        actions: list[ForgeAction] = []
        for item in actions_raw:
            t = item.get("type")
            if t == "append_section":
                actions.append(
                    ActionAppendSection(
                        target=item["target"],
                        section_heading=item["section_heading"],
                        body=item["body"],
                    )
                )
            elif t == "replace_section":
                actions.append(
                    ActionReplaceSection(
                        target=item["target"],
                        section_heading=item["section_heading"],
                        body=item["body"],
                    )
                )
            elif t == "add_decision":
                actions.append(
                    ActionAddDecision(
                        title=item["title"],
                        context=item["context"],
                        decision=item["decision"],
                        rationale=item["rationale"],
                    )
                )
            elif t == "mark_milestone_completed":
                actions.append(ActionMarkMilestoneCompleted())
            elif t == "write_file":
                actions.append(
                    ActionWriteFile(rel_path=item["rel_path"], body=item["body"])
                )
            else:
                raise ValueError(f"Unknown action type in stored plan: {t!r}")
        return ExecutionPlan(milestone_id=milestone_id, actions=actions)


@dataclass
class ApplyResult:
    files_changed: list[Path] = field(default_factory=list)
    actions_applied: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def normalized_files_changed(self) -> list[str]:
        return sorted({str(p) for p in self.files_changed})

    def human_summary(self) -> str:
        """One-line summary of per-action outcomes and touched artifact paths."""
        if not self.actions_applied:
            return "No actions recorded."
        counts: dict[str, int] = {"changed": 0, "skipped": 0, "failed": 0}
        paths: list[str] = []
        for a in self.actions_applied:
            o = a.get("outcome", "unknown")
            if o in counts:
                counts[o] += 1
            if o == "changed" and a.get("path"):
                paths.append(str(a["path"]))
        uniq = sorted(set(paths))
        path_part = ", ".join(uniq) if uniq else "—"
        failed = counts["failed"]
        fail_part = f", {failed} failed" if failed else ""
        return (
            f"{counts['changed']} changed, {counts['skipped']} skipped{fail_part}; "
            f"artifacts: {path_part}"
        )
