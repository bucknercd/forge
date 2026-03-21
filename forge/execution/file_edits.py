"""
Deterministic bounded substring / line edits for repo files (non-design paths).

Matching is non-overlapping for substring mode, or full-line equality when
line_match is true. With must_be_unique=false, occurrence selects the Nth match.
Newlines are normalized to \\n before matching and when writing bounded results.
"""

from __future__ import annotations

from dataclasses import dataclass


def unescape_action_body(body: str) -> str:
    return body.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def nonoverlapping_spans(text: str, sub: str) -> list[tuple[int, int]]:
    if not sub:
        raise ValueError("empty substring/marker is not allowed")
    spans: list[tuple[int, int]] = []
    i = 0
    while True:
        j = text.find(sub, i)
        if j < 0:
            break
        spans.append((j, j + len(sub)))
        i = j + max(1, len(sub))
    return spans


def full_line_spans(text: str) -> list[tuple[int, int, str]]:
    """
    For each logical line: (content_start, content_end, content) without \\n.
    content_end is the index of the following \\n or len(text).
    """
    text = normalize_newlines(text)
    res: list[tuple[int, int, str]] = []
    i = 0
    n = len(text)
    while i <= n:
        j = text.find("\n", i)
        if j < 0:
            res.append((i, n, text[i:n]))
            break
        res.append((i, j, text[i:j]))
        i = j + 1
    return res


def line_match_spans(text: str, line_content: str) -> list[tuple[int, int]]:
    """Spans (start, end) of line *content* where content == line_content exactly."""
    spans: list[tuple[int, int]] = []
    for s, e, content in full_line_spans(text):
        if content == line_content:
            spans.append((s, e))
    return spans


def offset_after_line(text: str, content_start: int, content_end: int) -> int:
    """Insert position immediately after this line (after its newline if any)."""
    if content_end < len(text) and text[content_end] == "\n":
        return content_end + 1
    return content_end


@dataclass(frozen=True)
class BoundedMatchOptions:
    occurrence: int = 1
    must_be_unique: bool = True
    line_match: bool = False


def pick_span(
    spans: list[tuple[int, int]],
    *,
    label: str,
    opts: BoundedMatchOptions,
) -> tuple[int, int]:
    if not spans:
        raise ValueError(f"{label}: no match")
    if opts.must_be_unique:
        if opts.occurrence != 1:
            raise ValueError(
                f"{label}: occurrence={opts.occurrence} is invalid when must_be_unique=true"
            )
        if len(spans) != 1:
            raise ValueError(
                f"{label}: ambiguous — {len(spans)} matches (must_be_unique=true)"
            )
        return spans[0]
    if opts.occurrence < 1 or opts.occurrence > len(spans):
        raise ValueError(
            f"{label}: occurrence {opts.occurrence} out of range (1..{len(spans)})"
        )
    return spans[opts.occurrence - 1]


def resolve_anchor_span(
    text: str,
    anchor: str,
    *,
    label: str,
    opts: BoundedMatchOptions,
) -> tuple[int, int]:
    text = normalize_newlines(text)
    if opts.line_match:
        spans = line_match_spans(text, anchor)
    else:
        spans = nonoverlapping_spans(text, anchor)
    return pick_span(spans, label=label, opts=opts)


def apply_insert_after(
    text: str, anchor: str, insertion: str, *, opts: BoundedMatchOptions
) -> str:
    text = normalize_newlines(text)
    s0, s1 = resolve_anchor_span(text, anchor, label="insert_after_in_file", opts=opts)
    if opts.line_match:
        pos = offset_after_line(text, s0, s1)
    else:
        pos = s1
    return text[:pos] + insertion + text[pos:]


def apply_insert_before(
    text: str, anchor: str, insertion: str, *, opts: BoundedMatchOptions
) -> str:
    text = normalize_newlines(text)
    s0, s1 = resolve_anchor_span(text, anchor, label="insert_before_in_file", opts=opts)
    return text[:s0] + insertion + text[s0:]


def apply_replace_text(
    text: str, old: str, new: str, *, opts: BoundedMatchOptions
) -> str:
    text = normalize_newlines(text)
    if opts.line_match:
        s0, s1 = resolve_anchor_span(text, old, label="replace_text_in_file", opts=opts)
        return text[:s0] + new + text[s1:]
    s0, s1 = resolve_anchor_span(text, old, label="replace_text_in_file", opts=opts)
    return text[:s0] + new + text[s1:]


def apply_replace_block(
    text: str,
    start_marker: str,
    end_marker: str,
    new_body: str,
    *,
    start_opts: BoundedMatchOptions,
) -> str:
    if not end_marker:
        raise ValueError("replace_block_in_file: empty end marker")
    text = normalize_newlines(text)
    s0, s1 = resolve_anchor_span(
        text, start_marker, label="replace_block_in_file (start)", opts=start_opts
    )
    if start_opts.line_match:
        block_start = s0
        search_from = offset_after_line(text, s0, s1)
    else:
        block_start = s0
        search_from = s1
    tail = text[search_from:]
    e_rel = tail.find(end_marker)
    if e_rel < 0:
        raise ValueError(
            "replace_block_in_file: no match for end marker after start region"
        )
    e1 = search_from + e_rel + len(end_marker)
    return text[:block_start] + new_body + text[e1:]


def apply_replace_lines(
    text: str, start_line: int, end_line: int, replacement: str
) -> str:
    text = normalize_newlines(text)
    lines = text.split("\n")
    n = len(lines)
    if start_line < 1 or end_line < start_line or end_line > n:
        raise ValueError(
            "replace_lines_in_file: line range "
            f"{start_line}-{end_line} invalid for file with {n} line(s)"
        )
    rep_lines = replacement.split("\n") if replacement else []
    new_lines = lines[: start_line - 1] + rep_lines + lines[end_line:]
    return "\n".join(new_lines)
