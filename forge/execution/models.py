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


@dataclass(frozen=True)
class ActionInsertAfterInFile:
    """
    Insert after anchor. Substring mode: after matched substring end.
    line_match: anchor must equal a full line's content (newlines normalized to \\n).
    must_be_unique: require exactly one match; else use occurrence (1-based).
    """

    rel_path: str
    anchor: str
    insertion: str
    occurrence: int = 1
    must_be_unique: bool = True
    line_match: bool = False


@dataclass(frozen=True)
class ActionInsertBeforeInFile:
    """Insert before anchor (substring or full-line match)."""

    rel_path: str
    anchor: str
    insertion: str
    occurrence: int = 1
    must_be_unique: bool = True
    line_match: bool = False


@dataclass(frozen=True)
class ActionReplaceTextInFile:
    """Replace one occurrence of old_text (substring or full line) with new_text."""

    rel_path: str
    old_text: str
    new_text: str
    occurrence: int = 1
    must_be_unique: bool = True
    line_match: bool = False


@dataclass(frozen=True)
class ActionReplaceBlockInFile:
    """
    Replace from start of start region through end of end_marker (inclusive).
    Start uses substring or full-line rules; end_marker is always a substring
    found after the start region.
    """

    rel_path: str
    start_marker: str
    end_marker: str
    new_body: str
    occurrence: int = 1
    must_be_unique: bool = True
    line_match: bool = False


@dataclass(frozen=True)
class ActionReplaceLinesInFile:
    """Replace inclusive 1-based line range [start_line, end_line] with replacement lines."""

    rel_path: str
    start_line: int
    end_line: int
    replacement: str


ForgeAction = Union[
    ActionAppendSection,
    ActionReplaceSection,
    ActionAddDecision,
    ActionMarkMilestoneCompleted,
    ActionWriteFile,
    ActionInsertAfterInFile,
    ActionInsertBeforeInFile,
    ActionReplaceTextInFile,
    ActionReplaceBlockInFile,
    ActionReplaceLinesInFile,
]


@dataclass
class ExecutionPlan:
    milestone_id: int
    actions: list[ForgeAction] = field(default_factory=list)
    """When set, this plan was built from a task under :attr:`milestone_id` (parent milestone)."""

    task_id: int | None = None

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
            elif isinstance(a, ActionInsertAfterInFile):
                out.append(
                    {
                        "type": "insert_after_in_file",
                        "rel_path": a.rel_path,
                        "anchor": a.anchor,
                        "insertion": a.insertion,
                        "occurrence": a.occurrence,
                        "must_be_unique": a.must_be_unique,
                        "line_match": a.line_match,
                    }
                )
            elif isinstance(a, ActionInsertBeforeInFile):
                out.append(
                    {
                        "type": "insert_before_in_file",
                        "rel_path": a.rel_path,
                        "anchor": a.anchor,
                        "insertion": a.insertion,
                        "occurrence": a.occurrence,
                        "must_be_unique": a.must_be_unique,
                        "line_match": a.line_match,
                    }
                )
            elif isinstance(a, ActionReplaceTextInFile):
                out.append(
                    {
                        "type": "replace_text_in_file",
                        "rel_path": a.rel_path,
                        "old_text": a.old_text,
                        "new_text": a.new_text,
                        "occurrence": a.occurrence,
                        "must_be_unique": a.must_be_unique,
                        "line_match": a.line_match,
                    }
                )
            elif isinstance(a, ActionReplaceBlockInFile):
                out.append(
                    {
                        "type": "replace_block_in_file",
                        "rel_path": a.rel_path,
                        "start_marker": a.start_marker,
                        "end_marker": a.end_marker,
                        "new_body": a.new_body,
                        "occurrence": a.occurrence,
                        "must_be_unique": a.must_be_unique,
                        "line_match": a.line_match,
                    }
                )
            elif isinstance(a, ActionReplaceLinesInFile):
                out.append(
                    {
                        "type": "replace_lines_in_file",
                        "rel_path": a.rel_path,
                        "start_line": a.start_line,
                        "end_line": a.end_line,
                        "replacement": a.replacement,
                    }
                )
        body: dict[str, Any] = {"milestone_id": self.milestone_id, "actions": out}
        if self.task_id is not None:
            body["task_id"] = self.task_id
        return body

    @staticmethod
    def from_serializable(data: dict[str, Any]) -> "ExecutionPlan":
        milestone_id = int(data.get("milestone_id"))
        raw_tid = data.get("task_id")
        task_id = int(raw_tid) if raw_tid is not None else None
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
            elif t == "insert_after_in_file":
                actions.append(
                    ActionInsertAfterInFile(
                        rel_path=item["rel_path"],
                        anchor=item["anchor"],
                        insertion=item["insertion"],
                        occurrence=int(item.get("occurrence", 1)),
                        must_be_unique=bool(item.get("must_be_unique", True)),
                        line_match=bool(item.get("line_match", False)),
                    )
                )
            elif t == "insert_before_in_file":
                actions.append(
                    ActionInsertBeforeInFile(
                        rel_path=item["rel_path"],
                        anchor=item["anchor"],
                        insertion=item["insertion"],
                        occurrence=int(item.get("occurrence", 1)),
                        must_be_unique=bool(item.get("must_be_unique", True)),
                        line_match=bool(item.get("line_match", False)),
                    )
                )
            elif t == "replace_text_in_file":
                actions.append(
                    ActionReplaceTextInFile(
                        rel_path=item["rel_path"],
                        old_text=item["old_text"],
                        new_text=item["new_text"],
                        occurrence=int(item.get("occurrence", 1)),
                        must_be_unique=bool(item.get("must_be_unique", True)),
                        line_match=bool(item.get("line_match", False)),
                    )
                )
            elif t == "replace_block_in_file":
                actions.append(
                    ActionReplaceBlockInFile(
                        rel_path=item["rel_path"],
                        start_marker=item["start_marker"],
                        end_marker=item["end_marker"],
                        new_body=item["new_body"],
                        occurrence=int(item.get("occurrence", 1)),
                        must_be_unique=bool(item.get("must_be_unique", True)),
                        line_match=bool(item.get("line_match", False)),
                    )
                )
            elif t == "replace_lines_in_file":
                actions.append(
                    ActionReplaceLinesInFile(
                        rel_path=item["rel_path"],
                        start_line=int(item["start_line"]),
                        end_line=int(item["end_line"]),
                        replacement=item["replacement"],
                    )
                )
            else:
                raise ValueError(f"Unknown action type in stored plan: {t!r}")
        return ExecutionPlan(milestone_id=milestone_id, actions=actions, task_id=task_id)


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
