"""
Deterministic unquoting for Forge validation substring fields (needles).

Milestone lines often wrap needles in single or double quotes so markdown / models
can emit tokens like ``def main`` without shell-splitting issues. The raw field
must be unwrapped so validation searches for the intended text, not the quote
characters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ValidationNeedleResult:
    """Parsed needle after optional outer quote stripping."""

    needle: str
    """Text to search for in the file or section body."""

    raw_input: str
    """Exact substring field from the validation line (before unquoting)."""

    quote_style: Literal["none", "single", "double"]
    """Whether outer single- or double-quotes were stripped, or none."""


def _decode_double_quoted_inner(inner: str) -> str:
    """Decode escape sequences inside a double-quoted validation needle."""
    out: list[str] = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        if i + 1 >= len(inner):
            raise ValueError(
                "double-quoted substring: backslash at end of string (invalid escape)"
            )
        nxt = inner[i + 1]
        if nxt == "\\":
            out.append("\\")
        elif nxt == '"':
            out.append('"')
        elif nxt == "n":
            out.append("\n")
        elif nxt == "t":
            out.append("\t")
        elif nxt == "r":
            out.append("\r")
        else:
            raise ValueError(
                f"double-quoted substring: invalid escape sequence \\{nxt!r} "
                "(supported: \\\\, \\\", \\n, \\t, \\r)"
            )
        i += 2
    return "".join(out)


def parse_validation_needle(
    rest: str,
    *,
    line_no: int | None = None,
) -> ValidationNeedleResult:
    """
    Parse the substring field after command/target tokens.

    - **Unquoted**: ``rest`` is used as-is except leading/trailing whitespace on
      the whole field is stripped (outer trim only).
    - **Single-quoted** ``'...'``: inner is literal; no escapes. ``'`` inside the
      inner string is forbidden (strict).
    - **Double-quoted** ``"..."``: inner supports ``\\``, ``\"``, ``\\n``,
      ``\\t``, ``\\r`` only.

    Mismatched or unclosed quotes raise ``ValueError`` with a clear message.
    """
    _ = line_no  # reserved for future column-aware diagnostics
    raw_input = rest
    s = rest.strip()
    if not s:
        raise ValueError("empty substring field")

    if s[0] == "'":
        if len(s) < 2:
            raise ValueError("unclosed single-quoted substring (missing closing quote)")
        if s[-1] != "'":
            raise ValueError(
                "unclosed single-quoted substring (expected closing ' or mismatched quotes)"
            )
        inner = s[1:-1]
        if "'" in inner:
            raise ValueError(
                "single-quoted substring cannot contain an unescaped single quote (use double-quoted form)"
            )
        if not inner:
            raise ValueError("empty substring after unquoting single-quoted string")
        return ValidationNeedleResult(
            needle=inner,
            raw_input=raw_input,
            quote_style="single",
        )

    if s[0] == '"':
        if len(s) < 2:
            raise ValueError("unclosed double-quoted substring (missing closing quote)")
        if s[-1] != '"':
            raise ValueError(
                'unclosed double-quoted substring (expected closing " or mismatched quotes)'
            )
        inner = s[1:-1]
        if not inner:
            raise ValueError("empty substring after unquoting double-quoted string")
        return ValidationNeedleResult(
            needle=_decode_double_quoted_inner(inner),
            raw_input=raw_input,
            quote_style="double",
        )

    return ValidationNeedleResult(needle=s, raw_input=raw_input, quote_style="none")
