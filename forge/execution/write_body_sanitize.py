"""
Normalize LLM / transport artifacts in file bodies before disk write.

Primary fixes:
- Spurious backslash-quoting outside string literals (e.g. Go ``import \\"fmt\\"``).
- Profile-specific follow-ups (Go import hygiene).

These transforms are intentionally conservative: escapes *inside* string literals are preserved.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any


def _suffix(rel_path: str) -> str:
    return Path(rel_path.replace("\\", "/")).suffix.lower()


def _go_like_strip_spurious_slash_quotes(body: str) -> str:
    """
    Remove erroneous ``\\"`` / ``\\'`` sequences that appear outside Go strings,
    comments, and raw string literals.
    """
    out: list[str] = []
    i = 0
    n = len(body)
    state = "code"

    while i < n:
        ch = body[i]
        if state == "code":
            if i + 1 < n and body[i : i + 2] == "//":
                out.append("//")
                i += 2
                state = "line"
                continue
            if i + 1 < n and body[i : i + 2] == "/*":
                out.append("/*")
                i += 2
                state = "block"
                continue
            if ch == '"':
                out.append('"')
                i += 1
                state = "dstr"
                continue
            if ch == "`":
                out.append("`")
                i += 1
                state = "raw"
                continue
            if ch == "'":
                out.append("'")
                i += 1
                state = "rune"
                continue
            if ch == "\\" and i + 1 < n and body[i + 1] in "\"'":
                out.append(body[i + 1])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if state == "line":
            if ch == "\n":
                out.append(ch)
                i += 1
                state = "code"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "block":
            if i + 1 < n and body[i : i + 2] == "*/":
                out.append("*/")
                i += 2
                state = "code"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "dstr":
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(body[i + 1])
                i += 2
                continue
            if ch == '"':
                out.append('"')
                i += 1
                state = "code"
                continue
            out.append(ch)
            i += 1
            continue

        if state == "raw":
            if ch == "`":
                out.append("`")
                i += 1
                state = "code"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "rune":
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(body[i + 1])
                i += 2
                continue
            if ch == "'":
                out.append("'")
                i += 1
                state = "code"
                continue
            out.append(ch)
            i += 1
            continue

    return "".join(out)


def _python_strip_spurious_slash_quotes(body: str) -> str:
    """Same as Go for comments/strings, but use ``#`` line comments (not ``//``)."""
    out: list[str] = []
    i = 0
    n = len(body)
    state = "code"

    def _starts_triple(idx: int, q: str) -> bool:
        return idx + 2 < n and body[idx : idx + 3] == q * 3

    while i < n:
        ch = body[i]
        if state == "code":
            if ch == "#":
                out.append("#")
                i += 1
                state = "line"
                continue
            if ch in "\"'":
                quote = ch
                if _starts_triple(i, quote):
                    out.append(quote * 3)
                    i += 3
                    state = "tstr_" + quote
                    continue
                out.append(quote)
                i += 1
                state = "dstr" if quote == '"' else "sstr"
                continue
            if ch == "\\" and i + 1 < n and body[i + 1] in "\"'":
                out.append(body[i + 1])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if state == "line":
            if ch == "\n":
                out.append(ch)
                i += 1
                state = "code"
            else:
                out.append(ch)
                i += 1
            continue

        if state in {"dstr", "sstr"}:
            q = '"' if state == "dstr" else "'"
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(body[i + 1])
                i += 2
                continue
            if ch == q:
                out.append(q)
                i += 1
                state = "code"
                continue
            out.append(ch)
            i += 1
            continue

        if state == "tstr_\"":
            if _starts_triple(i, '"'):
                out.append('"""')
                i += 3
                state = "code"
                continue
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(body[i + 1])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if state == "tstr_'":
            if _starts_triple(i, "'"):
                out.append("'''")
                i += 3
                state = "code"
                continue
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(body[i + 1])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

    return "".join(out)


