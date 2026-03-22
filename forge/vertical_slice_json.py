"""
Extract and validate JSON payloads from LLM responses for vertical-slice bundle generation.

Conservative extraction only (no eval, no YAML, no fuzzy schema guessing).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


STRICT_JSON_RETRY_SUFFIX = (
    "\n\n### OUTPUT FORMAT (required)\n"
    "Return exactly one valid JSON object and nothing else.\n"
    "No markdown code fences (no ```). No commentary, preamble, or text after the JSON.\n"
)


class VerticalSliceLlmJsonError(ValueError):
    """Raised when the model output cannot be parsed as the vertical-slice bundle JSON."""

    def __init__(self, message: str, *, artifact_paths: list[str]) -> None:
        super().__init__(message)
        self.artifact_paths = list(artifact_paths)


def _try_json_loads(s: str) -> dict[str, Any] | None:
    try:
        val = json.loads(s)
    except json.JSONDecodeError:
        return None
    if isinstance(val, dict):
        return val
    return None


_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n", re.IGNORECASE)


def _strip_json_markdown_fence(text: str) -> str | None:
    """
    If ``text`` is wrapped in a ``` or ```json fence, return inner payload; else None.
    """
    t = text.strip()
    if not t.startswith("```"):
        return None
    m = _FENCE_OPEN_RE.match(t)
    if not m:
        # ``` without newline — try minimal strip
        first = t.split("\n", 1)
        if len(first) < 2:
            return None
        rest = first[1]
    else:
        rest = t[m.end() :]
    # Close on line that is only ```
    lines = rest.splitlines()
    inner_lines: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == "```":
            inner = "\n".join(inner_lines).strip()
            return inner if inner else None
        inner_lines.append(line)
    return None


def _extract_balanced_object(s: str, start: int) -> str | None:
    """From index ``start`` (at ``{``), return the substring of the balanced ``{...}`` object."""
    depth = 0
    in_str = False
    esc = False
    quote = ""

    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        else:
            if c in "\"'":
                in_str = True
                quote = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
    return None


def extract_vertical_slice_json_text(raw: str) -> tuple[str, str]:
    """
    Return ``(json_text, extraction_kind)`` where ``json_text`` is suitable for ``json.loads``.

    Tries in order:

    1. ``direct`` — stripped full string parses as a JSON object.
    2. ``markdown_fenced`` — content inside a ``` / ```json fenced block.
    3. ``balanced_object`` — first top-level ``{...}`` substring (prose before/after ignored).

    Raises ``ValueError`` if no candidate produces a JSON object.
    """
    s = raw.strip()
    if not s:
        raise ValueError("LLM response is empty.")

    direct = _try_json_loads(s)
    if direct is not None:
        return s, "direct"

    fenced = _strip_json_markdown_fence(s)
    if fenced:
        fd = _try_json_loads(fenced)
        if fd is not None:
            return fenced.strip(), "markdown_fenced"

    start = s.find("{")
    if start != -1:
        balanced = _extract_balanced_object(s, start)
        if balanced:
            bd = _try_json_loads(balanced)
            if bd is not None:
                return balanced, "balanced_object"

    raise ValueError(
        "Could not extract a JSON object from the LLM response "
        "(tried direct parse, markdown fence, and first balanced {...})."
    )


def parse_vertical_slice_bundle_dict(
    raw_llm_text: str,
    *,
    required_keys: tuple[str, ...],
) -> tuple[dict[str, Any], str, str]:
    """
    Extract JSON text from ``raw_llm_text``, parse, and enforce ``required_keys``.

    Returns ``(data, json_text, extraction_kind)``.
    """
    json_text, kind = extract_vertical_slice_json_text(raw_llm_text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Extracted payload ({kind}) is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("Vertical slice JSON must be a JSON object.")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"LLM JSON missing keys: {missing}")
    return data, json_text, kind


def write_llm_bundle_raw_artifact(
    artifact_dir: Path | str | None,
    *,
    sequence: int,
    raw: str,
) -> Path | None:
    """
    Write ``raw`` to ``artifact_dir / f\"llm_bundle_raw_{sequence:02d}.txt\"``.

    ``artifact_dir`` may be None (no-op, returns None).
    """
    if artifact_dir is None:
        return None
    d = Path(artifact_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"llm_bundle_raw_{sequence:02d}.txt"
    path.write_text(raw, encoding="utf-8")
    return path
