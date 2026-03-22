from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.paths import Paths


DEFAULT_TEST_TIMEOUT_SECONDS = 120
DEFAULT_TEST_OUTPUT_MAX_CHARS = 1200


@dataclass(frozen=True)
class ReviewedApplyPolicy:
    run_validation_gate: bool = False
    test_command: str | None = None
    test_timeout_seconds: int = DEFAULT_TEST_TIMEOUT_SECONDS
    test_output_max_chars: int = DEFAULT_TEST_OUTPUT_MAX_CHARS


_LLM_CLIENT_IDS = frozenset({"stub", "openai"})


@dataclass(frozen=True)
class TaskExecutionPolicy:
    """
    Task-scoped execution: artifact pytest generation + bounded repair attempts.

    Repair replanning is effective only when using an LLM planner; deterministic
    mode still runs artifact tests / gates once.
    """

    artifact_test_generation: bool = True
    max_repair_attempts: int = 3


@dataclass(frozen=True)
class PlannerPolicy:
    mode: str = "deterministic"  # deterministic | llm
    llm_client: str | None = None  # stub | openai
    llm_model: str | None = None  # non-secret model id for provider-backed clients
    require_review_for_nondeterministic: bool = False


def policy_file_path() -> Path:
    return Paths.BASE_DIR / "forge-policy.json"


def load_reviewed_apply_policy() -> tuple[ReviewedApplyPolicy, str | None]:
    """
    Load optional repository policy defaults.
    Returns (policy, error_message). When missing, returns defaults + None.
    """
    path = policy_file_path()
    if not path.exists():
        return ReviewedApplyPolicy(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return ReviewedApplyPolicy(), f"Invalid policy JSON in {path}: {exc}"

    if not isinstance(data, dict):
        return ReviewedApplyPolicy(), f"Invalid policy file {path}: top-level must be an object."

    section = data.get("reviewed_plan_apply", {})
    if section is None:
        section = {}
    if not isinstance(section, dict):
        return ReviewedApplyPolicy(), (
            f"Invalid policy file {path}: 'reviewed_plan_apply' must be an object."
        )

    try:
        run_validation = _get_bool(section, "run_validation_gate", default=False)
        test_command = _get_opt_str(section, "test_command", default=None)
        timeout = _get_positive_int(
            section, "test_timeout_seconds", default=DEFAULT_TEST_TIMEOUT_SECONDS
        )
        max_chars = _get_positive_int(
            section, "test_output_max_chars", default=DEFAULT_TEST_OUTPUT_MAX_CHARS
        )
    except ValueError as exc:
        return ReviewedApplyPolicy(), f"Invalid policy file {path}: {exc}"

    return ReviewedApplyPolicy(
        run_validation_gate=run_validation,
        test_command=test_command,
        test_timeout_seconds=timeout,
        test_output_max_chars=max_chars,
    ), None


def load_planner_policy() -> tuple[PlannerPolicy, str | None]:
    """
    Load optional planner defaults from repo policy.
    """
    path = policy_file_path()
    if not path.exists():
        return PlannerPolicy(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return PlannerPolicy(), f"Invalid policy JSON in {path}: {exc}"
    if not isinstance(data, dict):
        return PlannerPolicy(), f"Invalid policy file {path}: top-level must be an object."

    section = data.get("planner", {})
    if section is None:
        section = {}
    if not isinstance(section, dict):
        return PlannerPolicy(), f"Invalid policy file {path}: 'planner' must be an object."
    try:
        mode = _get_mode(section, "mode", default="deterministic")
        llm_client = _get_opt_str(section, "llm_client", default=None)
        if llm_client is not None and llm_client not in _LLM_CLIENT_IDS:
            raise ValueError(
                f"'llm_client' must be one of: {', '.join(sorted(_LLM_CLIENT_IDS))}."
            )
        llm_model = _get_opt_str(section, "llm_model", default=None)
        require_review = _get_bool(
            section, "require_review_for_nondeterministic", default=False
        )
    except ValueError as exc:
        return PlannerPolicy(), f"Invalid policy file {path}: {exc}"
    return PlannerPolicy(
        mode=mode,
        llm_client=llm_client,
        llm_model=llm_model,
        require_review_for_nondeterministic=require_review,
    ), None


def load_task_execution_policy() -> tuple[TaskExecutionPolicy, str | None]:
    path = policy_file_path()
    if not path.exists():
        return TaskExecutionPolicy(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return TaskExecutionPolicy(), f"Invalid policy JSON in {path}: {exc}"
    if not isinstance(data, dict):
        return TaskExecutionPolicy(), f"Invalid policy file {path}: top-level must be an object."
    section = data.get("task_execution", {})
    if section is None:
        section = {}
    if not isinstance(section, dict):
        return (
            TaskExecutionPolicy(),
            f"Invalid policy file {path}: 'task_execution' must be an object.",
        )
    try:
        gen = _get_bool(section, "artifact_test_generation", default=True)
        max_rep = _get_positive_int(section, "max_repair_attempts", default=3)
        if max_rep > 20:
            raise ValueError("'max_repair_attempts' must be <= 20.")
    except ValueError as exc:
        return TaskExecutionPolicy(), f"Invalid policy file {path}: {exc}"
    return TaskExecutionPolicy(
        artifact_test_generation=gen,
        max_repair_attempts=max_rep,
    ), None


def merge_planner_policy(base: PlannerPolicy, *, mode_override: str | None) -> PlannerPolicy:
    mode = mode_override or base.mode
    return PlannerPolicy(
        mode=mode,
        llm_client=base.llm_client,
        llm_model=base.llm_model,
        require_review_for_nondeterministic=base.require_review_for_nondeterministic,
    )


def merge_reviewed_apply_policy(
    base: ReviewedApplyPolicy,
    *,
    gate_validate: bool | None,
    test_command: str | None,
    disable_test_command: bool,
    test_timeout_seconds: int | None,
    test_output_max_chars: int | None,
) -> ReviewedApplyPolicy:
    run_validation_gate = (
        gate_validate if gate_validate is not None else base.run_validation_gate
    )
    resolved_test_command = base.test_command
    if disable_test_command:
        resolved_test_command = None
    elif test_command is not None:
        resolved_test_command = test_command

    timeout = (
        test_timeout_seconds
        if test_timeout_seconds is not None
        else base.test_timeout_seconds
    )
    output_max = (
        test_output_max_chars
        if test_output_max_chars is not None
        else base.test_output_max_chars
    )
    return ReviewedApplyPolicy(
        run_validation_gate=run_validation_gate,
        test_command=resolved_test_command,
        test_timeout_seconds=timeout,
        test_output_max_chars=output_max,
    )


def _get_bool(data: dict[str, Any], key: str, *, default: bool) -> bool:
    val = data.get(key, default)
    if isinstance(val, bool):
        return val
    raise ValueError(f"'{key}' must be a boolean.")


def _get_opt_str(data: dict[str, Any], key: str, *, default: str | None) -> str | None:
    val = data.get(key, default)
    if val is None:
        return None
    if isinstance(val, str) and val.strip():
        return val
    raise ValueError(f"'{key}' must be a non-empty string or null.")


def _get_positive_int(data: dict[str, Any], key: str, *, default: int) -> int:
    val = data.get(key, default)
    if isinstance(val, int) and val > 0:
        return val
    raise ValueError(f"'{key}' must be a positive integer.")


def _get_mode(data: dict[str, Any], key: str, *, default: str) -> str:
    val = data.get(key, default)
    if isinstance(val, str) and val in {"deterministic", "llm"}:
        return val
    raise ValueError(f"'{key}' must be one of: deterministic, llm.")
