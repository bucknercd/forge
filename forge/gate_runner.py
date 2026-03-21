from __future__ import annotations

import shlex
import subprocess
from typing import Any

from forge.run_events import VALIDATION_COMPLETED, VALIDATION_STARTED, as_emitter
from forge.validator import Validator


def run_gates_for_milestone(
    milestone_id: int,
    *,
    run_validation_gate: bool = False,
    test_command: str | None = None,
    timeout_seconds: int = 120,
    output_max_chars: int = 1200,
    event_bus: Any = None,
) -> list[dict[str, Any]]:
    """
    Run explicit post-apply gates. Returns deterministic structured results.
    """
    bus = as_emitter(event_bus)
    results: list[dict[str, Any]] = []
    if run_validation_gate:
        bus.emit(VALIDATION_STARTED, name="milestone_validation")
        ok, reason = Validator.validate_milestone_with_report(milestone_id)
        msg = "Milestone validation passed." if ok else reason
        results.append(
            {
                "name": "milestone_validation",
                "ok": bool(ok),
                "message": msg,
                "details": {"milestone_id": milestone_id},
            }
        )
        bus.emit(
            VALIDATION_COMPLETED,
            name="milestone_validation",
            ok=bool(ok),
            message=msg,
        )

    if test_command:
        argv = shlex.split(test_command)
        if not argv:
            bus.emit(VALIDATION_STARTED, name="repo_test_command")
            results.append(
                {
                    "name": "repo_test_command",
                    "ok": False,
                    "message": "Empty test command.",
                    "details": {"command": test_command},
                }
            )
            bus.emit(
                VALIDATION_COMPLETED,
                name="repo_test_command",
                ok=False,
                message="Empty test command.",
            )
        else:
            bus.emit(VALIDATION_STARTED, name="repo_test_command")
            try:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                output = (proc.stdout or "") + (proc.stderr or "")
                max_len = output_max_chars
                if len(output) > max_len:
                    output = output[:max_len] + "\n... [output truncated]"
                ok = proc.returncode == 0
                msg_ok = "Repository test command passed."
                msg_fail = f"Repository test command failed with exit code {proc.returncode}."
                results.append(
                    {
                        "name": "repo_test_command",
                        "ok": ok,
                        "message": msg_ok if ok else msg_fail,
                        "details": {
                            "command": test_command,
                            "returncode": proc.returncode,
                            "output": output,
                        },
                    }
                )
                bus.emit(
                    VALIDATION_COMPLETED,
                    name="repo_test_command",
                    ok=ok,
                    message=msg_ok if ok else msg_fail,
                )
            except subprocess.TimeoutExpired:
                msg = f"Repository test command timed out after {timeout_seconds}s."
                results.append(
                    {
                        "name": "repo_test_command",
                        "ok": False,
                        "message": msg,
                        "details": {"command": test_command, "timeout_seconds": timeout_seconds},
                    }
                )
                bus.emit(
                    VALIDATION_COMPLETED,
                    name="repo_test_command",
                    ok=False,
                    message=msg,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"Failed to run repository test command: {exc}"
                results.append(
                    {
                        "name": "repo_test_command",
                        "ok": False,
                        "message": msg,
                        "details": {"command": test_command},
                    }
                )
                bus.emit(
                    VALIDATION_COMPLETED,
                    name="repo_test_command",
                    ok=False,
                    message=msg,
                )

    return results


def summarize_gate_results(gates: list[dict[str, Any]]) -> str:
    if not gates:
        return "No gates executed."
    passed = sum(1 for g in gates if g.get("ok"))
    failed = sum(1 for g in gates if not g.get("ok"))
    parts = []
    for g in gates:
        name = g.get("name", "gate")
        status = "pass" if g.get("ok") else "fail"
        parts.append(f"{name}={status}")
    return f"{passed} passed, {failed} failed ({', '.join(parts)})"