def _terraform_strip_spurious_slash_quotes(body: str) -> str:
    """HCL: treat ``#`` and ``//`` as line comments; ``/* */`` block; ``"`` strings."""
    out: list[str] = []
    i = 0
    n = len(body)
    state = "code"

    while i < n:
        ch = body[i]
        if state == "code":
            if ch == "#":
                out.append("#")
                i += 1
                state = "line_hash"
                continue
            if i + 1 < n and body[i : i + 2] == "//":
                out.append("//")
                i += 2
                state = "line_slash"
                continue
            if i + 1 < n and body[i : i + 2] == "/*":
                out.append("/*")
                i += 2
                state = "block"
                continue
            if ch == '"':
                out.append('"')
                i += 1
                state = "dstr"
                continue
            if ch == "\\" and i + 1 < n and body[i + 1] in "\"'":
                out.append(body[i + 1])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if state in {"line_hash", "line_slash"}:
            if ch == "\n":
                out.append(ch)
                i += 1
                state = "code"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "block":
            if i + 1 < n and body[i : i + 2] == "*/":
                out.append("*/")
                i += 2
                state = "code"
            else:
                out.append(ch)
                i += 1
            continue

        if state == "dstr":
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(body[i + 1])
                i += 2
                continue
            if ch == '"':
                out.append('"')
                i += 1
                state = "code"
                continue
            out.append(ch)
            i += 1
            continue

    return "".join(out)


_GO_IMPORT_CORRUPT = re.compile(
    r"""^(\s*import\s+)(\\")([^"\\]+)(\\")(\s*)$"""
)
_GO_IMPORT_PAREN_LINE = re.compile(
    r"""^(\s*)(\\")([^"\\]+)(\\")(\s*)$"""
)


def _split_line_newline(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def _go_extra_import_line_fixes(body: str) -> str:
    """
    Catch-all for single-line ``import \\"pkg\\"`` and grouped import lines that
    still slipped past the scanner (e.g. odd comment placement).
    """
    lines = body.splitlines(keepends=True)
    fixed: list[str] = []
    in_import_group = False
    for line in lines:
        core, nl = _split_line_newline(line)
        raw = core + nl
        stripped = core.lstrip()
        code_part = stripped.split("//")[0]
        if stripped.startswith("import "):
            if "(" in code_part:
                in_import_group = True
            else:
                m = _GO_IMPORT_CORRUPT.match(core)
                if m:
                    lead, _o, mid, _c, tail = m.groups()
                    raw = f'{lead}"{mid}"{tail}' + nl
        if in_import_group:
            m2 = _GO_IMPORT_PAREN_LINE.match(core)
            if m2 and not stripped.startswith("import "):
                indent, _o, mid, _c, tail = m2.groups()
                raw = f'{indent}"{mid}"{tail}' + nl
            if ")" in code_part:
                in_import_group = False
        fixed.append(raw)
    return "".join(fixed)


_CODE_LIKE_SUFFIXES = frozenset(
    {
        ".go",
        ".mod",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".java",
        ".rs",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".cs",
        ".swift",
        ".kt",
        ".kts",
    }
)


def _pick_scanner(suffix: str) -> str | None:
    if suffix == ".py":
        return "python"
    if suffix in {".tf", ".tfvars", ".hcl"}:
        return "terraform"
    if suffix in _CODE_LIKE_SUFFIXES:
        return "c_like"
    return None


def sanitize_write_file_body(
    body: str,
    *,
    normalized_rel_path: str,
    project_profile: str | None,
) -> tuple[str, dict[str, Any]]:
    """
    Return sanitized body and metadata about transforms applied.
    """
    meta: dict[str, Any] = {}
    suffix = _suffix(normalized_rel_path)
    scanner = _pick_scanner(suffix)
    out = body

    if scanner == "python":
        nxt = _python_strip_spurious_slash_quotes(out)
        if nxt != out:
            meta["slash_quote_unescape"] = "python_scanner"
        out = nxt
    elif scanner == "terraform":
        nxt = _terraform_strip_spurious_slash_quotes(out)
        if nxt != out:
            meta["slash_quote_unescape"] = "terraform_scanner"
        out = nxt
    elif scanner == "c_like":
        nxt = _go_like_strip_spurious_slash_quotes(out)
        if nxt != out:
            meta["slash_quote_unescape"] = "c_like_scanner"
        out = nxt
    # Non-code / unknown suffixes: leave body unchanged (avoid breaking prose/JSON).

    if suffix == ".go":
        nxt2 = _go_extra_import_line_fixes(out)
        if nxt2 != out:
            meta["go_import_line_fix"] = True
        out = nxt2

    return out, meta


def should_ensure_src_init_py(
    *,
    normalized_rel_path: str,
    project_profile: str | None,
) -> bool:
    """Whether writing under ``src/`` should auto-create ``src/__init__.py``."""
    if not normalized_rel_path.startswith("src/"):
        return False
    if project_profile == "python":
        return True
    if project_profile in {"go", "terraform"}:
        return False
    return normalized_rel_path.endswith(".py")
