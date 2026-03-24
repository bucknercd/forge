from datetime import datetime
import collections
import json
import re
import shlex
import sys
import uuid
from pathlib import Path
from typing import Any
from forge.paths import Paths
from forge.design_manager import Milestone, MilestoneService
from forge.run_history import RunHistory
from forge.models import RunHistoryEntry
from forge.validator import Validator
from forge.decision_tracker import DecisionTracker
from forge.milestone_state import normalize_milestone_state_value
from forge.milestone_selector import MilestoneSelector
from forge.milestone_state import MilestoneStateRepository

from forge.execution.models import ActionAddDecision, ApplyResult, ExecutionPlan
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.apply import ArtifactActionApplier
from forge.artifact_test_gen import ArtifactTestGenResult, generate_artifact_tests_for_task
from forge.gate_runner import (
    run_gates_for_milestone,
    run_validation_and_test_commands,
    summarize_gate_results,
)
from forge.planner_resolver import resolve_planner
from forge.policy_config import (
    ReviewedApplyPolicy,
    TaskExecutionPolicy,
    load_planner_policy,
    load_reviewed_apply_policy,
    load_task_execution_policy,
    merge_planner_policy,
)
from forge.failure_classification import (
    FailureClassification,
    classify_repair_failure,
    detect_identical_repair_plan,
)
from forge.analysis.stub_detection import (
    analyze_changed_python_files,
    persist_stub_detection_results,
)
from forge.task_feedback import build_repair_context, persist_task_feedback
from forge.run_events import (
    PHASE_COMPLETED,
    PHASE_STARTED,
    PLAN_SAVED,
    TASK_PLAN_SYNTHESIZED,
    as_emitter,
)
from forge.task_plan_synthesis import (
    TaskEmbeddedActionsError,
    synthesize_execution_plan_from_task,
    task_has_nonempty_embedded_forge_actions,
)
from forge.task_behavior_enrichment import (
    enrich_behavioral_task_if_needed,
    persist_enriched_task,
)
from forge.task_ir import (
    compile_task_to_ir,
    plan_is_substantive_for_task,
    task_ir_has_minimum_behavior_depth,
)
from forge.project_profile import project_profile_for_task_ir
from forge.planner import DeterministicPlanner, Planner
from forge.reviewed_plan import (
    load_reviewed_plan,
    save_reviewed_plan,
    validate_reviewed_plan,
)
from forge.task_service import (
    TASK_STATUS_COMPLETED,
    all_tasks_completed,
    ensure_tasks_for_milestone,
    get_next_task,
    get_task,
    set_task_status,
    task_to_execution_milestone,
)

MAX_RETRIES = 2


def _task_id_from_saved_plan(plan_id: str, payload: dict[str, Any]) -> int | None:
    raw = payload.get("task_id")
    if raw is not None:
        return int(raw)
    m = re.match(r"^m\d+-t(\d+)-", plan_id)
    if m:
        return int(m.group(1))
    return None


def _plan_has_add_decision(plan: ExecutionPlan) -> bool:
    return any(isinstance(a, ActionAddDecision) for a in plan.actions)


def _build_execution_summary(
    planned_action_count: int, apply_result: ApplyResult
) -> str:
    return (
        f"Applied {planned_action_count} planned action(s). "
        f"{apply_result.human_summary()}"
    )


def _primary_failure_message_from_classification(
    classification: dict[str, Any] | None,
    *,
    fallback: str,
) -> str:
    if not classification:
        return fallback
    mode = str(classification.get("mode") or "unknown_failure")
    phase = str(classification.get("phase") or "unknown")
    details = classification.get("details") or {}
    if mode == "missing_impl":
        if details.get("stub_detection_results"):
            return (
                "Run failed: missing_impl (stub detection: structural scaffold "
                "without required behavior)."
            )
        return "Run failed: missing_impl (required behavior not fully implemented)."
    return f"Run failed: {mode} (phase: {phase})."


def _plan_action_type_summary(plan: ExecutionPlan) -> list[str]:
    names: list[str] = []
    for a in plan.actions:
        n = type(a).__name__
        # Match API-ish action naming used elsewhere.
        if n.startswith("Action"):
            n = n[len("Action") :]
        names.append(
            n.replace("InFile", "_in_file")
            .replace("MarkMilestoneCompleted", "mark_milestone_completed")
            .replace("WriteFile", "write_file")
            .replace("AddDecision", "add_decision")
            .replace("AppendSection", "append_section")
            .replace("ReplaceSection", "replace_section")
            .replace("ReplaceText", "replace_text")
            .replace("ReplaceBlock", "replace_block")
            .replace("ReplaceLines", "replace_lines")
            .replace("InsertAfter", "insert_after")
            .replace("InsertBefore", "insert_before")
            .lower()
        )
    return names


def _behavioral_non_substantive_plan_error(
    *,
    milestone_id: int,
    task_ir: dict[str, Any],
    plan: ExecutionPlan,
) -> dict[str, Any]:
    task_id = int(task_ir.get("task_id", 0) or 0)
    ttype = str(task_ir.get("task_type", "unknown"))
    action_types = _plan_action_type_summary(plan)
    msg = (
        f"Rejected plan for task m{milestone_id}-t{task_id}: {ttype} task requires "
        "substantive implementation actions but plan only contains meta/bookkeeping actions. "
        "Hint: include implementation code edits or behavioral test actions."
    )
    return {
        "ok": False,
        "apply_ok": False,
        "message": msg,
        "failure_type": "non_substantive_behavioral_plan",
        "phase": "plan",
        "task_id": task_id,
        "task_ir": task_ir,
        "action_summary": action_types,
    }


def _persist_repair_loop_attempt_artifact(
    *,
    milestone_id: int,
    task_id: int,
    attempt: int,
    plan_id: str,
    apply_res: dict[str, Any],
) -> Path | None:
    """
    Persist the reviewed plan snapshot and apply outcome for each repair-loop attempt
    under ``.system/results/repair_attempts/`` for debugging (no-op vs rewrite, stale plan).
    """
    try:
        root = Paths.SYSTEM_DIR / "results" / "repair_attempts"
        root.mkdir(parents=True, exist_ok=True)
        safe = plan_id.replace("/", "_").replace("\\", "_")[:200]
        out_path = root / f"m{milestone_id}_t{task_id}_a{attempt:02d}_{safe}.json"
        stored = load_reviewed_plan(plan_id)
        wf_outcomes = [
            {
                "path": a.get("path"),
                "rel_path": a.get("rel_path"),
                "outcome": a.get("outcome"),
                "noop": a.get("noop"),
                "bytes_before": a.get("bytes_before"),
                "bytes_after": a.get("bytes_after"),
            }
            for a in (apply_res.get("actions_applied") or [])
            if a.get("type") == "write_file"
        ]
        summary: dict[str, Any] = {
            "milestone_id": milestone_id,
            "task_id": task_id,
            "attempt": attempt,
            "plan_id": plan_id,
            "apply_ok": apply_res.get("apply_ok"),
            "ok": apply_res.get("ok"),
            "gates_ok": apply_res.get("gates_ok"),
            "message": apply_res.get("message"),
            "files_changed": apply_res.get("files_changed"),
            "actions_applied": apply_res.get("actions_applied"),
            "write_file_outcomes": wf_outcomes,
            "result_artifact": apply_res.get("result_artifact"),
        }
        if stored:
            summary["plan"] = stored.get("plan")
            summary["planner_mode"] = stored.get("planner_mode")
            summary["plan_hash"] = stored.get("plan_hash")
            summary["milestones_file_hash"] = stored.get("milestones_file_hash")
            summary["tasks_file_hash"] = stored.get("tasks_file_hash")
        out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        return out_path
    except Exception:
        return None


