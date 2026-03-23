"""
Deterministic failure classification for task repair loops.

Maps apply errors and gate results into a small set of repair modes so the
planner can be re-prompted with narrow constraints (not one generic retry blob).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RepairMode = Literal[
    "format_fix",
    "syntax_fix",
    "behavior_fix",
    "missing_impl",
    "validation_bug",
    "no_op_repair",
    "planner_output_bug",
    "unknown_failure",
]

Phase = Literal["apply", "gates"]


@dataclass(frozen=True)
class FailureClassification:
    """Structured result from :func:`classify_repair_failure`."""

    mode: RepairMode
    phase: Phase
    signals: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "phase": self.phase,
            "signals": list(self.signals),
            "details": dict(self.details),
        }


def _lower_join(parts: list[str]) -> str:
    return " ".join(p.lower() for p in parts if p)


def _classify_apply_errors(errors: list[str]) -> FailureClassification | None:
    if not errors:
        return None
    blob = _lower_join(errors)
    signals: list[str] = []

    if any(
        x in blob
        for x in (
            "json extraction",
            "json parse",
            "invalid json",
            "malformed",
            "milestone",
            "parse error",
            "forge validation line",
            "action parse",
            "vertical slice json",
            "extract a single",
        )
    ):
        signals.append("parse_or_format_in_apply_errors")
        return FailureClassification(
            "format_fix", "apply", tuple(signals), {"error_sample": errors[0][:500]}
        )

    if any(
        x in blob
        for x in (
            "syntaxerror",
            "indentationerror",
            "compile(",
            "invalid syntax",
            "unexpected eof",
            "expected ':'",
        )
    ):
        signals.append("syntax_or_compile_in_errors")
        return FailureClassification(
            "syntax_fix", "apply", tuple(signals), {"error_sample": errors[0][:500]}
        )

    if "writefileintegrity" in blob or "integrityerror" in blob:
        signals.append("write_integrity")
        return FailureClassification(
            "validation_bug", "apply", tuple(signals), {"error_sample": errors[0][:500]}
        )

    if "llm planner" in blob or "planner output" in blob:
        signals.append("planner_string_in_errors")
        return FailureClassification(
            "planner_output_bug", "apply", tuple(signals), {"error_sample": errors[0][:500]}
        )

    return FailureClassification(
        "unknown_failure", "apply", ("apply_failed",), {"error_sample": errors[0][:500]}
    )


def _gate_output_blob(gate_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for g in gate_results:
        parts.append(str(g.get("message", "")))
        det = g.get("details") or {}
        parts.append(str(det.get("output", "")))
        parts.append(str(det.get("command", "")))
    return _lower_join(parts)


def _classify_gate_results(
    gate_results: list[dict[str, Any]],
    *,
    behavior_heavy: bool = False,
) -> FailureClassification | None:
    if not gate_results:
        return None
    blob = _gate_output_blob(gate_results)
    signals: list[str] = []

    mv_fail = any(
        g.get("name") == "milestone_validation" and not g.get("ok")
        for g in gate_results
    )

    if mv_fail:
        mv_msg = next(
            (
                str(g.get("message", ""))
                for g in gate_results
                if g.get("name") == "milestone_validation"
            ),
            "",
        )
        low_mv = mv_msg.lower()
        if "unquote_applied" in low_mv or "raw_substring_field" in low_mv:
            signals.append("validation_diag_suggests_parse_bug")
            return FailureClassification(
                "validation_bug",
                "gates",
                tuple(signals),
                {"milestone_validation_message": mv_msg[:800]},
            )
        if "missing substring" in low_mv and "'" in mv_msg:
            signals.append("quoted_substring_in_validation_error")
            return FailureClassification(
                "validation_bug",
                "gates",
                tuple(signals),
                {"milestone_validation_message": mv_msg[:800]},
            )
        if "json" in low_mv or "parse" in low_mv:
            signals.append("validation_message_mentions_parse")
            return FailureClassification(
                "format_fix",
                "gates",
                tuple(signals),
                {"milestone_validation_message": mv_msg[:800]},
            )

    if any(
        x in blob
        for x in (
            "syntaxerror",
            "indentationerror",
            "invalid syntax",
            "error while compiling",
        )
    ):
        signals.append("syntax_in_test_output")
        return FailureClassification("syntax_fix", "gates", tuple(signals), {})

    if "notimplementederror" in blob or "todo" in blob or "not implemented" in blob:
        signals.append("stub_signal_in_output")
        return FailureClassification("missing_impl", "gates", tuple(signals), {})

    if "no tests ran" in blob or "exit code 5" in blob:
        signals.append("no_tests_ran")
        if behavior_heavy:
            return FailureClassification(
                "missing_impl",
                "gates",
                tuple(signals + ["behavior_heavy_no_tests"]),
                {},
            )
        return FailureClassification("validation_bug", "gates", tuple(signals), {})

    if "assertionerror" in blob or "assert " in blob or "failed" in blob:
        signals.append("test_assertion_failure")
        return FailureClassification("behavior_fix", "gates", tuple(signals), {})

    if any(not g.get("ok") for g in gate_results):
        return FailureClassification(
            "unknown_failure", "gates", ("gate_failed",), {"blob_prefix": blob[:400]}
        )

    return None


def classify_repair_failure(
    *,
    phase: Phase,
    apply_errors: list[str] | None = None,
    gate_results: list[dict[str, Any]] | None = None,
    attempt: int = 1,
    previous_plan_hash: str | None = None,
    current_plan_hash: str | None = None,
    planner_metadata: dict[str, Any] | None = None,
    behavior_heavy: bool = False,
) -> FailureClassification:
    """
    Produce a single repair mode. ``no_op_repair`` wins when the replan is identical
    to the previous attempt's plan (ineffective retry).
    """
    if (
        attempt > 1
        and previous_plan_hash
        and current_plan_hash
        and previous_plan_hash == current_plan_hash
    ):
        return FailureClassification(
            "no_op_repair",
            phase,
            ("identical_plan_hash",),
            {
                "plan_hash": current_plan_hash[:24] + "...",
                "attempt": attempt,
            },
        )

    meta = planner_metadata or {}
    notes = meta.get("normalization_notes") or []
    if isinstance(notes, list) and len(notes) >= 8:
        return FailureClassification(
            "planner_output_bug",
            phase,
            ("many_normalization_notes",),
            {"normalization_note_count": len(notes)},
        )

    if phase == "apply":
        c = _classify_apply_errors(list(apply_errors or []))
        return c or FailureClassification("unknown_failure", "apply", (), {})

    c = _classify_gate_results(list(gate_results or []), behavior_heavy=behavior_heavy)
    return c or FailureClassification("unknown_failure", "gates", (), {})


def detect_identical_repair_plan(
    *,
    attempt: int,
    previous_plan_hash: str | None,
    current_plan_hash: str | None,
) -> bool:
    """True when the new reviewed plan is byte-identical to the last one (canonical hash)."""
    if attempt <= 1:
        return False
    if not previous_plan_hash or not current_plan_hash:
        return False
    return previous_plan_hash == current_plan_hash
