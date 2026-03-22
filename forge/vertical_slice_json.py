"""
Extract and validate JSON payloads from LLM responses for vertical-slice bundle generation.

Conservative extraction only (no eval, no YAML, no fuzzy schema repair).
Brace matching follows JSON: only double-quoted strings (apostrophes inside values
do not affect depth — fixes false failures on ``it's``-style text).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


STRICT_JSON_RETRY_SUFFIX = (
    "\n\n### OUTPUT FORMAT (machine-readable internal transport — required)\n"
    "Return exactly ONE JSON object. No other characters before or after it.\n"
    "- Output must be parseable by Python json.loads() as a single value.\n"
    "- Do NOT wrap in markdown code fences (no ```).\n"
    "- Do NOT add explanations, headings, labels, or commentary.\n"
    "- Do NOT emit multiple top-level JSON values.\n"
    "- This payload is internal to Forge only; users will not see this text.\n"
)


class VerticalSliceLlmJsonError(ValueError):
    """Raised when the model output cannot be parsed as the vertical-slice bundle JSON."""

    def __init__(
        self,
        message: str,
        *,
        artifact_paths: list[str],
        extraction_diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.artifact_paths = list(artifact_paths)
        self.extraction_diagnostics = extraction_diagnostics or {}


@dataclass
class JsonExtractionTrace:
    """Internal debugging metadata (not product UX)."""

    strategies_attempted: list[str] = field(default_factory=list)
    selected_strategy: str = ""
    failure_reason: str = ""
    response_length: int = 0
    response_prefix: str = ""
    notes: list[str] = field(default_factory=list)


class JsonExtractFailure(ValueError):
    """Extraction produced no single unambiguous JSON object."""

    def __init__(self, message: str, *, trace: JsonExtractionTrace) -> None:
        super().__init__(message)
        self.trace = trace


def _try_json_loads_dict(s: str) -> dict[str, Any] | None:
    try:
        val = json.loads(s)
    except json.JSONDecodeError:
        return None
    if isinstance(val, dict):
        return val
    return None


def _try_direct_single_json_dict(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Stripped response must be exactly one JSON object, no trailing garbage."""
    t = raw.strip()
    if not t:
        return None
    try:
        dec = json.JSONDecoder()
        val, idx = dec.raw_decode(t)
    except json.JSONDecodeError:
        return None
    if not isinstance(val, dict):
        return None
    if t[idx:].strip():
        return None
    return t, val


def _strip_json_markdown_fence_full(text: str) -> str | None:
    """If the entire text is one ``` / ```json fence, return inner payload."""
    t = text.strip()
    if not t.startswith("```"):
        return None
    m = re.match(r"^```(?:json)?\s*\r?\n", t, re.IGNORECASE)
    if not m:
        first = t.split("\n", 1)
        if len(first) < 2:
            return None
        rest = first[1]
    else:
        rest = t[m.end() :]
    lines = rest.splitlines()
    inner_lines: list[str] = []
    for line in lines:
        if line.strip() == "```":
            inner = "\n".join(inner_lines).strip()
            return inner if inner else None
        inner_lines.append(line)
    return None


_FENCE_OPEN_ANYWHERE = re.compile(r"```(?:json)?\s*\r?\n", re.IGNORECASE)


def _extract_fenced_payloads_anywhere(text: str) -> list[str]:
    """Inner payloads for ``` / ```json ... ``` blocks (anywhere in text)."""
    out: list[str] = []
    pos = 0
    while True:
        m = _FENCE_OPEN_ANYWHERE.search(text, pos)
        if not m:
            break
        start = m.end()
        nl = text.find("\n```", start)
        if nl != -1:
            inner = text[start:nl].strip()
            pos = nl + 1
        else:
            bare = text.find("```", start)
            if bare == -1:
                break
            inner = text[start:bare].strip()
            pos = bare + 3
        if inner:
            out.append(inner)
    return out


def _extract_balanced_json_object(s: str, start: int) -> str | None:
    """
    Balanced ``{...}`` using JSON rules: only ``"`` starts/ends strings.
    """
    if start >= len(s) or s[start] != "{":
        return None
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < len(s):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
        i += 1
    return None


def _longest_balanced_json_dict_candidates(s: str) -> list[str]:
    seen: set[str] = set()
    blocks: list[str] = []
    for i, c in enumerate(s):
        if c != "{":
            continue
        block = _extract_balanced_json_object(s, i)
        if block is None:
            continue
        if _try_json_loads_dict(block) is None:
            continue
        if block not in seen:
            seen.add(block)
            blocks.append(block)
    return blocks


def _pick_longest_unique_block(blocks: list[str]) -> str:
    if not blocks:
        raise ValueError(
            "no balanced {...} substring parsed as a JSON object (truncated or malformed JSON?)"
        )
    max_len = max(len(b) for b in blocks)
    at_max = [b for b in blocks if len(b) == max_len]
    uniq = set(at_max)
    if len(uniq) > 1:
        raise ValueError(
            f"ambiguous: {len(uniq)} distinct JSON objects tie for longest length; refuse to guess"
        )
    return at_max[0]


def _format_extract_failure(trace: JsonExtractionTrace, reason: str) -> str:
    trace.failure_reason = reason
    parts = [
        "Could not extract a single unambiguous JSON object from the LLM response.",
        f"strategies_attempted={trace.strategies_attempted}",
        f"response_length={trace.response_length}",
        f"response_prefix={trace.response_prefix}",
    ]
    if trace.notes:
        parts.append("notes=" + "; ".join(trace.notes))
    parts.append(f"reason={reason}")
    return " ".join(parts)