def _planner_warnings(planner_meta: dict, plan: ExecutionPlan) -> list[str]:
    warnings: list[str] = []
    if planner_meta.get("plan_source") == "task_forge_actions":
        warnings.append(
            "Plan synthesized from task JSON forge_actions (LLM planner not used for planning)."
        )
    if planner_meta.get("is_nondeterministic"):
        client = planner_meta.get("llm_client") or "unknown"
        model = planner_meta.get("llm_model")
        via = f"{client}" + (f":{model}" if model else "")
        warnings.append(
            "Plan generated by non-deterministic LLM planner "
            f"({via}); review before apply is strongly recommended."
        )
    actions = plan.to_serializable().get("actions", [])
    if planner_meta.get("mode") == "llm":
        if len(actions) > 12:
            warnings.append(
                f"LLM plan has high action count ({len(actions)}); inspect for overreach."
            )
        canonical = [json.dumps(a, sort_keys=True, separators=(",", ":")) for a in actions]
        dup_count = sum(c - 1 for c in collections.Counter(canonical).values() if c > 1)
        if dup_count > 0:
            warnings.append(
                f"LLM plan includes {dup_count} duplicate action(s); verify intent."
            )
        body_empty = 0
        for a in actions:
            t = a.get("type")
            if t in {"append_section", "replace_section", "write_file"}:
                if not str(a.get("body", "")).strip():
                    body_empty += 1
            elif t in {"insert_after_in_file", "insert_before_in_file"}:
                if not str(a.get("anchor", "")).strip():
                    body_empty += 1
            elif t == "replace_text_in_file":
                if not str(a.get("old_text", "")).strip():
                    body_empty += 1
            elif t == "replace_block_in_file":
                if not str(a.get("start_marker", "")).strip() or not str(
                    a.get("end_marker", "")
                ).strip():
                    body_empty += 1
            elif t == "replace_lines_in_file":
                sl = a.get("start_line")
                el = a.get("end_line")
                if (
                    not isinstance(sl, int)
                    or not isinstance(el, int)
                    or sl < 1
                    or el < sl
                ):
                    body_empty += 1
        if body_empty:
            warnings.append(
                f"LLM plan includes {body_empty} action(s) with empty anchor/body/markers."
            )
    return warnings


def _mark_task_done_and_maybe_milestone(
    milestone_id: int,
    task_id: int,
    *,
    parent_milestone: Milestone,
    reviewed_plan: ExecutionPlan,
    success_summary: str,
) -> None:
    """Persist task completion and milestone roadmap state when all tasks are done."""
    set_task_status(milestone_id, task_id, TASK_STATUS_COMPLETED)
    if all_tasks_completed(milestone_id):
        sync_state = Executor._load_milestone_state_file()
        for k in list(sync_state.keys()):
            sync_state[k] = normalize_milestone_state_value(sync_state.get(k))
        ms_done = normalize_milestone_state_value(
            sync_state.get(str(milestone_id))
        )
        ms_done["status"] = "completed"
        sync_state[str(milestone_id)] = ms_done
        Executor._write_milestone_state_file(sync_state)
        if not _plan_has_add_decision(reviewed_plan):
            DecisionTracker.append_milestone_success_decision(
                milestone_id=milestone_id,
                milestone_title=parent_milestone.title,
                summary=success_summary,
            )
        entry = RunHistoryEntry(
            task=f"Execute milestone {milestone_id} (all tasks complete)",
            summary=f"{parent_milestone.title}: all tasks applied",
            status="completed",
            timestamp=datetime.now(),
        )
        RunHistory.log_run(entry)


