"""Bounded unified text diffs for execution reporting (stdlib only)."""

from __future__ import annotations

import difflib


def unified_diff_bounded(
    before: str,
    after: str,
    label: str,
    *,
    max_lines: int = 64,
    max_chars: int = 12000,
    context_lines: int = 3,
    action_hint: str | None = None,
) -> tuple[str, bool]:
    """
    Return (diff_text, truncated). Empty string if before == after.
    action_hint is echoed as a header so multi-action runs are easier to read.
    """
    if before == after:
        return "", False

    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            lineterm="",
            n=context_lines,
        )
    )
    header_lines: list[str] = []
    if action_hint:
        header_lines.append(f"# forge-action: {action_hint}")
        header_lines.append("# ---")
    text = "\n".join(header_lines + diff_lines)
    if not text.strip():
        return "", False

    truncated = False
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        text = "\n".join(lines) + "\n... [diff truncated: too many lines]"
        truncated = True
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [diff truncated: too many characters]"
        truncated = True
    return text, truncated
