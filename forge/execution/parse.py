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


def _parse_target(tok: str, line_no: int | None = None, kind: str = "forge item") -> str:
    t = tok.strip().lower()
    if t not in TARGETS:
        raise ValueError(
            _fmt_diag(
                kind,
                f"Unknown document target {tok!r}. Expected one of {sorted(TARGETS)}.",
                line_no,
            )
        )
    return t


def parse_forge_action_line(
    raw: str, milestone: Milestone, line_no: int | None = None
) -> ForgeAction:
    line = raw.strip()
    if not line:
        raise ValueError(_fmt_diag("forge action", "Empty line.", line_no))

    if line == "mark_milestone_completed":
        return ActionMarkMilestoneCompleted()

    first = line.split(None, 1)[0].lower()
    if first == "add_decision":
        return _parse_add_decision(line, milestone)

    if " | " not in line:
        raise ValueError(
            _fmt_diag(
                "forge action",
                f"Invalid format (expected 'cmd ... | body' or known keyword): {raw!r}",
                line_no,
            )
        )

    left, body = line.split(" | ", 1)
    parts = left.split()
    if len(parts) < 3:
        raise ValueError(_fmt_diag("forge action", f"Invalid action: {raw!r}", line_no))

    cmd = parts[0].lower()
    target = _parse_target(parts[1], line_no=line_no, kind="forge action")
    section_heading = " ".join(parts[2:]).strip()
    if not section_heading:
        raise ValueError(
            _fmt_diag("forge action", f"Missing section heading: {raw!r}", line_no)
        )

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

    raise ValueError(
        _fmt_diag("forge action", f"Unknown command {parts[0]!r}", line_no)
    )


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


def parse_forge_validation_line(raw: str, line_no: int | None = None) -> ForgeValidationRule:
    line = raw.strip()
    if not line:
        raise ValueError(_fmt_diag("forge validation", "Empty line.", line_no))

    parts = line.split()
    if len(parts) < 2:
        raise ValueError(
            _fmt_diag("forge validation", f"Invalid validation rule: {raw!r}", line_no)
        )

    kind = parts[0].lower()
    target = _parse_target(parts[1], line_no=line_no, kind="forge validation")

    if kind == "file_contains":
        if len(parts) < 3:
            raise ValueError(
                _fmt_diag(
                    "forge validation",
                    f"file_contains expects: file_contains <target> <substring>: {raw!r}",
                    line_no,
                )
            )
        substring = line.split(maxsplit=2)[2]
        return RuleFileContains(target=target, substring=substring)  # type: ignore[arg-type]

    if kind == "section_contains":
        if len(parts) < 4:
            raise ValueError(
                _fmt_diag(
                    "forge validation",
                    (
                        "section_contains expects: section_contains <target> "
                        f"<section> <substring>: {raw!r}"
                    ),
                    line_no,
                )
            )
        section_heading = parts[2]
        substring = line.split(maxsplit=3)[3]
        return RuleSectionContains(
            target=target,  # type: ignore[arg-type]
            section_heading=section_heading,
            substring=substring,
        )

    raise ValueError(
        _fmt_diag("forge validation", f"Unknown validation kind {kind!r}", line_no)
    )


def _fmt_diag(kind: str, message: str, line_no: int | None) -> str:
    if line_no is None:
        return f"{kind}: {message}"
    return f"{kind} line {line_no}: {message}"
