"""Parse Forge Actions / Forge Validation lines from milestone markdown."""

from __future__ import annotations

import re

from forge.design_manager import Milestone
from forge.execution.file_edits import unescape_action_body
from forge.execution.write_file_integrity import log_write_file_payload_stage
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
    ForgeAction,
)
from forge.execution.validation_rules import (
    ForgeValidationRule,
    RuleFileContains,
    RulePathFileContains,
    RuleSectionContains,
)
from forge.execution.validation_substring_parse import parse_validation_needle

TARGETS = frozenset({"requirements", "architecture", "decisions", "milestones"})

# ``write_file <rel_path> | <body>`` — delimiter is ONLY after the path token (not the first
# `` | `` in the line). Bodies may contain `` | `` (e.g. Python ``a | b``); splitting the
# whole line on the first `` | `` would truncate the payload.
_WRITE_FILE_ACTION_RE = re.compile(r"^write_file\s+(\S+)\s+\|\s(.*)$", re.DOTALL)

# Separates parts inside the right-hand side of `cmd path | ...` for bounded file edits.
FORGE_BOUNDED_EDIT_SEP = " @@FORGE@@ "

BOUNDED_FILE_EDIT_CMDS = frozenset(
    {
        "insert_after_in_file",
        "insert_before_in_file",
        "replace_text_in_file",
        "replace_block_in_file",
        "replace_lines_in_file",
    }
)

# Trailing ` | key=value ...` on bounded-edit payloads (values are non-space tokens).
_TRAILING_BOUNDED_OPTS_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*=\S+)(\s+[A-Za-z_][A-Za-z0-9_]*=\S+)*$"
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
        m = _WRITE_FILE_ACTION_RE.match(line)
        if not m:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"write_file expects: write_file <rel_path> | <body> "
                    f"(path must be a single token; body may contain ' | '): {raw!r}",
                    line_no,
                )
            )
        rel_path = m.group(1).strip()
        body = m.group(2)
        if not rel_path:
            raise ValueError(
                _fmt_diag("forge action", f"write_file empty path: {raw!r}", line_no)
            )
        body_resolved = unescape_action_body(body)
        log_write_file_payload_stage(
            rel_path, body_resolved, "after_parse_unescape", line_no=line_no
        )
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


def _split_trailing_bounded_options(payload_raw: str) -> tuple[str, str]:
    s = payload_raw.rstrip()
    if " | " not in s:
        return s, ""
    base, tail = s.rsplit(" | ", 1)
    t = tail.strip()
    if not t or "=" not in t or _TRAILING_BOUNDED_OPTS_RE.match(t) is None:
        return s, ""
    return base.rstrip(), t


def _parse_bounded_option_tokens(opt_line: str) -> dict[str, str | int | bool]:
    out: dict[str, str | int | bool] = {}
    for tok in opt_line.split():
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        key = k.strip().lower()
        vs = v.strip()
        vl = vs.lower()
        if vl in ("true", "false"):
            out[key] = vl == "true"
        elif vs.isdigit():
            out[key] = int(vs)
        else:
            out[key] = vs
    return out


def _bounded_match_fields(
    opts: dict[str, str | int | bool], line_no: int | None
) -> tuple[int, bool, bool]:
    occurrence = int(opts.get("occurrence", 1))
    must_be_unique = bool(opts.get("must_be_unique", True))
    line_match = bool(opts.get("line_match", False))
    if must_be_unique and occurrence != 1:
        raise ValueError(
            _fmt_diag(
                "forge action",
                "must_be_unique=true requires occurrence=1 (or omit occurrence)",
                line_no,
            )
        )
    return occurrence, must_be_unique, line_match


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
    work_raw, opt_line = _split_trailing_bounded_options(payload_raw)
    payload = unescape_action_body(work_raw)
    opt_dict = _parse_bounded_option_tokens(opt_line)
    occ, mu, lm = _bounded_match_fields(opt_dict, line_no)
    sep = FORGE_BOUNDED_EDIT_SEP

    if cmd == "replace_lines_in_file":
        chunks = payload.split(sep)
        if len(chunks) != 3:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"replace_lines_in_file needs: start_line{sep}end_line{sep}replacement: {raw!r}",
                    line_no,
                )
            )
        sa, sb, repl = chunks[0].strip(), chunks[1].strip(), chunks[2]
        if opt_dict:
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"replace_lines_in_file does not accept trailing options: {raw!r}",
                    line_no,
                )
            )
        if not sa.isdigit() or not sb.isdigit():
            raise ValueError(
                _fmt_diag(
                    "forge action",
                    f"replace_lines_in_file: start_line and end_line must be integers: {raw!r}",
                    line_no,
                )
            )
        return ActionReplaceLinesInFile(
            rel_path=rel_path,
            start_line=int(sa),
            end_line=int(sb),
            replacement=repl,
        )

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
            occurrence=occ,
            must_be_unique=mu,
            line_match=lm,
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
            rel_path=rel_path,
            anchor=first_part,
            insertion=second_part,
            occurrence=occ,
            must_be_unique=mu,
            line_match=lm,
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
            rel_path=rel_path,
            anchor=first_part,
            insertion=second_part,
            occurrence=occ,
            must_be_unique=mu,
            line_match=lm,
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
            rel_path=rel_path,
            old_text=first_part,
            new_text=second_part,
            occurrence=occ,
            must_be_unique=mu,
            line_match=lm,
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
        _, relpath, substring_field = toks
        if not relpath.strip():
            raise ValueError(
                _fmt_diag(
                    "forge validation",
                    f"path_file_contains needs non-empty path and substring: {raw!r}",
                    line_no,
                )
            )
        try:
            needle = parse_validation_needle(substring_field, line_no=line_no)
        except ValueError as exc:
            raise ValueError(
                _fmt_diag("forge validation", f"path_file_contains: {exc}", line_no)
            ) from exc
        return RulePathFileContains(
            rel_path=relpath.strip(),
            substring=needle.needle,
            substring_input=needle.raw_input,
            substring_quote_style=needle.quote_style,
        )

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
        substring_field = line.split(maxsplit=2)[2]
        try:
            needle = parse_validation_needle(substring_field, line_no=line_no)
        except ValueError as exc:
            raise ValueError(
                _fmt_diag("forge validation", f"file_contains: {exc}", line_no)
            ) from exc
        return RuleFileContains(
            target=target,  # type: ignore[arg-type]
            substring=needle.needle,
            substring_input=needle.raw_input,
            substring_quote_style=needle.quote_style,
        )

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
        substring_field = line.split(maxsplit=3)[3]
        try:
            needle = parse_validation_needle(substring_field, line_no=line_no)
        except ValueError as exc:
            raise ValueError(
                _fmt_diag("forge validation", f"section_contains: {exc}", line_no)
            ) from exc
        return RuleSectionContains(
            target=target,  # type: ignore[arg-type]
            section_heading=section_heading,
            substring=needle.needle,
            substring_input=needle.raw_input,
            substring_quote_style=needle.quote_style,
        )

    raise ValueError(
        _fmt_diag("forge validation", f"Unknown validation kind {kind!r}", line_no)
    )


def _fmt_diag(kind: str, message: str, line_no: int | None) -> str:
    if line_no is None:
        return f"{kind}: {message}"
    return f"{kind} line {line_no}: {message}"
