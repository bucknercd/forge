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
from forge.execution.section_ops import append_to_section, replace_section_body, insert_milestone_forge_status_completed
from forge.models import Decision


class ArtifactActionApplier:
    """Deterministic file updates only (stdlib + project Paths)."""

    def __init__(self, paths_mod) -> None:
        self._paths = paths_mod

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
                result.errors.append(str(exc))
                break
        return result

    def _apply_one(self, action: Any, milestone: Milestone, result: ApplyResult) -> None:
        if isinstance(action, ActionAppendSection):
            path = self._resolve(action.target)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# {action.target.title()}\n\n", encoding="utf-8")
            content = DesignManager.load_document(path)
            new_content, changed = append_to_section(
                content, action.section_heading, action.body
            )
            if changed:
                DesignManager.save_document(path, new_content)
                result.files_changed.append(path)
            result.actions_applied.append(
                {
                    "type": "append_section",
                    "target": action.target,
                    "section_heading": action.section_heading,
                    "changed": changed,
                }
            )
            return

        if isinstance(action, ActionReplaceSection):
            path = self._resolve(action.target)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# {action.target.title()}\n\n", encoding="utf-8")
            content = DesignManager.load_document(path)
            new_content, changed = replace_section_body(
                content, action.section_heading, action.body
            )
            if changed:
                DesignManager.save_document(path, new_content)
                result.files_changed.append(path)
            result.actions_applied.append(
                {
                    "type": "replace_section",
                    "target": action.target,
                    "section_heading": action.section_heading,
                    "changed": changed,
                }
            )
            return

        if isinstance(action, ActionAddDecision):
            decision = Decision(
                title=action.title,
                context=action.context,
                decision=action.decision,
                rationale=action.rationale,
                timestamp=datetime.now(),
            )
            DecisionTracker.append_decision(decision)
            result.files_changed.append(self._paths.DECISIONS_FILE)
            result.actions_applied.append({"type": "add_decision", "title": action.title})
            return

        if isinstance(action, ActionMarkMilestoneCompleted):
            path = self._paths.MILESTONES_FILE
            content = DesignManager.load_document(path)
            new_content, changed = insert_milestone_forge_status_completed(
                content, milestone.id
            )
            if changed:
                DesignManager.save_document(path, new_content)
                result.files_changed.append(path)
            result.actions_applied.append(
                {"type": "mark_milestone_completed", "changed": changed}
            )
            return

        raise TypeError(f"Unsupported action: {type(action)!r}")
