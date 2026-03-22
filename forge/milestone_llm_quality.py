"""
Heuristics and normalization for LLM-produced milestone markdown (vertical slice)
and milestone synthesis JSON.

Keeps the real parser strict; this module only repairs common variants and rejects
obviously non-productive / bootstrap-only plans.
"""

from __future__ import annotations

import re
from forge.design_manager import Milestone


class WeakMilestonePlanError(ValueError):
    """Raised when parsed milestones are structurally OK but fail product-quality gates."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages) if messages else "weak milestone plan")


# --- Normalization (pre-parser) ---

_FORGE_HEADER_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^#{1,6}\s*Forge\s+Actions\s*:?\s*$", re.IGNORECASE),
        "- **Forge Actions**:",
    ),
    (
        re.compile(r"^#{1,6}\s*Forge\s+Validation\s*:?\s*$", re.IGNORECASE),
        "- **Forge Validation**:",
    ),
    (
        re.compile(r"^\*{0,2}Forge\s+Actions\*{0,2}\s*:?\s*$", re.IGNORECASE),
        "- **Forge Actions**:",
    ),
    (
        re.compile(r"^\*{0,2}Forge\s+Validation\*{0,2}\s*:?\s*$", re.IGNORECASE),
        "- **Forge Validation**:",
    ),
    (
        re.compile(r"^-\s*\*{2}Forge\s+Actions\*{2}\s*$", re.IGNORECASE),
        "- **Forge Actions**:",
    ),
    (
        re.compile(r"^-\s*\*{2}Forge\s+Validation\*{2}\s*$", re.IGNORECASE),
        "- **Forge Validation**:",
    ),
]

_MILESTONE_HEADING_RE = re.compile(r"^##\s+Milestone\s+\d+\s*:\s*.+$")


def _rewrite_forge_header_line(stripped: str) -> tuple[str | None, list[str]]:
    """
    If ``stripped`` is a Forge Actions / Forge Validation header variant, return the
    canonical ``- **Forge …**:` line (column 0).
    """
    warns: list[str] = []
    for pattern, repl in _FORGE_HEADER_SUBSTITUTIONS:
        if pattern.match(stripped):
            return repl, [f"Normalized milestone header line {stripped!r} to {repl!r}."]
    if re.match(r"^-\s*\*\*Forge Actions\*\*\s*$", stripped, re.IGNORECASE):
        return "- **Forge Actions**:", ["Added missing colon to '- **Forge Actions**' line."]
    if re.match(r"^-\s*\*\*Forge Validation\*\*\s*$", stripped, re.IGNORECASE):
        return "- **Forge Validation**:", ["Added missing colon to '- **Forge Validation**' line."]
    if re.match(r"^Forge Actions\s*:?\s*$", stripped, re.IGNORECASE):
        return "- **Forge Actions**:", [f"Normalized plain header {stripped!r} to '- **Forge Actions**:'."]
    if re.match(r"^Forge Validation\s*:?\s*$", stripped, re.IGNORECASE):
        return "- **Forge Validation**:", [f"Normalized plain header {stripped!r} to '- **Forge Validation**:'."]
    return None, []


def normalize_milestone_markdown(md: str) -> tuple[str, list[str]]:
    """
    Repair common LLM variants so :class:`MilestoneService` can parse Forge lists.

    Handles:

    - ``**Forge Validation**``: (and similar) without a leading ``- `` — this otherwise
      leaves the parser inside **Forge Actions** and triggers false "expected '- '" errors.
    - Heading-style / hash / plain-text Forge section titles.
    - Indented list items (``  - action``) and ``*`` bullets under Forge Actions /
      Forge Validation → column-0 ``- `` bullets (parser-safe flat list).

    Returns ``(normalized_text, warning_messages)``.
    """
    if not (md or "").strip():
        return md, []
    warnings: list[str] = []
    out_lines: list[str] = []
    in_milestone = False
    forge_zone: str | None = None  # "actions" | "validation"

    for raw_line in md.splitlines():
        stripped = raw_line.strip()

        if stripped.startswith("## Milestone") and _MILESTONE_HEADING_RE.match(stripped):
            in_milestone = True
            forge_zone = None
            out_lines.append(raw_line)
            continue

        if in_milestone and stripped.startswith("# ") and not stripped.startswith("##"):
            in_milestone = False
            forge_zone = None

        rewritten, rw = _rewrite_forge_header_line(stripped)
        if rewritten is not None:
            warnings.extend(rw)
            nline = rewritten
        else:
            nline = raw_line

        nst = nline.strip()

        if in_milestone:
            if re.match(r"^-\s*\*\*Forge Actions\*\*:", nst, re.IGNORECASE):
                forge_zone = "actions"
                out_lines.append(nline)
                continue
            if re.match(r"^-\s*\*\*Forge Validation\*\*:", nst, re.IGNORECASE):
                forge_zone = "validation"
                out_lines.append(nline)
                continue
            if forge_zone and nst.startswith("- **"):
                if not re.match(
                    r"^-\s*\*\*Forge (Actions|Validation)\*\*:", nst, re.IGNORECASE
                ):
                    forge_zone = None

            if forge_zone and nst:
                indent_bullet = re.match(r"^(\s{2,})-\s+(.*)$", nline)
                if indent_bullet and not nst.startswith("- **"):
                    out_lines.append(f"- {indent_bullet.group(2).strip()}")
                    warnings.append(
                        "Flattened indented Forge Actions/Validation bullet to column-0 '- '."
                    )
                    continue
                star_bullet = re.match(r"^\s*\*\s+(.+)$", nline)
                if star_bullet and not nst.startswith("- **"):
                    out_lines.append(f"- {star_bullet.group(1).strip()}")
                    warnings.append("Normalized '*' bullet to '- ' in Forge list.")
                    continue

        out_lines.append(nline)

    normalized = "\n".join(out_lines)
    if md.endswith("\n") and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized, warnings


# --- Weak plan detection (vertical slice: parsed milestones with actions) ---

_DOC_ANCHOR_PREFIXES = (
    "append_section requirements",
    "append_section architecture",
    "append_section milestones",
    "append_section decisions",
    "replace_section requirements",
    "replace_section architecture",
    "replace_section milestones",
    "replace_section decisions",
)

_CODE_ROOTS = ("examples/", "src/", "scripts/", "tests/")


def _action_lower(line: str) -> str:
    return line.strip().lower()


def _is_mark_completion(action: str) -> bool:
    return action.startswith("mark_milestone_completed")


def _is_add_decision(action: str) -> bool:
    return action.startswith("add_decision")


def _has_forge_init_marker(action: str) -> bool:
    return "forge_init_marker" in action.lower()


def _is_doc_churn_action(action: str) -> bool:
    a = _action_lower(action)
    return any(a.startswith(p) for p in _DOC_ANCHOR_PREFIXES)


def _is_substantive_code_action(action: str) -> bool:
    """True if the action likely creates or edits code under allowed roots."""
    a = _action_lower(action)
    if not a or _is_mark_completion(a) or _is_add_decision(a):
        return False
    if _has_forge_init_marker(a):
        return False
    if a.startswith("write_file "):
        for root in _CODE_ROOTS:
            if a.startswith(f"write_file {root}"):
                return True
        return False
    for verb in (
        "insert_after_in_file ",
        "insert_before_in_file ",
        "replace_text_in_file ",
        "replace_block_in_file ",
        "replace_lines_in_file ",
    ):
        if not a.startswith(verb):
            continue
        for root in _CODE_ROOTS:
            if root in a:
                return True
    return False


def weak_parsed_milestone_plan_messages(
    milestones: list[Milestone],
    *,
    idea_context: str | None = None,
) -> list[str]:
    """
    Return human-readable rejection reasons for a parsed milestone plan, or [] if OK.

    Fails closed on template markers and doc-only / bookkeeping-only plans.
    """
    errors: list[str] = []
    all_actions: list[str] = []
    blob_parts: list[str] = []

    for m in milestones:
        blob_parts.extend(
            [m.title, m.objective, m.scope, m.validation, m.summary, *m.forge_actions]
        )
        all_actions.extend(m.forge_actions)

    combined_blob = "\n".join(blob_parts).lower()

    for i, m in enumerate(milestones, start=1):
        for a in m.forge_actions:
            if _has_forge_init_marker(a):
                errors.append(
                    f"Milestone {i} uses FORGE_INIT_MARKER (template/bootstrap only); "
                    "use real Forge Actions for the product."
                )

    substantive = [a for a in all_actions if _is_substantive_code_action(a)]
    if not substantive:
        errors.append(
            "No substantive code actions found (expected at least one write_file or "
            "bounded edit under examples/, src/, scripts/, or tests/). "
            "Milestones must deliver real project artifacts, not only doc edits."
        )

    # Doc-only milestones: every action is doc churn, mark_milestone_completed, or add_decision
    for i, m in enumerate(milestones, start=1):
        if not m.forge_actions:
            continue
        non_meta = [
            a
            for a in m.forge_actions
            if not _is_mark_completion(_action_lower(a))
            and not _is_add_decision(_action_lower(a))
        ]
        if not non_meta:
            continue
        if all(_is_doc_churn_action(a) for a in non_meta) and not any(
            _is_substantive_code_action(a) for a in m.forge_actions
        ):
            errors.append(
                f"Milestone {i} has only documentation append/replace actions; "
                "include implementation work (code under allowed paths)."
            )

    # Idea grounding: significant tokens from user idea should appear somewhere
    if idea_context and idea_context.strip():
        tokens = _significant_tokens_from_phrase(idea_context)
        if tokens:
            missing = [t for t in tokens if t not in combined_blob]
            if len(missing) == len(tokens):
                errors.append(
                    "Milestones do not reference the user's idea "
                    f"(expected terms like: {', '.join(sorted(tokens)[:6])}). "
                    "Ground every milestone in the requested product."
                )

    return errors


_STOPWORDS = frozenset(
    """
    the and for with from this that have will your into about when what which
    their them then than some such only also just been were being over after
    before under while here there where build make create small tool using use
    """.split()
)


def _significant_tokens_from_phrase(text: str) -> set[str]:
    """Tokens length >= 5 from idea/vision, excluding common English stopwords."""
    raw = {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 5}
    return {t for t in raw if t not in _STOPWORDS}


_SYNTH_STOP = _STOPWORDS | frozenset(
    """
    milestone milestones project documentation requirements architecture overview
    section update updates changes change improve improvements general various
    stuff things content base design log decisions
    """.split()
)


def _token_set(text: str, *, stop: frozenset[str] | None = None) -> set[str]:
    st = _SYNTH_STOP if stop is None else stop
    return {
        t
        for t in re.findall(r"[a-z0-9]{3,}", text.lower())
        if t not in st
    }


# Minimum domain tokens in requirements+architecture before we enforce grounding
_MIN_CONTEXT_TOKENS_FOR_GROUNDING = 14

# Titles that are roadmap bookkeeping only (normalized lowercased exact match on strip)
_BOOTSTRAP_ONLY_TITLES = frozenset(
    {
        "project setup",
        "initial setup",
        "repo setup",
        "repository setup",
        "bootstrap",
        "documentation",
        "documentation only",
        "docs only",
        "foundation",
        "milestone 1",
    }
)


def weak_synthesized_json_plan_messages(
    milestones: list[dict[str, str]],
    *,
    requirements_excerpt: str,
    architecture_excerpt: str,
) -> list[str]:
    """
    Hard rejection reasons for milestone-synthesis JSON (no Forge Actions yet).

    Requires some lexical overlap with requirements/architecture when context is rich enough.
    Rejects plans where every milestone title is generic bootstrap bookkeeping.
    """
    errors: list[str] = []
    if not milestones:
        return ["No milestones in synthesis response."]

    pool = _token_set(requirements_excerpt) | _token_set(architecture_excerpt)
    title_norms = {str(m.get("title", "")).strip().lower() for m in milestones if str(m.get("title", "")).strip()}
    if title_norms and title_norms <= _BOOTSTRAP_ONLY_TITLES:
        errors.append(
            "Every synthesized milestone title is generic bootstrap/doc bookkeeping; "
            "name milestones after concrete product deliverables from requirements/architecture."
        )

    if len(pool) >= _MIN_CONTEXT_TOKENS_FOR_GROUNDING:
        milestone_text = "\n".join(
            f"{m.get('title', '')} {m.get('objective', '')} {m.get('scope', '')} "
            f"{m.get('validation', '')}"
            for m in milestones
        )
        mtoks = _token_set(milestone_text)
        if not (mtoks & pool):
            errors.append(
                "Synthesized milestones do not reference terminology from requirements.md "
                "or architecture.md; regenerate with concrete, source-grounded milestones."
            )

    return errors


def milestone_lint_passes(content: str) -> bool:
    """True if ``content`` parses as milestones (used in tests / quick checks)."""
    from forge.design_manager import MilestoneService

    try:
        MilestoneService.parse_milestones(content)
    except ValueError:
        return False
    return True
