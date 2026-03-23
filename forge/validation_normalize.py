from __future__ import annotations

import logging
import re

from forge.execution.parse import parse_forge_validation_line

logger = logging.getLogger(__name__)


_CANONICAL_PREFIXES = (
    "path_file_contains ",
    "file_contains ",
    "section_contains ",
)


def normalize_validation_rule(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith(_CANONICAL_PREFIXES):
        return s

    # "<path> contains <phrase>" -> path_file_contains <path> <needle>
    m = re.match(r"^([A-Za-z0-9_\-./]+)\s+contains\s+(.+)$", s, re.IGNORECASE)
    if m:
        path = m.group(1).strip()
        phrase = m.group(2).strip().lower()
        needle = _infer_contains_needle(path, phrase)
        if needle:
            return f"path_file_contains {path} {needle}"
        return None

    # "<path> filters out INFO and DEBUG messages" -> ERROR heuristic for logcheck-like tasks
    m2 = re.match(r"^([A-Za-z0-9_\-./]+)\s+filters?\s+out\s+(.+)$", s, re.IGNORECASE)
    if m2:
        path = m2.group(1).strip()
        phrase = m2.group(2).strip().lower()
        if "info" in phrase and "debug" in phrase:
            return f"path_file_contains {path} ERROR"
        return None

    return None


def _infer_contains_needle(path: str, phrase: str) -> str | None:
    if "'" in phrase:
        quoted = re.findall(r"'([^']+)'", phrase)
        if quoted:
            return quoted[0]
    if '"' in phrase:
        quoted = re.findall(r'"([^"]+)"', phrase)
        if quoted:
            return quoted[0]
    if "function" in phrase:
        if path.endswith(".py"):
            return "def"
        if path.endswith(".go"):
            return "func"
    if "error" in phrase:
        return "ERROR"
    if "read" in phrase and "file" in phrase:
        return "open"
    if "parse" in phrase:
        return "parse"
    return None


def sanitize_validation_rules(
    rules: list[str],
    *,
    log_warnings: bool = True,
) -> tuple[list[str], list[str]]:
    """
    Keep only canonical, parseable Forge validation rules.
    Returns (sanitized_rules, warnings).
    """
    out: list[str] = []
    warnings: list[str] = []
    for raw in rules:
        norm = normalize_validation_rule(raw)
        if norm is None:
            msg = f"Dropped invalid validation: {raw!r}"
            warnings.append(msg)
            if log_warnings:
                logger.warning(msg)
            continue
        try:
            parse_forge_validation_line(norm)
        except ValueError:
            msg = f"Dropped invalid validation: {raw!r}"
            warnings.append(msg)
            if log_warnings:
                logger.warning(msg)
            continue
        if norm != raw:
            msg = f"Normalized validation: {raw!r} -> {norm!r}"
            warnings.append(msg)
            if log_warnings:
                logger.warning(msg)
        out.append(norm)
    return out, warnings