class Executor:
    @staticmethod
    def execute_next() -> dict:
        """
        Orchestrate a single step:
        - use MilestoneSelector to choose the next eligible milestone
        - execute it via execute_milestone()
        - return a minimal structured outcome dict
        """
        milestone_service = MilestoneService()
        state_repository = MilestoneStateRepository(Paths.SYSTEM_DIR / "milestone_state.json")
        selector = MilestoneSelector(milestone_service, state_repository)

        try:
            next_milestone, report = selector.get_next_milestone_with_report()
        except ValueError as exc:
            return {
                "outcome": "none",
                "message": f"Milestone definition error: {exc}",
            }
        kind = (report or {}).get("kind")

        if next_milestone is None:
            if kind == "all_complete":
                return {"outcome": "complete", "message": "All milestones completed."}
            if kind == "in_progress":
                return {"outcome": "in_progress", "message": "Progress is already in progress."}
            if kind == "blocked":
                return {
                    "outcome": "blocked",
                    "message": "Progress is blocked by failed/unmet prerequisites.",
                }
            return {"outcome": "none", "message": "No runnable milestones found."}

        milestone_id = next_milestone.id

        expand = ensure_tasks_for_milestone(milestone_id)
        if not expand.get("ok"):
            return {
                "outcome": "none",
                "message": expand.get("message", "Could not ensure tasks for milestone."),
            }

        next_task = get_next_task(milestone_id)
        if next_task is None:
            if all_tasks_completed(milestone_id):
                Executor._sync_milestone_state_all_tasks_done(milestone_id, next_milestone)
            updated_state = state_repository.get(milestone_id)
            if updated_state.get("status") == "completed":
                return {
                    "outcome": "complete",
                    "milestone_id": milestone_id,
                    "message": f"All tasks for milestone {milestone_id} are completed.",
                }
            return {
                "outcome": "complete",
                "milestone_id": milestone_id,
                "message": f"Milestone {milestone_id} has no pending tasks.",
            }

        outcome = Executor._execute_next_task_step(
            milestone_id,
            next_milestone,
            next_task.id,
        )
        updated_state = state_repository.get(milestone_id)
        status = updated_state.get("status")
        if status == "completed":
            return {
                "outcome": "complete",
                "milestone_id": milestone_id,
                "task_id": next_task.id,
                "message": f"Milestone {milestone_id} completed (all tasks done).",
            }

        return {
            "outcome": "executed" if outcome.get("apply_ok") else "none",
            "milestone_id": milestone_id,
            "task_id": next_task.id,
            "message": outcome.get("message")
            or f"Milestone {milestone_id} task {next_task.id} executed; status={status}.",
        }

    @staticmethod
    def execute_milestone(milestone_id: int) -> None:
        """Legacy full-milestone apply (non-reviewed). Prefer task-based ``execute_next``."""
        return Executor._execute_milestone_internal(milestone_id)

    @staticmethod
    def _load_milestone_state_file() -> dict:
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        if state_file.exists():
            with state_file.open("r", encoding="utf-8") as file:
                return json.load(file)
        return {}

    @staticmethod
    def _write_milestone_state_file(state: dict) -> None:
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)

    @staticmethod
    def _sync_milestone_state_all_tasks_done(milestone_id: int, milestone) -> None:
        """If every task is completed, ensure roadmap state reflects milestone completion."""
        if not all_tasks_completed(milestone_id):
            return
        state = Executor._load_milestone_state_file()
        normalized_changed = False
        for k in list(state.keys()):
            if isinstance(state.get(k), str):
                normalized_changed = True
            state[k] = normalize_milestone_state_value(state.get(k))
        if normalized_changed:
            Executor._write_milestone_state_file(state)
        ms = normalize_milestone_state_value(state.get(str(milestone_id)))
        if ms["status"] == "completed":
            return
        ms["status"] = "completed"
        state[str(milestone_id)] = ms
        Executor._write_milestone_state_file(state)

    @staticmethod
    def run_task_apply_with_repair_loop(
        milestone_id: int,
        task_id: int,
        milestone: Milestone,
        *,
        planner: Planner,
        apply_policy: ReviewedApplyPolicy,
        task_exec_policy: TaskExecutionPolicy,
        run_milestone_validation: bool,
        initial_plan_id: str | None = None,
        review_enforcement: dict[str, Any] | None = None,
        event_bus: Any | None = None,
        finalize_milestone_state_on_failure: bool = False,
        milestone_state: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        state_file: Path | None = None,
    ) -> dict[str, Any]:
        """
        Shared task orchestration used by ``run-next``, ``task-apply-plan``,
        workflow guarded apply, and ``vertical-slice``: apply (optional first attempt
        uses a pre-saved reviewed plan id), artifact tests, validation/test batch,
        bounded replans with feedback.
        """
        result_path = Paths.SYSTEM_DIR / "results" / f"milestone_{milestone_id}.json"

        def _maybe_finalize(reason: str) -> None:
            if (
                finalize_milestone_state_on_failure
                and milestone_state is not None
                and state is not None
                and state_file is not None
            ):
                Executor._finalize_failed_or_retry(
                    milestone_id,
                    milestone,
                    milestone_state,
                    state,
                    state_file,
                    result_path,
                    reason=reason,
                )

        max_rep = task_exec_policy.max_repair_attempts
        if planner.mode == "deterministic":
            max_rep = 1

        task = get_task(milestone_id, task_id)
        if not task:
            msg = f"Task {task_id} not found for milestone {milestone_id}."
            _maybe_finalize(msg)
            return {"ok": False, "apply_ok": False, "message": msg}
        task_ir_for_profile = compile_task_to_ir(task)
        project_profile = project_profile_for_task_ir(task_ir_for_profile).profile_name
        behavior_heavy_task = task_ir_for_profile.task_type == "behavioral"

        parent_milestone = MilestoneService.get_milestone(milestone_id)
        if not parent_milestone:
            msg = "Parent milestone missing."
            _maybe_finalize(msg)
            return {"ok": False, "apply_ok": False, "message": msg}

        repair_context: dict[str, Any] | None = None
        last_message = ""
        last_plan_id: str | None = None
        last_gate_results: list[dict[str, Any]] = []
        prev_plan_hash: str | None = None
        last_failure_phase: str | None = None
        last_failure_classification: dict[str, Any] | None = None
        secondary_warnings: list[str] = []

        for attempt in range(1, max_rep + 1):
            use_initial = bool(initial_plan_id and attempt == 1)
            if use_initial:
                payload0 = load_reviewed_plan(initial_plan_id)
                if payload0 is None:
                    msg = f"Reviewed plan '{initial_plan_id}' not found."
                    _maybe_finalize(msg)
                    return {
                        "ok": False,
                        "apply_ok": False,
                        "message": msg,
                        "plan_id": initial_plan_id,
                        "repair_attempts_used": 0,
                    }
                mid_raw = payload0.get("milestone_id")
                if mid_raw is None or int(mid_raw) != milestone_id:
                    msg = "Reviewed plan milestone_id does not match."
                    _maybe_finalize(msg)
                    return {
                        "ok": False,
                        "apply_ok": False,
                        "message": msg,
                        "plan_id": initial_plan_id,
                    }
                tid = _task_id_from_saved_plan(initial_plan_id, payload0)
                if tid is None or tid != task_id:
                    msg = (
                        "Reviewed plan is not scoped to this task "
                        f"(expected task_id={task_id})."
                    )
                    return {
                        "ok": False,
                        "apply_ok": False,
                        "message": msg,
                        "plan_id": initial_plan_id,
                    }
                plan_id = initial_plan_id
            else:
                save = Executor.save_reviewed_plan_for_task(
                    milestone_id,
                    task_id,
                    planner=planner,
                    review_enforcement=review_enforcement,
                    event_bus=event_bus,
                    repair_context=repair_context,
                )
                if not save.get("ok"):
                    save_message = str(save.get("message", "Plan save failed."))
                    # If a classified failure already exists, keep it as primary outcome and
                    # treat this save error as secondary; retry remaining attempts if any.
                    if last_failure_classification:
                        secondary_warnings.append(
                            f"attempt {attempt}: failed to persist follow-up plan metadata: "
                            f"{save_message}"
                        )
                        last_message = _primary_failure_message_from_classification(
                            last_failure_classification,
                            fallback=save_message,
                        )
                        continue
                    last_message = save_message
                    _maybe_finalize(last_message)
                    return {
                        "ok": False,
                        "apply_ok": False,
                        "message": last_message,
                        "repair_attempts_used": attempt - 1,
                    }
                plan_id = save.get("plan_id")
                if not plan_id:
                    no_id_msg = "No plan_id from save step."
                    if last_failure_classification:
                        secondary_warnings.append(
                            f"attempt {attempt}: failed to persist follow-up plan metadata: "
                            f"{no_id_msg}"
                        )
                        last_message = _primary_failure_message_from_classification(
                            last_failure_classification,
                            fallback=no_id_msg,
                        )
                        continue
                    last_message = no_id_msg
                    _maybe_finalize(last_message)
                    return {
                        "ok": False,
                        "apply_ok": False,
                        "message": last_message,
                        "repair_attempts_used": attempt - 1,
                    }

            last_plan_id = plan_id
            stored_plan = load_reviewed_plan(plan_id)
            curr_plan_hash = (
                str(stored_plan.get("plan_hash")) if stored_plan else None
            ) or None
            planner_meta = (
                (stored_plan.get("planner_metadata") or {})
                if stored_plan
                else {}
            )

            # Same reviewed plan cannot fix a gate failure without changing the world
            # (e.g. external mocks), so we only short-circuit when the *previous* failure
            # was in apply — identical replan is provably redundant there.
            if (
                detect_identical_repair_plan(
                    attempt=attempt,
                    previous_plan_hash=prev_plan_hash,
                    current_plan_hash=curr_plan_hash,
                )
                and last_failure_phase == "apply"
            ):
                fc = FailureClassification(
                    "no_op_repair",
                    "apply",
                    ("identical_plan_hash",),
                    {
                        "plan_hash_prefix": (curr_plan_hash or "")[:20],
                        "attempt": attempt,
                    },
                )
                last_failure_classification = fc.to_dict()
                persist_task_feedback(
                    milestone_id,
                    task_id,
                    attempt,
                    {
                        "phase": "repair_preflight",
                        "plan_id": plan_id,
                        "early_exit": "no_op_repair",
                        "classification": fc.to_dict(),
                    },
                )
                msg = (
                    f"Repair loop stopped: planner produced an identical plan to attempt "
                    f"{attempt - 1} (plan hash unchanged). Human review required."
                )
                _maybe_finalize(msg)
                return {
                    "ok": False,
                    "apply_ok": False,
                    "gates_ok": False,
                    "plan_id": plan_id,
                    "message": msg,
                    "repair_attempts_used": attempt - 1,
                    "gate_results": last_gate_results,
                    "failure_classification": fc.to_dict(),
                    "repair_stopped_reason": "no_op_repair",
                    "policy": {
                        "run_validation_gate": run_milestone_validation,
                        "test_command": apply_policy.test_command,
                        "test_timeout_seconds": apply_policy.test_timeout_seconds,
                        "test_output_max_chars": apply_policy.test_output_max_chars,
                    },
                    "orchestration": "task_repair_loop",
                }

            apply_res = Executor.apply_reviewed_plan_with_gates(
                plan_id,
                run_validation_gate=False,
                test_command=None,
                test_timeout_seconds=apply_policy.test_timeout_seconds,
                test_output_max_chars=apply_policy.test_output_max_chars,
                mark_task_complete=False,
                record_milestone_attempt=False,
                defer_post_apply_gates=True,
                event_bus=event_bus,
            )
            rapath = _persist_repair_loop_attempt_artifact(
                milestone_id=milestone_id,
                task_id=task_id,
                attempt=attempt,
                plan_id=plan_id,
                apply_res=apply_res,
            )
            if rapath is not None:
                apply_res["repair_attempt_artifact"] = str(rapath)

            if not apply_res.get("apply_ok"):
                last_message = apply_res.get("message") or "Apply failed."
                fc = classify_repair_failure(
                    phase="apply",
                    apply_errors=list(apply_res.get("errors") or []),
                    attempt=attempt,
                    previous_plan_hash=prev_plan_hash,
                    current_plan_hash=curr_plan_hash,
                    planner_metadata=planner_meta,
                )
                last_failure_classification = fc.to_dict()
                last_message = _primary_failure_message_from_classification(
                    last_failure_classification,
                    fallback=last_message,
                )
                persist_task_feedback(
                    milestone_id,
                    task_id,
                    attempt,
                    {
                        "phase": "apply",
                        "plan_id": plan_id,
                        "apply_ok": False,
                        "errors": apply_res.get("errors", []),
                        "classification": fc.to_dict(),
                    },
                )
                repair_context = build_repair_context(
                    milestone_id,
                    task_id,
                    attempt,
                    apply_ok=False,
                    apply_errors=list(apply_res.get("errors") or []),
                    gate_results=None,
                    classification=fc.to_dict(),
                    repair_mode=fc.mode,
                    project_profile=project_profile,
                )
                last_failure_phase = "apply"
                prev_plan_hash = curr_plan_hash
                continue

            if task_exec_policy.artifact_test_generation:
                gen = generate_artifact_tests_for_task(
                    milestone_id, task_id, task
                )
            else:
                gen = ArtifactTestGenResult(
                    generated=False,
                    rel_path=None,
                    message=(
                        "Artifact test generation disabled in forge-policy.json "
                        "(task_execution.artifact_test_generation=false)."
                    ),
                    skipped_reason="policy_disabled",
                )

            test_commands: list[str] = []
            if gen.generated and gen.rel_path:
                test_commands.append(
                    f"{shlex.quote(sys.executable)} -m pytest "
                    f"{shlex.quote(gen.rel_path)}"
                )
            if apply_policy.test_command:
                test_commands.append(apply_policy.test_command)

            gates = run_validation_and_test_commands(
                milestone_id,
                run_validation_gate=run_milestone_validation,
                test_commands=test_commands,
                timeout_seconds=apply_policy.test_timeout_seconds,
                output_max_chars=apply_policy.test_output_max_chars,
                event_bus=event_bus,
            )
            last_gate_results = gates
            gates_ok = all(g.get("ok") for g in gates) if gates else True

            if not gates_ok:
                last_message = (
                    apply_res.get("message")
                    or summarize_gate_results(gates)
                    or "Validation or tests failed."
                )
                fc = classify_repair_failure(
                    phase="gates",
                    gate_results=gates,
                    attempt=attempt,
                    previous_plan_hash=prev_plan_hash,
                    current_plan_hash=curr_plan_hash,
                    planner_metadata=planner_meta,
                    behavior_heavy=behavior_heavy_task,
                )
                last_failure_classification = fc.to_dict()
                last_message = _primary_failure_message_from_classification(
                    last_failure_classification,
                    fallback=last_message,
                )
                persist_task_feedback(
                    milestone_id,
                    task_id,
                    attempt,
                    {
                        "phase": "gates",
                        "plan_id": plan_id,
                        "artifact_test": {
                            "generated": gen.generated,
                            "rel_path": gen.rel_path,
                            "skipped_reason": gen.skipped_reason,
                            "message": gen.message,
                        },
                        "gate_results": gates,
                        "classification": fc.to_dict(),
                    },
                )
                repair_context = build_repair_context(
                    milestone_id,
                    task_id,
                    attempt,
                    apply_ok=True,
                    apply_errors=[],
                    gate_results=gates,
                    artifact_test_path=gen.rel_path,
                    extra_message=None
                    if gen.generated
                    else gen.message,
                    classification=fc.to_dict(),
                    repair_mode=fc.mode,
                    project_profile=project_profile,
                )
                last_failure_phase = "gates"
                prev_plan_hash = curr_plan_hash
                continue

            # Post-gate stub detection (deterministic): fail if product Python is scaffold-only.
            fc_run_id = (getattr(event_bus, "run_id", "") or "").strip() or uuid.uuid4().hex[:16]
            reviewed_payload = load_reviewed_plan(plan_id)
            reviewed_plan_for_stub = (
                ExecutionPlan.from_serializable(reviewed_payload["plan"])
                if reviewed_payload and reviewed_payload.get("plan")
                else ExecutionPlan(milestone_id=milestone_id, actions=[])
            )

            if behavior_heavy_task:
                has_source_impl_target = any(
                    str(getattr(a, "rel_path", "")).replace("\\", "/").startswith(
                        ("src/", "scripts/", "examples/", "infra/")
                    )
                    for a in reviewed_plan_for_stub.actions
                )
                if not has_source_impl_target:
                    last_message = (
                        "Behavior-heavy task plan did not target source implementation files; "
                        "missing core behavior implementation."
                    )
                    fc = FailureClassification(
                        "missing_impl",
                        "gates",
                        ("no_source_impl_targets",),
                        {
                            "requirement_summary": (parent_milestone.objective or "").strip()[
                                :1200
                            ]
                        },
                    )
                    last_failure_classification = fc.to_dict()
                    last_message = _primary_failure_message_from_classification(
                        last_failure_classification, fallback=last_message
                    )
                    repair_context = build_repair_context(
                        milestone_id,
                        task_id,
                        attempt,
                        apply_ok=True,
                        apply_errors=[],
                        gate_results=gates,
                        artifact_test_path=gen.rel_path,
                        extra_message=None if gen.generated else gen.message,
                        classification=fc.to_dict(),
                        repair_mode=fc.mode,
                        project_profile=project_profile,
                    )
                    last_failure_phase = "gates"
                    prev_plan_hash = curr_plan_hash
                    continue

            changed_paths = set(apply_res.get("files_changed") or [])

            # If a follow-up repair attempt re-applies an identical stub, write_file
            # actions can become noops and apply_res.files_changed may be empty.
            # To avoid false success, always analyze python files targeted by the
            # reviewed plan actions.
            try:
                stub_plan: ExecutionPlan | None = reviewed_plan_for_stub
            except Exception:  # noqa: BLE001
                stub_plan = None

            if stub_plan is not None:
                for a in stub_plan.actions:
                    rel = getattr(a, "rel_path", None)
                    if not isinstance(rel, str) or not rel.endswith(".py"):
                        continue
                    if type(a).__name__ == "ActionWriteFile" and rel.startswith("examples/"):
                        rel = "src/" + rel[len("examples/") :]
                    changed_paths.add(str(Paths.BASE_DIR / rel))

            if behavior_heavy_task:
                source_paths = [
                    p
                    for p in changed_paths
                    if "/src/" in p
                    or "/scripts/" in p
                    or "/examples/" in p
                    or "/infra/" in p
                    or p.endswith(("/src", "/scripts", "/examples", "/infra"))
                ]
                if source_paths:
                    changed_paths = set(source_paths)

            changed_paths = list(changed_paths)
            all_stub_recs, stub_fails = analyze_changed_python_files(
                changed_paths,
                Paths.BASE_DIR,
                expected_behavior_signals=(
                    list(task_ir_for_profile.behavior_signals) if behavior_heavy_task else None
                ),
            )
            stub_artifact_path = persist_stub_detection_results(
                Paths.BASE_DIR, fc_run_id, all_stub_recs
            )
            if stub_fails:
                last_message = (
                    "Stub detection: implementation looks like a structural scaffold "
                    "without required behavior (missing core logic). Files: "
                    + ", ".join(r["rel_path"] for r in stub_fails)
                )
                sig_union = sorted({s for r in stub_fails for s in r.get("signals") or []})
                stub_gate = {
                    "name": "stub_detection",
                    "ok": False,
                    "message": last_message,
                    "details": {
                        "stub_files": stub_fails,
                        "artifact_path": str(stub_artifact_path),
                        "run_id": fc_run_id,
                    },
                }
                gates_with_stub = list(gates) + [stub_gate]
                fc = FailureClassification(
                    "missing_impl",
                    "gates",
                    ("stub_detection",) + tuple(sig_union),
                    {
                        "stub_detection_results": stub_fails,
                        "stub_detection_artifact": str(stub_artifact_path),
                        "requirement_summary": (parent_milestone.objective or "").strip()[
                            :1200
                        ],
                    },
                )
                last_failure_classification = fc.to_dict()
                last_message = _primary_failure_message_from_classification(
                    last_failure_classification,
                    fallback=last_message,
                )
                persist_task_feedback(
                    milestone_id,
                    task_id,
                    attempt,
                    {
                        "phase": "stub_detection",
                        "plan_id": plan_id,
                        "gate_results": gates_with_stub,
                        "stub_detection": {
                            "artifact_path": str(stub_artifact_path),
                            "failing_files": stub_fails,
                        },
                        "classification": fc.to_dict(),
                    },
                )
                repair_context = build_repair_context(
                    milestone_id,
                    task_id,
                    attempt,
                    apply_ok=True,
                    apply_errors=[],
                    gate_results=gates_with_stub,
                    artifact_test_path=gen.rel_path,
                    extra_message=None if gen.generated else gen.message,
                    classification=fc.to_dict(),
                    repair_mode=fc.mode,
                    project_profile=project_profile,
                )
                last_failure_phase = "gates"
                prev_plan_hash = curr_plan_hash
                continue

            payload = load_reviewed_plan(plan_id)
            if payload is None:
                last_message = f"Reviewed plan '{plan_id}' missing after apply."
                _maybe_finalize(last_message)
                return {
                    "ok": False,
                    "apply_ok": False,
                    "message": last_message,
                    "plan_id": plan_id,
                    "repair_attempts_used": attempt,
                }

            reviewed_plan = ExecutionPlan.from_serializable(payload["plan"])
            gate_summary = summarize_gate_results(gates)
            success_summary = (
                f"Applied {len(reviewed_plan.actions)} planned action(s). "
                f"{apply_res.get('artifact_summary', '')}; gates: {gate_summary}"
            )
            _mark_task_done_and_maybe_milestone(
                milestone_id,
                task_id,
                parent_milestone=parent_milestone,
                reviewed_plan=reviewed_plan,
                success_summary=success_summary,
            )
            RunHistory.log_milestone_attempt(
                milestone_id=milestone_id,
                milestone_title=milestone.title,
                status="success",
                artifact_summary=f"{apply_res.get('artifact_summary', '')}; gates: {gate_summary}",
            )
            done_msg = (
                f"Artifact tests: {gen.rel_path}"
                if gen.generated
                else gen.message
            )
            out = dict(apply_res)
            pol = dict(apply_res.get("policy", {}))
            pol["run_validation_gate"] = run_milestone_validation
            pol["test_command"] = apply_policy.test_command
            pol["test_timeout_seconds"] = apply_policy.test_timeout_seconds
            pol["test_output_max_chars"] = apply_policy.test_output_max_chars
            out.update(
                {
                    "ok": True,
                    "apply_ok": True,
                    "gates_ok": True,
                    "plan_id": plan_id,
                    "policy": pol,
                    "gate_results": gates,
                    "gate_summary": gate_summary,
                    "repair_attempts_used": attempt,
                    "message": (
                        f"Task {task_id} completed (attempt {attempt}/{max_rep}). "
                        f"{done_msg}"
                    ).strip(),
                    "orchestration": "task_repair_loop",
                }
            )
            return out

        final_reason = (
            f"Task {task_id} failed after {max_rep} repair attempt(s): {last_message}"
        )
        if secondary_warnings:
            final_reason = (
                f"{final_reason} Warning: {secondary_warnings[-1]}"
            )
        _maybe_finalize(final_reason)
        return {
            "ok": False,
            "apply_ok": False,
            "gates_ok": False,
            "plan_id": last_plan_id,
            "message": final_reason,
            "repair_attempts_used": max_rep,
            "gate_results": last_gate_results,
            "gate_summary": summarize_gate_results(last_gate_results)
            if last_gate_results
            else "",
            "failure_classification": last_failure_classification,
            "secondary_warnings": list(secondary_warnings),
            "policy": {
                "run_validation_gate": run_milestone_validation,
                "test_command": apply_policy.test_command,
                "test_timeout_seconds": apply_policy.test_timeout_seconds,
                "test_output_max_chars": apply_policy.test_output_max_chars,
                "defer_post_apply_gates": True,
                "mark_task_complete": False,
                "record_milestone_attempt": False,
            },
            "orchestration": "task_repair_loop",
        }

    @staticmethod
    def task_ids_for_reviewed_plan(plan_id: str) -> tuple[int, int] | None:
        """Return ``(milestone_id, task_id)`` for a task-scoped reviewed plan, or ``None``."""
        payload = load_reviewed_plan(plan_id)
        if payload is None:
            return None
        mid_raw = payload.get("milestone_id")
        if mid_raw is None:
            return None
        tid = _task_id_from_saved_plan(plan_id, payload)
        if tid is None:
            return None
        return int(mid_raw), tid

    @staticmethod
    def _execute_next_task_step(
        milestone_id: int,
        milestone,
        task_id: int,
    ) -> dict:
        """
        Milestone roadmap + selector preamble, then
        :meth:`run_task_apply_with_repair_loop` (``run-next`` repair semantics).
        """
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        state = Executor._load_milestone_state_file()
        normalized_changed = False
        for k in list(state.keys()):
            if isinstance(state.get(k), str):
                normalized_changed = True
            state[k] = normalize_milestone_state_value(state.get(k))
        if normalized_changed:
            Executor._write_milestone_state_file(state)

        milestone_state = normalize_milestone_state_value(state.get(str(milestone_id)))

        deps_ok = True
        for dep_id in getattr(milestone, "depends_on", []):
            dep_state = normalize_milestone_state_value(state.get(str(dep_id)))
            if dep_state["status"] != "completed":
                deps_ok = False
                break

        runnable_statuses = {"not_started", "retry_pending", "in_progress"}
        if milestone_state["status"] not in runnable_statuses:
            return {
                "apply_ok": False,
                "message": "Milestone is not runnable in its current state.",
            }

        if not deps_ok:
            return {
                "apply_ok": False,
                "message": "Milestone is blocked by unmet prerequisites.",
            }

        milestone_state["attempts"] += 1
        milestone_state["status"] = "in_progress"
        state[str(milestone_id)] = milestone_state
        Executor._write_milestone_state_file(state)

        entry = RunHistoryEntry(
            task=f"Execute milestone {milestone_id} task {task_id} "
            f"(Attempt {milestone_state['attempts']})",
            summary=f"{milestone.title}: task {task_id}",
            status="started",
            timestamp=datetime.now(),
        )
        RunHistory.log_run(entry)

        result_path = Paths.SYSTEM_DIR / "results" / f"milestone_{milestone_id}.json"

        planner, _planner_policy, planner_err = resolve_planner(None)
        if planner is None:
            msg = planner_err or "Could not resolve planner from forge-policy.json."
            Executor._finalize_failed_or_retry(
                milestone_id,
                milestone,
                milestone_state,
                state,
                state_file,
                result_path,
                reason=msg,
            )
            return {"apply_ok": False, "message": msg}

        apply_policy, apply_policy_err = load_reviewed_apply_policy()
        if apply_policy_err:
            Executor._finalize_failed_or_retry(
                milestone_id,
                milestone,
                milestone_state,
                state,
                state_file,
                result_path,
                reason=apply_policy_err,
            )
            return {"apply_ok": False, "message": apply_policy_err}

        task_exec_policy, task_exec_err = load_task_execution_policy()
        if task_exec_err:
            Executor._finalize_failed_or_retry(
                milestone_id,
                milestone,
                milestone_state,
                state,
                state_file,
                result_path,
                reason=task_exec_err,
            )
            return {"apply_ok": False, "message": task_exec_err}

        loop_out = Executor.run_task_apply_with_repair_loop(
            milestone_id,
            task_id,
            milestone,
            planner=planner,
            apply_policy=apply_policy,
            task_exec_policy=task_exec_policy,
            run_milestone_validation=True,
            initial_plan_id=None,
            review_enforcement=None,
            event_bus=None,
            finalize_milestone_state_on_failure=True,
            milestone_state=milestone_state,
            state=state,
            state_file=state_file,
        )
        if loop_out.get("apply_ok"):
            return {
                "apply_ok": True,
                "message": loop_out.get("message", ""),
                "repair_attempts_used": loop_out.get("repair_attempts_used"),
                "last_plan_id": loop_out.get("plan_id"),
            }
        return {
            "apply_ok": False,
            "message": loop_out.get("message", ""),
            "repair_attempts_used": loop_out.get("repair_attempts_used"),
        }

    @staticmethod
    def preview_milestone(
        milestone_id: int,
        planner: Planner | None = None,
        *,
        task_id: int | None = None,
        repair_context: dict | None = None,
        planner_mode_override: str | None = None,
    ) -> dict:
        """
        Build and simulate an execution plan for a **task** under the milestone.

        ``task_id`` is required. The plan is built from ``.system/tasks/m<milestone_id>.json``;
        the parent milestone id is still used for ``mark_milestone_completed`` targets.
        """
        try:
            parent = MilestoneService.get_milestone(milestone_id)
        except ValueError as exc:
            return {"ok": False, "message": f"Milestone definition error: {exc}"}
        if not parent:
            return {"ok": False, "message": "Invalid milestone ID."}

        if task_id is not None:
            ens = ensure_tasks_for_milestone(milestone_id)
            if not ens.get("ok"):
                return {
                    "ok": False,
                    "message": ens.get("message", "Could not ensure tasks for milestone."),
                    "milestone_id": milestone_id,
                }

        if task_id is None:
            return {
                "ok": False,
                "message": (
                    "Execution requires a task. List tasks with "
                    f"`forge task-list --milestone {milestone_id}` and pass `--task <n>`."
                ),
                "requires_task_selection": True,
                "milestone_id": milestone_id,
            }

        task = get_task(milestone_id, task_id)
        if not task:
            return {
                "ok": False,
                "message": (
                    f"Unknown task {task_id} for milestone {milestone_id}. "
                    f"Run `forge task-expand --milestone {milestone_id}` first."
                ),
                "milestone_id": milestone_id,
            }

        vision_text: str | None = None
        try:
            vf = Paths.VISION_FILE
            if vf.is_file():
                vision_text = vf.read_text(encoding="utf-8")[:4000]
        except OSError:
            vision_text = None

        task, enrich_meta = enrich_behavioral_task_if_needed(
            task, parent, vision_text=vision_text
        )
        if enrich_meta.get("enriched"):
            persist_enriched_task(milestone_id, task)

        task_ir = compile_task_to_ir(task)
        if not task_ir_has_minimum_behavior_depth(task_ir):
            return {
                "ok": False,
                "message": (
                    f"Rejected task m{milestone_id}-t{task_id}: behavioral task is under-scoped "
                    "even after enrichment from milestone/vision "
                    "(count/aggregate/group/sort/top/rank/transform)."
                ),
                "milestone_id": milestone_id,
                "task_id": task_id,
                "failure_type": "behavioral_task_underscoped",
                "task_ir": task_ir.to_dict(),
                "task_behavior_enrichment": enrich_meta,
            }
        milestone = task_to_execution_milestone(parent, task)

        plan: ExecutionPlan | None = None
        planner_meta: dict[str, Any] | None = None

        skip_embedded = bool(repair_context)
        if not skip_embedded and task_ir.has_embedded_actions:
            try:
                plan, meta_obj = synthesize_execution_plan_from_task(task, milestone)
                planner_meta = dict(meta_obj)
            except TaskEmbeddedActionsError as exc:
                return {
                    "ok": False,
                    "message": str(exc),
                    "milestone_id": milestone_id,
                    "task_id": task_id,
                    "failure_type": "task_action_validation_error",
                    "offending_action": exc.offending_action,
                    "parser_reason": exc.parser_message,
                }
        else:
            use_planner = planner or DeterministicPlanner()
            try:
                plan = use_planner.build_plan(milestone, repair_context=repair_context)
                _ = ExecutionPlanBuilder.parse_validation_rules(milestone)
                planner_meta = dict(use_planner.metadata())
            except ValueError as exc:
                msg = str(exc)
                out_err: dict[str, Any] = {
                    "ok": False,
                    "message": msg,
                    "milestone_id": milestone_id,
                }
                if "LLM planner action" in msg and "invalid:" in msg:
                    out_err["failure_type"] = "planner_format_error"
                    parser_reason = msg
                    bad_action = None
                    m_bad = re.search(r"Bad action:\s*('(?:[^'\\]|\\.)*')", msg)
                    if m_bad:
                        bad_action = m_bad.group(1)
                        parser_reason = msg[: m_bad.start()].strip()
                    m_path = re.search(r"Raw planner output saved to:\s*(.+)$", msg)
                    if bad_action is not None:
                        out_err["bad_action"] = bad_action
                    out_err["parser_reason"] = parser_reason
                    if m_path:
                        out_err["raw_planner_output_path"] = m_path.group(1).strip()
                return out_err

        assert plan is not None and planner_meta is not None
        plan.task_id = task_id
        if enrich_meta.get("enriched") or enrich_meta.get("phases_tried"):
            planner_meta["task_behavior_enrichment"] = enrich_meta

        pol_b, pol_err = load_planner_policy()
        if pol_err:
            policy_mode = "deterministic"
            planner_meta["policy_llm_client"] = None
        else:
            pol_m = merge_planner_policy(pol_b, mode_override=planner_mode_override)
            policy_mode = pol_m.mode
            planner_meta["policy_llm_client"] = pol_m.llm_client
        planner_meta["policy_planner_mode"] = policy_mode
        if not skip_embedded and task_ir.has_embedded_actions:
            planner_meta["mode"] = policy_mode
        elif not planner_meta.get("mode"):
            planner_meta["mode"] = policy_mode
        planner_meta["task_ir"] = {
            "task_type": task_ir.task_type,
            "behavior_signals": list(task_ir.behavior_signals),
            "has_embedded_actions": task_ir.has_embedded_actions,
        }

        warnings = _planner_warnings(planner_meta, plan)
        if task_ir.task_type == "behavioral" and not plan_is_substantive_for_task(
            task_ir, plan
        ):
            return _behavioral_non_substantive_plan_error(
                milestone_id=milestone_id,
                task_ir=task_ir.to_dict(),
                plan=plan,
            )
        applier = ArtifactActionApplier(Paths)
        project_profile = project_profile_for_task_ir(task_ir).profile_name
        dry = applier.apply(
            plan, milestone, dry_run=True, project_profile=project_profile
        )
        effective_mode = str(planner_meta.get("mode") or policy_mode)
        out: dict = {
            "ok": len(dry.errors) == 0,
            "milestone_id": milestone.id,
            "title": milestone.title,
            "planner_mode": effective_mode,
            "planner_metadata": planner_meta,
            "execution_plan": plan.to_serializable(),
            "files_changed": dry.normalized_files_changed(),
            "artifact_summary": dry.human_summary(),
            "actions_applied": dry.actions_applied,
            "errors": dry.errors,
            "warnings": warnings,
        }
        out["task_id"] = task_id
        out["task_ir"] = task_ir.to_dict()
        out["task_behavior_enrichment"] = enrich_meta
        return out

    @staticmethod
    def save_reviewed_plan_for_task(
        milestone_id: int,
        task_id: int,
        planner: Planner | None = None,
        review_enforcement: dict | None = None,
        event_bus: object | None = None,
        *,
        repair_context: dict | None = None,
        planner_mode_override: str | None = None,
    ) -> dict:
        """Preview/save a reviewed plan built from a task under ``milestone_id``."""
        ens = ensure_tasks_for_milestone(milestone_id)
        if not ens.get("ok"):
            return {
                "ok": False,
                "message": ens.get("message", "Could not ensure tasks for milestone."),
            }
        planner = planner or DeterministicPlanner()
        preview = Executor.preview_milestone(
            milestone_id,
            planner=planner,
            task_id=task_id,
            repair_context=repair_context,
            planner_mode_override=planner_mode_override,
        )
        if not preview.get("ok"):
            return preview
        try:
            parent = MilestoneService.get_milestone(milestone_id)
            if not parent:
                return {"ok": False, "message": "Invalid milestone ID."}
            plan = ExecutionPlan.from_serializable(preview["execution_plan"])
            eff_mode = preview.get("planner_mode", planner.mode)
            payload = save_reviewed_plan(
                milestone_id,
                parent.title,
                plan,
                planner_mode=eff_mode,
                planner_metadata=preview.get("planner_metadata", planner.metadata()),
                warnings=preview.get("warnings", []),
                review_enforcement=review_enforcement,
                task_id=task_id,
            )
            preview["plan_id"] = payload["plan_id"]
            plan_path = Paths.SYSTEM_DIR / "reviewed_plans" / f"{payload['plan_id']}.json"
            preview["plan_file"] = str(plan_path)
            preview["review_enforcement"] = payload.get(
                "review_enforcement", review_enforcement or {}
            )
            planner_meta = payload.get("planner_metadata", {}) or {}
            norm_events = planner_meta.get("normalization_events") or []
            bus = as_emitter(event_bus)
            if planner_meta.get("plan_source") == "task_forge_actions":
                acts = (preview.get("execution_plan") or {}).get("actions") or []
                bus.emit(
                    TASK_PLAN_SYNTHESIZED,
                    milestone_id=milestone_id,
                    task_id=task_id,
                    action_count=len(acts),
                    reason=str(
                        planner_meta.get("reason") or "embedded_forge_actions_present"
                    ),
                )
            for ne in norm_events:
                if not isinstance(ne, dict):
                    continue
                bus.emit(
                    "planner_action_normalized",
                    action_index=ne.get("action_index"),
                    original_action=ne.get("original_action"),
                    normalized_action=ne.get("normalized_action"),
                    reason=ne.get("reason"),
                )
            bus.emit(
                PLAN_SAVED,
                plan_id=payload["plan_id"],
                milestone_id=milestone_id,
                plan_file=str(plan_path),
                task_id=task_id,
            )
            return preview
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Failed to save reviewed plan: {exc}"}

    @staticmethod
    def preview_next() -> dict:
        """
        Preview next eligible milestone without executing or mutating state.
        """
        milestone_service = MilestoneService()
        state_repository = MilestoneStateRepository(Paths.SYSTEM_DIR / "milestone_state.json")
        selector = MilestoneSelector(milestone_service, state_repository)

        try:
            next_milestone, report = selector.get_next_milestone_with_report()
        except ValueError as exc:
            return {"ok": False, "message": f"Milestone definition error: {exc}"}

        if next_milestone is None:
            kind = (report or {}).get("kind")
            if kind == "all_complete":
                return {"ok": False, "message": "All milestones completed."}
            if kind == "in_progress":
                return {"ok": False, "message": "Progress is already in progress."}
            return {
                "ok": False,
                "message": "Progress is blocked by failed/unmet prerequisites.",
            }
        mid = next_milestone.id
        ens = ensure_tasks_for_milestone(mid)
        if not ens.get("ok"):
            return {"ok": False, "message": ens.get("message", "Could not ensure tasks.")}
        nt = get_next_task(mid)
        if nt is None:
            return {
                "ok": False,
                "message": (
                    f"No pending tasks for milestone {mid} "
                    "(all tasks may already be completed)."
                ),
                "milestone_id": mid,
            }
        return Executor.preview_milestone(mid, task_id=nt.id)

    @staticmethod
    def apply_reviewed_plan(plan_id: str) -> dict:
        return Executor.apply_reviewed_plan_with_gates(
            plan_id,
            run_validation_gate=False,
            test_command=None,
        )

    @staticmethod
    def apply_reviewed_plan_with_gates(
        plan_id: str,
        *,
        run_validation_gate: bool,
        test_command: str | None,
        test_timeout_seconds: int = 120,
        test_output_max_chars: int = 1200,
        event_bus: object | None = None,
        mark_task_complete: bool = True,
        record_milestone_attempt: bool = True,
        defer_post_apply_gates: bool = False,
    ) -> dict:
        bus = as_emitter(event_bus)
        payload = load_reviewed_plan(plan_id)
        if payload is None:
            return {"ok": False, "message": f"Reviewed plan '{plan_id}' not found."}

        milestone_id = int(payload.get("milestone_id"))
        try:
            milestone = MilestoneService.get_milestone(milestone_id)
        except ValueError as exc:
            return {"ok": False, "message": f"Milestone definition error: {exc}"}
        if not milestone:
            return {"ok": False, "message": "Milestone for reviewed plan no longer exists."}

        raw_task_id = payload.get("task_id")
        task_id: int | None = int(raw_task_id) if raw_task_id is not None else None
        task_ir = None

        try:
            planner_mode = payload.get("planner_mode", "deterministic")
            apply_milestone = milestone
            if task_id is not None:
                task = get_task(milestone_id, task_id)
                if not task:
                    return {
                        "ok": False,
                        "message": (
                            f"Task {task_id} no longer exists for milestone {milestone_id}."
                        ),
                        "plan_id": plan_id,
                        "milestone_id": milestone_id,
                    }
                apply_milestone = task_to_execution_milestone(milestone, task)
            if planner_mode == "deterministic":
                current_plan = DeterministicPlanner().build_plan(apply_milestone)
            else:
                # For non-deterministic planners, compare against reviewed plan
                # and rely on existing milestone/target hash stale checks.
                current_plan = ExecutionPlan.from_serializable(payload["plan"])
            if task_id is not None:
                current_plan.task_id = task_id
        except ValueError as exc:
            return {"ok": False, "message": f"Current milestone plan invalid: {exc}"}

        ok, reason = validate_reviewed_plan(payload, current_plan)
        if not ok:
            return {"ok": False, "message": reason, "plan_id": plan_id, "milestone_id": milestone_id}

        reviewed_plan = ExecutionPlan.from_serializable(payload["plan"])
        if task_id is not None:
            task_for_ir = get_task(milestone_id, task_id)
            if task_for_ir is not None:
                task_ir = compile_task_to_ir(task_for_ir)
                if (
                    task_ir.task_type == "behavioral"
                    and not plan_is_substantive_for_task(task_ir, reviewed_plan)
                ):
                    out = _behavioral_non_substantive_plan_error(
                        milestone_id=milestone_id,
                        task_ir=task_ir.to_dict(),
                        plan=reviewed_plan,
                    )
                    out.update(
                        {
                            "plan_id": plan_id,
                            "milestone_id": milestone_id,
                            "planner_mode": payload.get("planner_mode", "deterministic"),
                            "planner_metadata": payload.get("planner_metadata", {}),
                            "review_enforcement": payload.get("review_enforcement", {}),
                        }
                    )
                    return out
        apply_project_profile: str | None = None
        if task_id is not None:
            task_for_profile = get_task(milestone_id, task_id)
            if task_for_profile is not None:
                apply_project_profile = project_profile_for_task_ir(
                    compile_task_to_ir(task_for_profile)
                ).profile_name
        applier = ArtifactActionApplier(Paths)
        bus.emit(PHASE_STARTED, phase="apply", label="execute reviewed plan")
        apply_result = applier.apply(
            reviewed_plan,
            apply_milestone,
            dry_run=False,
            event_bus=bus,
            project_profile=apply_project_profile,
        )
        apply_ok = len(apply_result.errors) == 0
        bus.emit(
            PHASE_COMPLETED,
            phase="apply",
            ok=apply_ok,
            message=(
                apply_result.human_summary()
                if apply_ok
                else "; ".join(apply_result.errors)
            ),
        )
        # Persist a milestone result artifact so optional validation gate can
        # reuse the existing Validator contract.
        result_dir = Paths.SYSTEM_DIR / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        milestone_result_file = result_dir / f"milestone_{milestone_id}.json"
        milestone_result_payload = {
            "id": milestone_id,
            "title": apply_milestone.title,
            "summary": _build_execution_summary(len(reviewed_plan.actions), apply_result),
            "artifact_summary": apply_result.human_summary(),
            "files_changed": apply_result.normalized_files_changed(),
            "actions_applied": apply_result.actions_applied,
            "execution_plan": reviewed_plan.to_serializable(),
            "apply_errors": apply_result.errors,
        }
        if task_id is not None:
            milestone_result_payload["task_id"] = task_id
        with milestone_result_file.open("w", encoding="utf-8") as file:
            json.dump(milestone_result_payload, file, indent=4)
        run_any_gate = bool(
            not defer_post_apply_gates and (run_validation_gate or test_command)
        )
        if defer_post_apply_gates:
            gates = [
                {
                    "name": "post_apply_gates_deferred",
                    "ok": True,
                    "message": "Post-apply gates deferred (run by task orchestration).",
                    "details": {},
                }
            ]
            gates_ok = True
        else:
            if run_any_gate:
                bus.emit(PHASE_STARTED, phase="validation", label="post-apply gates")
            gates = run_gates_for_milestone(
                milestone_id,
                run_validation_gate=run_validation_gate,
                test_command=test_command,
                timeout_seconds=test_timeout_seconds,
                output_max_chars=test_output_max_chars,
                event_bus=bus,
            )
            gates_ok = all(g.get("ok") for g in gates) if gates else True
            if apply_ok and gates_ok:
                fc_run_id = (getattr(event_bus, "run_id", "") or "").strip() or uuid.uuid4().hex[
                    :16
                ]
                changed_paths = set(apply_result.normalized_files_changed())
                # Also analyze targeted python files even when write_file is a noop.
                # This prevents false-success when an earlier attempt wrote a scaffold
                # but later attempts re-apply an identical stub (no further diffs).
                for a in reviewed_plan.actions:
                    rel = getattr(a, "rel_path", None)
                    if not isinstance(rel, str):
                        continue
                    if not rel.endswith(".py"):
                        continue
                    # Mirror write_file canonicalization (examples/ -> src/) for analysis.
                    if type(a).__name__ == "ActionWriteFile" and rel.startswith("examples/"):
                        rel = "src/" + rel[len("examples/") :]
                    changed_paths.add(str(Paths.BASE_DIR / rel))

                changed_paths = list(changed_paths)
                all_stub_recs, stub_fails = analyze_changed_python_files(
                    changed_paths,
                    Paths.BASE_DIR,
                    expected_behavior_signals=(
                        list(task_ir.behavior_signals)
                        if task_ir is not None and task_ir.task_type == "behavioral"
                        else None
                    ),
                )
                _stub_art = persist_stub_detection_results(
                    Paths.BASE_DIR, fc_run_id, all_stub_recs
                )
                if stub_fails:
                    sg_msg = (
                        "Stub detection: structural scaffold without required behavior. "
                        + ", ".join(r["rel_path"] for r in stub_fails)
                    )
                    gates = list(gates) + [
                        {
                            "name": "stub_detection",
                            "ok": False,
                            "message": sg_msg,
                            "details": {
                                "stub_files": stub_fails,
                                "artifact_path": str(_stub_art),
                                "run_id": fc_run_id,
                            },
                        }
                    ]
                    gates_ok = False
            if run_any_gate:
                bus.emit(
                    PHASE_COMPLETED,
                    phase="validation",
                    ok=gates_ok,
                    message=summarize_gate_results(gates),
                )
        ok_final = apply_ok and gates_ok
        gate_summary = summarize_gate_results(gates)
        artifact_summary = apply_result.human_summary()

        if task_id is not None and ok_final and mark_task_complete:
            _mark_task_done_and_maybe_milestone(
                milestone_id,
                task_id,
                parent_milestone=milestone,
                reviewed_plan=reviewed_plan,
                success_summary=_build_execution_summary(
                    len(reviewed_plan.actions), apply_result
                ),
            )

        result_payload = {
            "kind": "reviewed_plan_apply",
            "plan_id": plan_id,
            "milestone_id": milestone_id,
            "task_id": task_id,
            "title": apply_milestone.title,
            "planner_mode": payload.get("planner_mode", "deterministic"),
            "planner_metadata": payload.get("planner_metadata", {}),
            "review_enforcement": payload.get("review_enforcement", {}),
            "ok": ok_final,
            "apply_ok": apply_ok,
            "gates_ok": gates_ok,
            "artifact_summary": artifact_summary,
            "gate_summary": gate_summary,
            "gate_results": gates,
            "policy": {
                "run_validation_gate": run_validation_gate,
                "test_command": test_command,
                "test_timeout_seconds": test_timeout_seconds,
                "test_output_max_chars": test_output_max_chars,
                "defer_post_apply_gates": defer_post_apply_gates,
                "mark_task_complete": mark_task_complete,
                "record_milestone_attempt": record_milestone_attempt,
            },
            "files_changed": apply_result.normalized_files_changed(),
            "actions_applied": apply_result.actions_applied,
            "errors": apply_result.errors,
            "warnings": payload.get("warnings", []),
        }
        safe_id = plan_id.replace("/", "_")
        reviewed_result_file = result_dir / f"reviewed_apply_{safe_id}.json"
        with reviewed_result_file.open("w", encoding="utf-8") as file:
            json.dump(result_payload, file, indent=4)

        status = "success" if ok_final else "failure"
        err = None
        if not apply_ok:
            err = "; ".join(apply_result.errors)
        elif not gates_ok:
            failed_msgs = [g.get("message", "") for g in gates if not g.get("ok")]
            err = "; ".join(failed_msgs) or "Post-apply gate failure."
        if record_milestone_attempt:
            RunHistory.log_milestone_attempt(
                milestone_id=milestone_id,
                milestone_title=milestone.title,
                status=status,
                error_message=err,
                artifact_summary=f"{artifact_summary}; gates: {gate_summary}",
            )

        ret = {
            "ok": ok_final,
            "apply_ok": apply_ok,
            "gates_ok": gates_ok,
            "plan_id": plan_id,
            "milestone_id": milestone_id,
            "title": apply_milestone.title,
            "planner_mode": payload.get("planner_mode", "deterministic"),
            "planner_metadata": payload.get("planner_metadata", {}),
            "review_enforcement": payload.get("review_enforcement", {}),
            "artifact_summary": artifact_summary,
            "gate_summary": gate_summary,
            "gate_results": gates,
            "policy": {
                "run_validation_gate": run_validation_gate,
                "test_command": test_command,
                "test_timeout_seconds": test_timeout_seconds,
                "test_output_max_chars": test_output_max_chars,
                "defer_post_apply_gates": defer_post_apply_gates,
                "mark_task_complete": mark_task_complete,
                "record_milestone_attempt": record_milestone_attempt,
            },
            "files_changed": apply_result.normalized_files_changed(),
            "actions_applied": apply_result.actions_applied,
            "errors": apply_result.errors,
            "warnings": payload.get("warnings", []),
            "result_artifact": str(reviewed_result_file),
            "message": "" if ok_final else (err or "Reviewed plan apply failed."),
        }
        if task_id is not None:
            ret["task_id"] = task_id
        return ret

    @staticmethod
    def _execute_milestone_internal(milestone_id: int) -> None:
        try:
            milestone = MilestoneService.get_milestone(milestone_id)
        except ValueError as exc:
            print(f"Milestone definition error: {exc}")
            return
        if not milestone:
            print("Invalid milestone ID.")
            return

        # Load or initialize milestone state
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        if state_file.exists():
            with state_file.open("r", encoding="utf-8") as file:
                state = json.load(file)
        else:
            state = {}

        # Normalize any legacy/non-uniform entries so we always store
        # `{ "status": ..., "attempts": ... }` after this point.
        normalized_changed = False
        for k in list(state.keys()):
            if isinstance(state.get(k), str):
                normalized_changed = True
            state[k] = normalize_milestone_state_value(state.get(k))
        if normalized_changed:
            with state_file.open("w", encoding="utf-8") as file:
                json.dump(state, file, indent=4)

        milestone_state = normalize_milestone_state_value(state.get(str(milestone_id)))

        # Dependency eligibility check.
        deps_ok = True
        for dep_id in getattr(milestone, "depends_on", []):
            dep_state = normalize_milestone_state_value(state.get(str(dep_id)))
            if dep_state["status"] != "completed":
                deps_ok = False
                break

        runnable_statuses = {"not_started", "retry_pending"}
        if milestone_state["status"] not in runnable_statuses:
            print("Milestone is not runnable in its current state.")
            return

        if not deps_ok:
            print("Milestone is blocked by unmet prerequisites.")
            return

        # Increment attempts and set status to in_progress
        milestone_state["attempts"] += 1
        milestone_state["status"] = "in_progress"
        state[str(milestone_id)] = milestone_state
        with state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)

        # Log the start of execution
        entry = RunHistoryEntry(
            task=f"Execute milestone {milestone_id} (Attempt {milestone_state['attempts']})",
            summary=f"{milestone.title}: {milestone.objective}",
            status="started",
            timestamp=datetime.now(),
        )
        RunHistory.log_run(entry)

        # Perform execution step
        result_dir = Paths.SYSTEM_DIR / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_file = result_dir / f"milestone_{milestone_id}.json"

        try:
            plan = DeterministicPlanner().build_plan(milestone)
        except ValueError as exc:
            Executor._write_failure_payload(
                result_file,
                milestone_id,
                milestone,
                error=f"Invalid forge actions: {exc}",
            )
            Executor._finalize_failed_or_retry(
                milestone_id,
                milestone,
                milestone_state,
                state,
                state_file,
                result_file,
                reason=f"Invalid forge actions: {exc}",
            )
            return

        applier = ArtifactActionApplier(Paths)
        apply_result = applier.apply(plan, milestone, project_profile=None)

        files_norm = apply_result.normalized_files_changed()
        summary = _build_execution_summary(len(plan.actions), apply_result)

        result_payload: dict = {
            "id": milestone_id,
            "title": milestone.title,
            "summary": summary,
            "artifact_summary": apply_result.human_summary(),
            "files_changed": files_norm,
            "actions_applied": apply_result.actions_applied,
            "execution_plan": plan.to_serializable(),
            "apply_errors": apply_result.errors,
        }

        with result_file.open("w", encoding="utf-8") as file:
            json.dump(result_payload, file, indent=4)

        # Perform validation step
        is_valid, reason = Validator.validate_milestone_with_report(milestone_id)
        if is_valid:
            # Log completion
            entry = RunHistoryEntry(
                task=f"Execute milestone {milestone_id} (Attempt {milestone_state['attempts']})",
                summary=f"{milestone.title}: {milestone.objective}",
                status="completed",
                timestamp=datetime.now(),
            )
            RunHistory.log_run(entry)

            # Update state to completed
            milestone_state["status"] = "completed"

            # Record append-only decision history unless the plan already added a decision.
            if not _plan_has_add_decision(plan):
                DecisionTracker.append_milestone_success_decision(
                    milestone_id=milestone_id,
                    milestone_title=milestone.title,
                    summary=summary,
                )

            RunHistory.log_milestone_attempt(
                milestone_id=milestone_id,
                milestone_title=milestone.title,
                status="success",
                artifact_summary=apply_result.human_summary(),
            )
        else:
            if milestone_state["attempts"] < MAX_RETRIES:
                milestone_state["status"] = "retry_pending"
            else:
                milestone_state["status"] = "failed"

            # Store validation error for operator visibility.
            try:
                with result_file.open("r", encoding="utf-8") as file:
                    updated_payload = json.load(file)
            except Exception:
                updated_payload = {}
            updated_payload["validation_error"] = reason
            with result_file.open("w", encoding="utf-8") as file:
                json.dump(updated_payload, file, indent=4)

            # Log failure
            entry = RunHistoryEntry(
                task=f"Execute milestone {milestone_id} (Attempt {milestone_state['attempts']})",
                summary=f"{milestone.title}: {milestone.objective}",
                status=milestone_state["status"],
                timestamp=datetime.now(),
            )
            RunHistory.log_run(entry)

            RunHistory.log_milestone_attempt(
                milestone_id=milestone_id,
                milestone_title=milestone.title,
                status="failure",
                error_message=reason,
                artifact_summary=apply_result.human_summary()
                if apply_result.actions_applied
                else None,
            )

        # Persist updated state
        state[str(milestone_id)] = milestone_state
        with state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)

    @staticmethod
    def _write_failure_payload(
        result_file,
        milestone_id: int,
        milestone,
        error: str,
    ) -> None:
        payload = {
            "id": milestone_id,
            "title": milestone.title,
            "summary": "",
            "artifact_summary": "",
            "files_changed": [],
            "actions_applied": [],
            "execution_plan": {},
            "apply_errors": [error],
            "validation_error": error,
        }
        with result_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4)

    @staticmethod
    def _finalize_failed_or_retry(
        milestone_id: int,
        milestone,
        milestone_state: dict,
        state: dict,
        state_file,
        result_file,
        reason: str,
    ) -> None:
        if milestone_state["attempts"] < MAX_RETRIES:
            milestone_state["status"] = "retry_pending"
        else:
            milestone_state["status"] = "failed"

        entry = RunHistoryEntry(
            task=f"Execute milestone {milestone_id} (Attempt {milestone_state['attempts']})",
            summary=f"{milestone.title}: {milestone.objective}",
            status=milestone_state["status"],
            timestamp=datetime.now(),
        )
        RunHistory.log_run(entry)
        RunHistory.log_milestone_attempt(
            milestone_id=milestone_id,
            milestone_title=milestone.title,
            status="failure",
            error_message=reason,
        )
        state[str(milestone_id)] = milestone_state
        with state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)
