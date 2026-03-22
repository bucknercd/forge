"""
Normalize near-miss LLM planner action strings into canonical forge action lines.

Only unambiguous repairs are applied; ambiguous output raises ValueError with the
bad action and expected grammar. Execution still uses :func:`parse_forge_action_line`.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Final

from forge.execution.parse import TARGETS
from forge.paths import Paths

_SECTION_CMDS: Final[frozenset[str]] = frozenset({"append_section", "replace_section"})
_HEADING_LINE: Final[re.Pattern[str]] = re.compile(r"^##\s+(.+)$")


def _first_non_empty_line_and_rest(body: str) -> tuple[str | None, str]:
    if not body:
        return None, ""
    lines = body.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None, ""
    first = lines[i]
    rest = "\n".join(lines[i + 1 :])
    return first, rest


def normalize_llm_planner_action_line(raw: str) -> tuple[str, list[str]]:
    """
    Return ``(canonical_line, repair_notes)``.

    Repairs **only** the common LLM mistake:

        append_section <target> | ## <Heading>\\n<body>

    i.e. ``<Section Heading>`` was omitted before ``|`` but the body begins with a
    markdown ``##`` line. In that case the heading is inferred from that line and
    the canonical form is:

        append_section <target> <Section Heading> | <rest of body>

    Same for ``replace_section``. Any other malformed line is left unchanged so the
    strict parser can reject it with its usual diagnostics — except when the
    two-token form is detected but inference is impossible: then this raises
    :class:`ValueError` with an explicit message.
    """
    warnings: list[str] = []
    # Leading strip only: stripping the full line would remove a trailing space after
    # ``|``, breaking ``cmd target | `` (empty body) detection and `` | `` matching.
    line = raw.lstrip()
    if " | " not in line:
        return raw, []

    left, body = line.split(" | ", 1)
    parts = left.split()
    if len(parts) >= 3:
        return raw, []
    if len(parts) != 2:
        return raw, []

    cmd = parts[0].lower()
    target = parts[1].lower()
    if cmd not in _SECTION_CMDS or target not in TARGETS:
        return raw, []

    first_line, rest = _first_non_empty_line_and_rest(body)
    if first_line is None:
        raise ValueError(
            f"{cmd} is missing the section heading before '|' (got only "
            f"{cmd!r} and {target!r}). "
            "Expected: append_section|replace_section <target> <Section Heading> | <body>\n"
            f"Bad action: {raw!r}"
        )

    m = _HEADING_LINE.match(first_line.strip())
    if not m:
        raise ValueError(
            f"{cmd} is missing the section heading before '|'. "
            "Either use the full form:\n"
            f"  {cmd} <target> <Section Heading> | <body>\n"
            "or put the heading as the first non-empty line of the body as "
            "exactly one markdown H2 line: ## <Section Heading>\n"
            f"Bad action: {raw!r}"
        )

    heading = m.group(1).strip()
    if not heading:
        raise ValueError(
            f"Empty heading after '##' in body for {cmd}; cannot infer section heading.\n"
            f"Bad action: {raw!r}"
        )

    canonical = f"{cmd} {target} {heading} | {rest}"
    warnings.append(
        f"Repaired missing <Section Heading> before '|': inferred {heading!r} from "
        "first ## line in body."
    )
    return canonical, warnings


def persist_llm_planner_raw_on_failure(
    raw_output: str, milestone_id: int, *, reason: str
) -> Path | None:
    """
    Write raw LLM planner output when planning fails (JSON/parse/normalize errors).
    """
    try:
        root = Paths.SYSTEM_DIR / "results" / "llm_planner_failures"
        root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = root / f"m{milestone_id}_{ts}.txt"
        path.write_text(
            f"reason: {reason}\n\n--- raw model output ---\n\n{raw_output}",
            encoding="utf-8",
        )
        return path
    except OSError:
        return None
