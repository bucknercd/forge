"""Artifact-driven milestone execution (deterministic, file-based)."""

from forge.execution.models import (
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
    ExecutionPlan,
    ApplyResult,
    ForgeAction,
)
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.apply import ArtifactActionApplier

__all__ = [
    "ActionAppendSection",
    "ActionReplaceSection",
    "ActionAddDecision",
    "ActionMarkMilestoneCompleted",
    "ActionWriteFile",
    "ActionInsertAfterInFile",
    "ActionInsertBeforeInFile",
    "ActionReplaceTextInFile",
    "ActionReplaceBlockInFile",
    "ActionReplaceLinesInFile",
    "ExecutionPlan",
    "ApplyResult",
    "ForgeAction",
    "ExecutionPlanBuilder",
    "ArtifactActionApplier",
]
