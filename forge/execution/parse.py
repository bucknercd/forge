"""Parse Forge Actions / Forge Validation lines from milestone markdown."""

from __future__ import annotations

from forge.design_manager import Milestone
from forge.execution.models import (
    ActionAppendSection,
    ActionReplaceSection,
    ActionAddDecision,
    ActionMarkMilestoneCompleted,
    ForgeAction,
)
from forge.execution.validation_rules import ForgeValidationRule, RuleFileContains, RuleSectionContains

TARGETS = frozenset({"requirements", "architecture", "decisions", "milestones"})


def _parse_target(tok: str) -> str:
    t = tok.strip().lower()
    if t not in TARGETS:
        raise ValueError(f"Unknown document target '{tok}'. Expected one of {sorted(TARGETS)}.")
    return t


def parse_forge_action_line(raw: str, milestone: Milestone) -> ForgeAction:
    line = raw.strip()
    if not line:
        raise ValueError("Empty forge action line.")

    if line == "mark_milestone_completed":
        return ActionMarkMilestoneCompleted()

    first = line.split(None, 1)[0].lower()
    if first == "add_decision":
        return _parse_add_decision(line, milestone)

    if " | " not in line:
        raise ValueError(
            f"Invalid forge action (expected 'cmd ... | body' or known keyword): {raw!r}"
        )

    left, body = line.split(" | ", 1)
    parts = left.split()
    if len(parts) < 3:
        raise ValueError(f"Invalid forge action: {raw!r}")

    cmd = parts[0].lower()
    target = _parse_target(parts[1])
    section_heading = " ".join(parts[2:]).strip()
    if not section_heading:
        raise ValueError(f"Missing section heading in forge action: {raw!r}")

    if cmd == "append_section":
        return ActionAppendSection(
            target=target,  # type: ignore[arg-type]
            section_heading=section_heading,
            body=body,
        )
    if cmd == "replace_section":
        return ActionReplaceSection(
            target=target,  # type: ignore[arg-type]
            section_heading=section_heading,
            body=body,
        )

    raise ValueError(f"Unknown forge action command: {parts[0]!r}")


def _parse_add_decision(line: str, milestone: Milestone) -> ActionAddDecision:
    """Formats: add_decision | add_decision | title | rationale | ..."""
    parts = [p.strip() for p in line.split("|")]
    parts = [p for p in parts if p]
    key = parts[0].lower()
    if key != "add_decision":
        raise ValueError("Internal parse error for add_decision.")
    rest = parts[1:]
    if not rest:
        return ActionAddDecision(
            title=f"Milestone {milestone.id} completed",
            context=milestone.title,
            decision="Execution outcome: completed",
            rationale=(milestone.objective or "Milestone completed.").strip(),
        )
    if len(rest) == 2:
        title, rationale = rest
        return ActionAddDecision(
            title=title,
            context=milestone.title,
            decision="Execution outcome: completed",
            rationale=rationale,
        )
    if len(rest) == 4:
        title, context, decision, rationale = rest
        return ActionAddDecision(
            title=title,
            context=context,
            decision=decision,
            rationale=rationale,
        )
    raise ValueError(
        "add_decision expects: add_decision | <title> | <rationale> "
        "or add_decision | <title> | <context> | <decision> | <rationale>"
    )


def parse_forge_validation_line(raw: str) -> ForgeValidationRule:
    line = raw.strip()
    if not line:
        raise ValueError("Empty forge validation line.")

    parts = line.split()
    if len(parts) < 2:
        raise ValueError(f"Invalid forge validation rule: {raw!r}")

    kind = parts[0].lower()
    target = _parse_target(parts[1])

    if kind == "file_contains":
        if len(parts) < 3:
            raise ValueError(
                f"file_contains needs: file_contains <target> <substring>: {raw!r}"
            )
        substring = line.split(maxsplit=2)[2]
        return RuleFileContains(target=target, substring=substring)  # type: ignore[arg-type]

    if kind == "section_contains":
        if len(parts) < 4:
            raise ValueError(
                f"section_contains needs: section_contains <target> <section> <substring>: {raw!r}"
            )
        section_heading = parts[2]
        substring = line.split(maxsplit=3)[3]
        return RuleSectionContains(
            target=target,  # type: ignore[arg-type]
            section_heading=section_heading,
            substring=substring,
        )

    raise ValueError(f"Unknown forge validation kind: {kind!r}")