@dataclass
class VerticalSliceJsonExtractResult:
    json_text: str
    kind: str
    trace: JsonExtractionTrace


def extract_vertical_slice_json_inner(raw: str) -> VerticalSliceJsonExtractResult:
    """
    Extract exactly one JSON object text. Raises :class:`JsonExtractFailure` on failure.
    """
    trace = JsonExtractionTrace()
    trace.response_length = len(raw or "")
    s = raw.strip() if raw else ""
    trace.response_prefix = repr(s[:200]) if s else "''"

    if not s:
        trace.strategies_attempted.append("direct")
        raise JsonExtractFailure(
            _format_extract_failure(trace, "empty response"), trace=trace
        )

    # 1) Direct — whole string is one JSON object
    trace.strategies_attempted.append("direct")
    direct = _try_direct_single_json_dict(s)
    if direct is not None:
        jt, _ = direct
        trace.selected_strategy = "direct"
        return VerticalSliceJsonExtractResult(json_text=jt, kind="direct", trace=trace)

    # 2) Whole response is one markdown fence
    trace.strategies_attempted.append("markdown_fenced_full")
    fenced_full = _strip_json_markdown_fence_full(s)
    if fenced_full:
        fd = _try_json_loads_dict(fenced_full.strip())
        if fd is not None:
            trace.selected_strategy = "markdown_fenced_full"
            return VerticalSliceJsonExtractResult(
                json_text=fenced_full.strip(),
                kind="markdown_fenced",
                trace=trace,
            )

    # 3) Embedded fenced blocks — exactly one may parse as a JSON object
    trace.strategies_attempted.append("markdown_fenced_embedded")
    payloads = _extract_fenced_payloads_anywhere(s)
    trace.notes.append(f"fenced_block_count={len(payloads)}")
    dict_payloads: list[str] = []
    for p in payloads:
        st = p.strip()
        if _try_json_loads_dict(st) is not None:
            dict_payloads.append(st)
    uniq = list(dict.fromkeys(dict_payloads))
    if len(uniq) > 1:
        raise JsonExtractFailure(
            _format_extract_failure(
                trace,
                f"ambiguous: {len(uniq)} fenced blocks each parse as a JSON object",
            ),
            trace=trace,
        )
    if len(uniq) == 1:
        trace.selected_strategy = "markdown_fenced_embedded"
        return VerticalSliceJsonExtractResult(
            json_text=uniq[0], kind="markdown_fenced", trace=trace
        )

    # 4) Longest balanced JSON object
    trace.strategies_attempted.append("balanced_longest")
    try:
        blocks = _longest_balanced_json_dict_candidates(s)
        trace.notes.append(f"balanced_parseable_blocks={len(blocks)}")
        winner = _pick_longest_unique_block(blocks)
    except ValueError as exc:
        raise JsonExtractFailure(
            _format_extract_failure(trace, str(exc)), trace=trace
        ) from exc

    trace.selected_strategy = "balanced_longest"
    return VerticalSliceJsonExtractResult(
        json_text=winner, kind="balanced_object", trace=trace
    )


def extract_vertical_slice_json_text(raw: str) -> tuple[str, str]:
    """Return ``(json_text, extraction_kind)`` — for planner and tests."""
    r = extract_vertical_slice_json_inner(raw)
    return r.json_text, r.kind


def parse_vertical_slice_bundle_dict(
    raw_llm_text: str,
    *,
    required_keys: tuple[str, ...],
) -> tuple[dict[str, Any], str, str, JsonExtractionTrace]:
    """
    Extract JSON, parse, enforce ``required_keys``.

    Returns ``(data, json_text, extraction_kind, trace)``.

    Raises :class:`JsonExtractFailure` if extraction fails;
    :class:`ValueError` if JSON invalid after extraction or keys missing.
    """
    res = extract_vertical_slice_json_inner(raw_llm_text)
    try:
        data = json.loads(res.json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Extracted payload ({res.kind}) is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("Vertical slice JSON must be a JSON object.")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"LLM JSON missing keys: {missing}")
    return data, res.json_text, res.kind, res.trace


def write_llm_bundle_raw_artifact(
    artifact_dir: Path | str | None,
    *,
    sequence: int,
    raw: str,
) -> Path | None:
    if artifact_dir is None:
        return None
    d = Path(artifact_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"llm_bundle_raw_{sequence:02d}.txt"
    path.write_text(raw, encoding="utf-8")
    return path


def write_llm_bundle_extraction_debug_artifact(
    artifact_dir: Path | str | None,
    *,
    sequence: int,
    trace: JsonExtractionTrace | None,
    error_message: str,
) -> Path | None:
    """Internal extraction diagnostics next to raw LLM dumps."""
    if artifact_dir is None:
        return None
    d = Path(artifact_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"llm_bundle_extract_debug_{sequence:02d}.txt"
    t = trace or JsonExtractionTrace()
    lines = [
        error_message,
        "",
        f"strategies_attempted={t.strategies_attempted}",
        f"selected_strategy={t.selected_strategy!r}",
        f"response_length={t.response_length}",
        f"response_prefix={t.response_prefix}",
        f"notes={t.notes}",
        f"failure_reason={t.failure_reason}",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
