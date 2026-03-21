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
    ActionWriteFile,
    ApplyResult,
    ExecutionPlan,
)
from forge.execution.safe_paths import resolve_safe_project_path
from forge.execution.section_ops import (
    append_to_section,
    insert_milestone_forge_status_completed,
    replace_section_body,
)
from forge.execution.text_diff import unified_diff_bounded
from forge.models import Decision
from forge.run_events import ACTION_APPLIED, as_emitter


def _action_type_name(action: Any) -> str:
    if isinstance(action, ActionAppendSection):
        return "append_section"
    if isinstance(action, ActionReplaceSection):
        return "replace_section"
    if isinstance(action, ActionAddDecision):
        return "add_decision"
    if isinstance(action, ActionMarkMilestoneCompleted):
        return "mark_milestone_completed"
    if isinstance(action, ActionWriteFile):
        return "write_file"
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

    def apply(
        self,
        plan: ExecutionPlan,
        milestone: Milestone,
        *,
        dry_run: bool = False,
        event_bus: Any = None,
    ) -> ApplyResult:
        bus = as_emitter(event_bus)
        result = ApplyResult()
        for action in plan.actions:
            try:
                self._apply_one(
                    action, milestone, result, dry_run=dry_run, event_bus=bus
                )
            except Exception as exc:  # noqa: BLE001 — surface as execution error string
                err = str(exc)
                result.errors.append(err)
                fail_entry = {
                    "type": _action_type_name(action),
                    "outcome": "failed",
                    "error": err,
                }
                result.actions_applied.append(fail_entry)
                bus.emit(
                    ACTION_APPLIED,
                    action_type=fail_entry["type"],
                    target_path=fail_entry.get("path"),
                    outcome="failed",
                    error=err,
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
        event_bus: Any = None,
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
        bus = as_emitter(event_bus)
        bus.emit(
            ACTION_APPLIED,
            action_type=entry["type"],
            target_path=entry.get("path"),
            outcome=entry["outcome"],
            error=entry.get("error"),
        )

    def _apply_one(
        self,
        action: Any,
        milestone: Milestone,
        result: ApplyResult,
        *,
        dry_run: bool,
        event_bus: Any = None,
    ) -> None:
        if isinstance(action, ActionAppendSection):
            path = self._resolve(action.target)
            default_header = f"# {action.target.title()}\n\n"
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text(default_header, encoding="utf-8")
            before = (
                DesignManager.load_document(path)
                if path.exists()
                else default_header
            )
            new_content, changed = append_to_section(
                content=before,
                section_heading=action.section_heading,
                body=action.body,
            )
            if changed:
                if not dry_run:
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
                event_bus=event_bus,
            )
            return

        if isinstance(action, ActionReplaceSection):
            path = self._resolve(action.target)
            default_header = f"# {action.target.title()}\n\n"
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text(default_header, encoding="utf-8")
            before = (
                DesignManager.load_document(path)
                if path.exists()
                else default_header
            )
            new_content, changed = replace_section_body(
                content=before,
                section_heading=action.section_heading,
                body=action.body,
            )
            if changed:
                if not dry_run:
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
                event_bus=event_bus,
            )
            return

        if isinstance(action, ActionAddDecision):
            path = self._paths.DECISIONS_FILE
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
            before = path.read_text(encoding="utf-8") if path.exists() else ""
            if dry_run:
                ts = "PREVIEW_TIMESTAMP"
                entry = (
                    f"## {action.title}\n"
                    f"- **Context**: {action.context}\n"
                    f"- **Decision**: {action.decision}\n"
                    f"- **Rationale**: {action.rationale}\n"
                    f"- **Timestamp**: {ts}\n"
                )
                after = before + entry
            else:
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
            if changed:
                result.files_changed.append(path)
            self._append_file_record(
                result,
                action_type="add_decision",
                path=path,
                before=before,
                after=after,
                changed=changed,
                extra={"title": action.title},
                event_bus=event_bus,
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
                if not dry_run:
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
                event_bus=event_bus,
            )
            return

        if isinstance(action, ActionWriteFile):
            path = resolve_safe_project_path(action.rel_path, self._paths.BASE_DIR)
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
            before = path.read_text(encoding="utf-8") if path.exists() else ""
            after = action.body
            changed = before != after
            if changed:
                if not dry_run:
                    path.write_text(after, encoding="utf-8")
                result.files_changed.append(path)
            self._append_file_record(
                result,
                action_type="write_file",
                path=path,
                before=before,
                after=after,
                changed=changed,
                extra={"rel_path": action.rel_path},
                event_bus=event_bus,
            )
            return

        raise TypeError(f"Unsupported action: {type(action)!r}")
