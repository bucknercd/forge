"""
Structured feedback for task-scoped repair loops (same task, new reviewed plan).

Persisted under ``.system/task_feedback/`` for inspection after failures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forge.paths import Paths


def task_feedback_dir() -> Path:
    d = Paths.SYSTEM_DIR / "task_feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def persist_task_feedback(
    milestone_id: int, task_id: int, attempt: int, payload: dict[str, Any]
) -> Path:
    """Write one JSON file per attempt (overwrite if same attempt re-run)."""
    path = task_feedback_dir() / f"m{milestone_id}_t{task_id}_a{attempt}.json"
    body = {
        "milestone_id": milestone_id,
        "task_id": task_id,
        "attempt": attempt,
        **payload,
    }
    path.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_repair_context(
    milestone_id: int,
    task_id: int,
    attempt: int,
    *,
    gate_results: list[dict[str, Any]] | None = None,
    apply_errors: list[str] | None = None,
    apply_ok: bool = True,
    artifact_test_path: str | None = None,
    extra_message: str | None = None,
) -> dict[str, Any]:
    """
    Structured context for the next planner call (esp. LLM).

    ``attempt`` is 1-based; the first plan uses ``repair_context=None``.
    """
    return {
        "milestone_id": milestone_id,
        "task_id": task_id,
        "previous_attempt": attempt,
        "apply_ok": apply_ok,
        "apply_errors": list(apply_errors or []),
        "gate_results": list(gate_results or []),
        "artifact_test_path": artifact_test_path,
        "extra_message": extra_message,
    }


def repair_context_to_prompt_appendix(ctx: dict[str, Any]) -> str:
    """Plain-text block appended to LLM planner prompts when repairing."""
    lines = [
        "\n---\nPREVIOUS ATTEMPT FAILED — produce a revised action list for the SAME task.\n",
        f"Previous attempt number: {ctx.get('previous_attempt')}\n",
    ]
    if ctx.get("apply_errors"):
        lines.append("Apply-phase errors:\n")
        for e in ctx["apply_errors"]:
            lines.append(f"  - {e}\n")
    gr = ctx.get("gate_results") or []
    if gr:
        lines.append("Gate results:\n")
        for g in gr:
            name = g.get("name", "gate")
            ok = g.get("ok")
            msg = g.get("message", "")
            lines.append(f"  - {name}: ok={ok} — {msg}\n")
            det = g.get("details") or {}
            out = det.get("output")
            if out:
                snippet = str(out)[:800]
                lines.append(f"    output snippet:\n{snippet}\n")
            cmd = det.get("command")
            if cmd:
                lines.append(f"    command: {cmd}\n")
    if ctx.get("artifact_test_path"):
        lines.append(f"Generated artifact test file (may need fixing): {ctx['artifact_test_path']}\n")
    if ctx.get("extra_message"):
        lines.append(f"Note: {ctx['extra_message']}\n")
    lines.append(
        "\nRevise the plan to fix the failure. Keep changes minimal and bounded to allowed paths.\n"
    )
    return "".join(lines)
