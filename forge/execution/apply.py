"""Apply ExecutionPlan actions to on-disk design artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from forge.decision_tracker import DecisionTracker
from forge.design_manager import DesignManager, Milestone
from forge.execution.models import (
    ActionAddDecision,
    ActionAppendSection,
    ActionMarkMilestoneCompleted,
    ActionReplaceSection,
    ApplyResult,
    ExecutionPlan,
)
from forge.execution.section_ops import (
    append_to_section,
    insert_milestone_forge_status_completed,
    replace_section_body,
)
from forge.execution.text_diff import unified_diff_bounded
from forge.models import Decision


def _action_type_name(action: Any) -> str:
    if isinstance(action, ActionAppendSection):
        return "append_section"
    if isinstance(action, ActionReplaceSection):
        return "replace_section"
    if isinstance(action, ActionAddDecision):
        return "add_decision"
    if isinstance(action, ActionMarkMilestoneCompleted):
        return "mark_milestone_completed"
    return type(action).__name__


class ArtifactActionApplier:
    """Deterministic file updates only (stdlib + project Paths)."""

    def __init__(self, paths_mod) -> None:
        self._paths = paths_mod

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self._paths.BASE_DIR.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _resolve(self, target: str) -> Path:
        mapping = {
            "requirements": self._paths.REQUIREMENTS_FILE,
            "architecture": self._paths.ARCHITECTURE_FILE,
            "decisions": self._paths.DECISIONS_FILE,
            "milestones": self._paths.MILESTONES_FILE,
        }
        return mapping[target]

    def apply(self, plan: ExecutionPlan, milestone: Milestone) -> ApplyResult:
        result = ApplyResult()
        for action in plan.actions:
            try:
                self._apply_one(action, milestone, result)
            except Exception as exc:  # noqa: BLE001 — surface as execution error string
                err = str(exc)
                result.errors.append(err)
                result.actions_applied.append(
                    {
                        "type": _action_type_name(action),
                        "outcome": "failed",
                        "error": err,
                    }
                )
                break
        return result

    def _append_file_record(
        self,
        result: ApplyResult,
        *,
        action_type: str,
        path: Path,
        before: str,
        after: str,
        changed: bool,
        extra: dict[str, Any],
    ) -> None:
        rel = self._rel(path)
        entry: dict[str, Any] = {
            "type": action_type,
            "outcome": "changed" if changed else "skipped",
            "path": rel,
            **extra,
        }
        if changed and before != after:
            diff_text, truncated = unified_diff_bounded(before, after, rel)
            entry["diff"] = diff_text
            entry["diff_truncated"] = truncated
        else:
            entry["diff"] = None
            entry["diff_truncated"] = False
        result.actions_applied.append(entry)

    def _apply_one(self, action: Any, milestone: Milestone, result: ApplyResult) -> None:
        if isinstance(action, ActionAppendSection):
            path = self._resolve(action.target)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# {action.target.title()}\n\n", encoding="utf-8")
            before = DesignManager.load_document(path)
            new_content, changed = append_to_section(
                content=before,
                section_heading=action.section_heading,
                body=action.body,
            )
            if changed:
                DesignManager.save_document(path, new_content)
                result.files_changed.append(path)
            self._append_file_record(
                result,
                action_type="append_section",
                path=path,
                before=before,
                after=new_content if changed else before,
                changed=changed,
                extra={
                    "target": action.target,
                    "section_heading": action.section_heading,
                },
            )
            return

        if isinstance(action, ActionReplaceSection):
            path = self._resolve(action.target)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# {action.target.title()}\n\n", encoding="utf-8")
            before = DesignManager.load_document(path)
            new_content, changed = replace_section_body(
                content=before,
                section_heading=action.section_heading,
                body=action.body,
            )
            if changed:
                DesignManager.save_document(path, new_content)
                result.files_changed.append(path)
            self._append_file_record(
                result,
                action_type="replace_section",
                path=path,
                before=before,
                after=new_content if changed else before,
                changed=changed,
                extra={
                    "target": action.target,
                    "section_heading": action.section_heading,
                },
            )
            return

        if isinstance(action, ActionAddDecision):
            path = self._paths.DECISIONS_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            before = path.read_text(encoding="utf-8") if path.exists() else ""
            decision = Decision(
                title=action.title,
                context=action.context,
                decision=action.decision,
                rationale=action.rationale,
                timestamp=datetime.now(),
            )
            DecisionTracker.append_decision(decision)
            after = path.read_text(encoding="utf-8")
            changed = before != after
            result.files_changed.append(path)
            self._append_file_record(
                result,
                action_type="add_decision",
                path=path,
                before=before,
                after=after,
                changed=changed,
                extra={"title": action.title},
            )
            return

        if isinstance(action, ActionMarkMilestoneCompleted):
            path = self._paths.MILESTONES_FILE
            before = DesignManager.load_document(path)
            new_content, changed = insert_milestone_forge_status_completed(
                content=before,
                milestone_id=milestone.id,
            )
            if changed:
                DesignManager.save_document(path, new_content)
                result.files_changed.append(path)
            self._append_file_record(
                result,
                action_type="mark_milestone_completed",
                path=path,
                before=before,
                after=new_content if changed else before,
                changed=changed,
                extra={},
            )
            return

        raise TypeError(f"Unsupported action: {type(action)!r}")
