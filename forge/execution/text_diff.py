"""Bounded unified text diffs for execution reporting (stdlib only)."""

from __future__ import annotations

import difflib


def unified_diff_bounded(
    before: str,
    after: str,
    label: str,
    *,
    max_lines: int = 48,
    max_chars: int = 8000,
) -> tuple[str, bool]:
    """
    Return (diff_text, truncated). Empty string if before == after.
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
        )
    )
    text = "\n".join(diff_lines)
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
