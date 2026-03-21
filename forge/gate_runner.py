from __future__ import annotations

import shlex
import subprocess
from typing import Any

from forge.validator import Validator


def run_gates_for_milestone(
    milestone_id: int,
    *,
    run_validation_gate: bool = False,
    test_command: str | None = None,
    timeout_seconds: int = 120,
    output_max_chars: int = 1200,
) -> list[dict[str, Any]]:
    """
    Run explicit post-apply gates. Returns deterministic structured results.
    """
    results: list[dict[str, Any]] = []
    if run_validation_gate:
        ok, reason = Validator.validate_milestone_with_report(milestone_id)
        results.append(
            {
                "name": "milestone_validation",
                "ok": bool(ok),
                "message": "Milestone validation passed." if ok else reason,
                "details": {"milestone_id": milestone_id},
            }
        )

    if test_command:
        argv = shlex.split(test_command)
        if not argv:
            results.append(
                {
                    "name": "repo_test_command",
                    "ok": False,
                    "message": "Empty test command.",
                    "details": {"command": test_command},
                }
            )
        else:
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
                results.append(
                    {
                        "name": "repo_test_command",
                        "ok": ok,
                        "message": (
                            "Repository test command passed."
                            if ok
                            else f"Repository test command failed with exit code {proc.returncode}."
                        ),
                        "details": {
                            "command": test_command,
                            "returncode": proc.returncode,
                            "output": output,
                        },
                    }
                )
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "name": "repo_test_command",
                        "ok": False,
                        "message": f"Repository test command timed out after {timeout_seconds}s.",
                        "details": {"command": test_command, "timeout_seconds": timeout_seconds},
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "name": "repo_test_command",
                        "ok": False,
                        "message": f"Failed to run repository test command: {exc}",
                        "details": {"command": test_command},
                    }
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
