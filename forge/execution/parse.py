"""Parse Forge Actions / Forge Validation lines from milestone markdown."""

from __future__ import annotations

from forge.design_manager import Milestone
from forge.execution.file_edits import unescape_action_body
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
    ForgeAction,
)
from forge.execution.validation_rules import (
    ForgeValidationRule,
    RuleFileContains,
    RulePathFileContains,
    RuleSectionContains,
)

TARGETS = frozenset({"requirements", "architecture", "decisions", "milestones"})

# Separates parts inside the right-hand side of `cmd path | ...` for bounded file edits.
FORGE_BOUNDED_EDIT_SEP = " @@FORGE@@ "

BOUNDED_FILE_EDIT_CMDS = frozenset(
    {
        "insert_after_in_file",
        "insert_before_in_file",
        "replace_text_in_file",
        "replace_block_in_file",
    }
)


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
    if first == "write_file":
        if " | " not in line:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"write_file expects: write_file <rel_path> | <body>: {raw!r}",
                    line_no,
                )
            )
        left, body = line.split(" | ", 1)
        lparts = left.split(None, 1)
        if len(lparts) < 2:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"write_file missing relative path: {raw!r}",
                    line_no,
                )
            )
        rel_path = lparts[1].strip()
        if not rel_path:
            raise ValueError(
                _fmt_diag("forge action", f"write_file empty path: {raw!r}", line_no)
            )
        body_resolved = unescape_action_body(body)
        return ActionWriteFile(rel_path=rel_path, body=body_resolved)

    if first in BOUNDED_FILE_EDIT_CMDS:
        return _parse_bounded_file_edit(first, raw, line_no)

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


def _parse_bounded_file_edit(cmd: str, raw: str, line_no: int | None) -> ForgeAction:
    if " | " not in raw:
        raise ValueError(
            _fmt_diag(
                "forge action",
                f"{cmd} expects: {cmd} <rel_path> | <parts separated by{FORGE_BOUNDED_EDIT_SEP!r}>: {raw!r}",
                line_no,
            )
        )
    left, payload_raw = raw.split(" | ", 1)
    lparts = left.split(None, 1)
    if len(lparts) < 2:
        raise ValueError(
            _fmt_diag(
                "forge action",
                f"{cmd} missing relative path: {raw!r}",
                line_no,
            )
        )
    rel_path = lparts[1].strip()
    if not rel_path:
        raise ValueError(
            _fmt_diag("forge action", f"{cmd} empty path: {raw!r}", line_no)
        )
    payload = unescape_action_body(payload_raw)
    sep = FORGE_BOUNDED_EDIT_SEP
    if cmd == "replace_block_in_file":
        chunks = payload.split(sep)
        if len(chunks) != 3:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"replace_block_in_file needs exactly two separators {sep!r} "
                    f"(start, end, new_body): {raw!r}",
                    line_no,
                )
            )
        start_m, end_m, new_body = chunks[0], chunks[1], chunks[2]
        if not start_m or not end_m:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"replace_block_in_file: empty start or end marker: {raw!r}",
                    line_no,
                )
            )
        return ActionReplaceBlockInFile(
            rel_path=rel_path,
            start_marker=start_m,
            end_marker=end_m,
            new_body=new_body,
        )
    parts = payload.split(sep)
    if len(parts) != 2:
        raise ValueError(
            _fmt_diag(
                "forge action",
                f"{cmd} needs exactly one separator {sep!r} between two parts: {raw!r}",
                line_no,
            )
        )
    first_part, second_part = parts[0], parts[1]
    if cmd == "insert_after_in_file":
        if not first_part:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"insert_after_in_file: empty anchor: {raw!r}",
                    line_no,
                )
            )
        return ActionInsertAfterInFile(
            rel_path=rel_path, anchor=first_part, insertion=second_part
        )
    if cmd == "insert_before_in_file":
        if not first_part:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"insert_before_in_file: empty anchor: {raw!r}",
                    line_no,
                )
            )
        return ActionInsertBeforeInFile(
            rel_path=rel_path, anchor=first_part, insertion=second_part
        )
    if cmd == "replace_text_in_file":
        if not first_part:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"replace_text_in_file: empty old_text: {raw!r}",
                    line_no,
                )
            )
        return ActionReplaceTextInFile(
            rel_path=rel_path, old_text=first_part, new_text=second_part
        )
    raise ValueError(_fmt_diag("forge action", f"Unknown bounded edit {cmd!r}", line_no))


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
    if len(parts) < 1:
        raise ValueError(
            _fmt_diag("forge validation", f"Invalid validation rule: {raw!r}", line_no)
        )

    kind = parts[0].lower()

    if kind == "path_file_contains":
        toks = line.split(None, 2)
        if len(toks) < 3:
            raise ValueError(
                _fmt_diag(
                    "forge validation",
                    (
                        "path_file_contains expects: path_file_contains "
                        f"<rel_path> <substring>: {raw!r}"
                    ),
                    line_no,
                )
            )
        _, relpath, substring = toks
        if not relpath.strip() or not substring.strip():
            raise ValueError(
                _fmt_diag(
                    "forge validation",
                    f"path_file_contains needs non-empty path and substring: {raw!r}",
                    line_no,
                )
            )
        return RulePathFileContains(rel_path=relpath.strip(), substring=substring)

    if len(parts) < 2:
        raise ValueError(
            _fmt_diag("forge validation", f"Invalid validation rule: {raw!r}", line_no)
        )

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
