"""
Mode-specific instructions appended to LLM planner repair prompts.

Keeps deterministic execution and canonical actions; only the *guidance text*
changes per :class:`~forge.failure_classification.FailureClassification`.
"""

from __future__ import annotations

from typing import Any

from forge.failure_classification import FailureClassification, RepairMode

_MODE_BLOCKS: dict[RepairMode, str] = {
    "format_fix": (
        "### REPAIR MODE: format_fix\n"
        "The failure is likely malformed structured output (JSON, milestone lines, or "
        "Forge action syntax) — NOT missing product logic.\n"
        "- Emit strictly valid, minimal structured content.\n"
        "- Do not change product behavior until parse/validation succeeds.\n"
        "- Prefer fixing escaping, delimiters, and required fields only.\n"
    ),
    "syntax_fix": (
        "### REPAIR MODE: syntax_fix\n"
        "The codebase failed to parse, compile, or import — fix the smallest edit set "
        "that restores valid Python (or other language) syntax.\n"
        "- Do not redesign behavior; unblock syntax/compile/test collection first.\n"
        "- Keep edits in allowed paths; preserve public interfaces implied by tests.\n"
    ),
    "behavior_fix": (
        "### REPAIR MODE: behavior_fix\n"
        "Tests or behavioral checks failed; structure and parsing are OK.\n"
        "- Change implementation only to satisfy failing assertions or CLI behavior.\n"
        "- Minimal diff; do not edit docs or validation rules unless the task requires it.\n"
    ),
    "missing_impl": (
        "### REPAIR MODE: missing_impl\n"
        "The implementation is insufficient: it may pass shallow checks but omits required "
        "behavior (e.g. file I/O, parsing, or core logic).\n"
        "- Replace placeholder / CLI-only scaffolding with real logic that satisfies the "
        "milestone objective and validation.\n"
        "- Do not add new files unless necessary; prefer completing existing modules.\n"
    ),
    "validation_bug": (
        "### REPAIR MODE: validation_bug\n"
        "Failure pattern suggests Forge validation or parsing mismatch (e.g. substring / "
        "quoting / path rules), not necessarily wrong application code.\n"
        "- If the task is to fix product code, first verify validation expectations match "
        "what was written.\n"
        "- Prefer adjusting milestone validation lines or file content consistency — "
        "do not paper over with unrelated refactors.\n"
    ),
    "no_op_repair": (
        "### REPAIR MODE: no_op_repair (human required)\n"
        "The planner produced an identical plan to the previous failed attempt.\n"
        "- Do NOT repeat the same actions.\n"
        "- You must change strategy materially or ask for human clarification.\n"
    ),
    "planner_output_bug": (
        "### REPAIR MODE: planner_output_bug\n"
        "The plan has structural issues: duplicates, empty payloads, or excessive "
        "normalization warnings.\n"
        "- Produce fewer, clearer actions; each must be complete and non-redundant.\n"
        "- Follow delimiter and path rules exactly.\n"
    ),
    "unknown_failure": (
        "### REPAIR MODE: unknown_failure\n"
        "Failure class is unclear from diagnostics.\n"
        "- Diagnose from gate output and apply errors below; propose the smallest fix.\n"
        "- If uncertain, prefer minimal code changes over broad rewrites.\n"
    ),
}


def _stub_detection_prompt_extra(details: dict[str, Any]) -> str:
    if not details.get("stub_detection_results"):
        return ""
    lines = [
        "\n### STUB DETECTION (Forge deterministic analysis)\n",
        "The previous implementation is only a structural stub and does not implement "
        "required behavior.\n",
        "You must implement full logic, not CLI scaffolding (argparse/main alone is not enough).\n",
    ]
    req = (details.get("requirement_summary") or "").strip()
    if req:
        lines.append("\n**Requirement summary (from milestone):**\n" + req + "\n")
    lines.append("\n**Per-file signals:**\n")
    for r in details["stub_detection_results"]:
        lines.append(
            f"  - {r.get('rel_path')}: confidence={r.get('confidence')!r} "
            f"signals={r.get('signals')!r}\n"
        )
    art = (details.get("stub_detection_artifact") or "").strip()
    if art:
        lines.append(f"\nFull JSON: {art}\n")
    return "".join(lines)


def repair_mode_prompt_block(classification: FailureClassification) -> str:
    """LLM-facing block for this classification (internal prompt text only)."""
    base = _MODE_BLOCKS.get(classification.mode, _MODE_BLOCKS["unknown_failure"])
    meta = (
        f"\n(classifier mode={classification.mode!r} phase={classification.phase!r} "
        f"signals={list(classification.signals)!r})\n"
    )
    stub_x = ""
    if classification.mode == "missing_impl":
        stub_x = _stub_detection_prompt_extra(classification.details)
    return base + meta + stub_x
