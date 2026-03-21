"""
Deterministic bounded substring edits for repo files (non-design paths).

Matching uses non-overlapping left-to-right scans. Zero or multiple matches fail.
"""

from __future__ import annotations


def unescape_action_body(body: str) -> str:
    return body.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")


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


def require_unique_span(
    text: str, sub: str, *, label: str
) -> tuple[int, int]:
    spans = nonoverlapping_spans(text, sub)
    if len(spans) == 0:
        preview = sub[:80] + ("..." if len(sub) > 80 else "")
        raise ValueError(f"{label}: no match for substring ({preview!r})")
    if len(spans) > 1:
        raise ValueError(
            f"{label}: ambiguous — {len(spans)} non-overlapping matches for substring"
        )
    return spans[0]


def apply_insert_after(text: str, anchor: str, insertion: str) -> str:
    _s0, s1 = require_unique_span(text, anchor, label="insert_after_in_file")
    return text[:s1] + insertion + text[s1:]


def apply_insert_before(text: str, anchor: str, insertion: str) -> str:
    s0, s1 = require_unique_span(text, anchor, label="insert_before_in_file")
    return text[:s0] + insertion + text[s0:]


def apply_replace_text(text: str, old: str, new: str) -> str:
    s0, s1 = require_unique_span(text, old, label="replace_text_in_file")
    return text[:s0] + new + text[s1:]


def apply_replace_block(
    text: str, start_marker: str, end_marker: str, new_body: str
) -> str:
    s0, s1 = require_unique_span(
        text, start_marker, label="replace_block_in_file (start)"
    )
    tail = text[s1:]
    e_rel = tail.find(end_marker)
    if e_rel < 0:
        raise ValueError(
            "replace_block_in_file: no match for end marker after start marker"
        )
    e0 = s1 + e_rel
    e1 = e0 + len(end_marker)
    return text[:s0] + new_body + text[e1:]
