from datetime import datetime
import json
from forge.paths import Paths
from forge.design_manager import MilestoneService
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
from forge.gate_runner import run_gates_for_milestone, summarize_gate_results
from forge.reviewed_plan import (
    load_reviewed_plan,
    save_reviewed_plan,
    validate_reviewed_plan,
)

MAX_RETRIES = 2


def _plan_has_add_decision(plan: ExecutionPlan) -> bool:
    return any(isinstance(a, ActionAddDecision) for a in plan.actions)


def _build_execution_summary(
    planned_action_count: int, apply_result: ApplyResult
) -> str:
    return (
        f"Applied {planned_action_count} planned action(s). "
        f"{apply_result.human_summary()}"
    )


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
        Executor.execute_milestone(milestone_id)

        updated_state = state_repository.get(milestone_id)
        status = updated_state.get("status")
        if status == "completed":
            return {
                "outcome": "complete",
                "milestone_id": milestone_id,
                "message": f"Milestone {milestone_id} completed.",
            }

        return {
            "outcome": "executed",
            "milestone_id": milestone_id,
            "message": f"Milestone {milestone_id} updated status={status}.",
        }

    @staticmethod
    def execute_milestone(milestone_id: int) -> None:
        return Executor._execute_milestone_internal(milestone_id)

    @staticmethod
    def preview_milestone(milestone_id: int) -> dict:
        """
        Build and simulate a milestone execution plan without side effects.
        """
        try:
            milestone = MilestoneService.get_milestone(milestone_id)
        except ValueError as exc:
            return {"ok": False, "message": f"Milestone definition error: {exc}"}
        if not milestone:
            return {"ok": False, "message": "Invalid milestone ID."}

        try:
            plan = ExecutionPlanBuilder.build(milestone)
            _ = ExecutionPlanBuilder.parse_validation_rules(milestone)
        except ValueError as exc:
            return {"ok": False, "message": str(exc), "milestone_id": milestone_id}

        applier = ArtifactActionApplier(Paths)
        preview = applier.apply(plan, milestone, dry_run=True)
        return {
            "ok": len(preview.errors) == 0,
            "milestone_id": milestone.id,
            "title": milestone.title,
            "execution_plan": plan.to_serializable(),
            "files_changed": preview.normalized_files_changed(),
            "artifact_summary": preview.human_summary(),
            "actions_applied": preview.actions_applied,
            "errors": preview.errors,
        }

    @staticmethod
    def save_reviewed_plan_for_milestone(milestone_id: int) -> dict:
        preview = Executor.preview_milestone(milestone_id)
        if not preview.get("ok"):
            return preview
        try:
            milestone = MilestoneService.get_milestone(milestone_id)
            if not milestone:
                return {"ok": False, "message": "Invalid milestone ID."}
            plan = ExecutionPlan.from_serializable(preview["execution_plan"])
            payload = save_reviewed_plan(milestone_id, milestone.title, plan)
            preview["plan_id"] = payload["plan_id"]
            preview["plan_file"] = str((Paths.SYSTEM_DIR / "reviewed_plans" / f"{payload['plan_id']}.json"))
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
        return Executor.preview_milestone(next_milestone.id)

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
    ) -> dict:
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

        try:
            current_plan = ExecutionPlanBuilder.build(milestone)
        except ValueError as exc:
            return {"ok": False, "message": f"Current milestone plan invalid: {exc}"}

        ok, reason = validate_reviewed_plan(payload, current_plan)
        if not ok:
            return {"ok": False, "message": reason, "plan_id": plan_id, "milestone_id": milestone_id}

        reviewed_plan = ExecutionPlan.from_serializable(payload["plan"])
        applier = ArtifactActionApplier(Paths)
        apply_result = applier.apply(reviewed_plan, milestone, dry_run=False)
        # Persist a milestone result artifact so optional validation gate can
        # reuse the existing Validator contract.
        result_dir = Paths.SYSTEM_DIR / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        milestone_result_file = result_dir / f"milestone_{milestone_id}.json"
        milestone_result_payload = {
            "id": milestone_id,
            "title": milestone.title,
            "summary": _build_execution_summary(len(reviewed_plan.actions), apply_result),
            "artifact_summary": apply_result.human_summary(),
            "files_changed": apply_result.normalized_files_changed(),
            "actions_applied": apply_result.actions_applied,
            "execution_plan": reviewed_plan.to_serializable(),
            "apply_errors": apply_result.errors,
        }
        with milestone_result_file.open("w", encoding="utf-8") as file:
            json.dump(milestone_result_payload, file, indent=4)
        gates = run_gates_for_milestone(
            milestone_id,
            run_validation_gate=run_validation_gate,
            test_command=test_command,
        )
        gates_ok = all(g.get("ok") for g in gates) if gates else True
        apply_ok = len(apply_result.errors) == 0
        ok_final = apply_ok and gates_ok
        gate_summary = summarize_gate_results(gates)
        artifact_summary = apply_result.human_summary()

        result_payload = {
            "kind": "reviewed_plan_apply",
            "plan_id": plan_id,
            "milestone_id": milestone_id,
            "title": milestone.title,
            "ok": ok_final,
            "apply_ok": apply_ok,
            "gates_ok": gates_ok,
            "artifact_summary": artifact_summary,
            "gate_summary": gate_summary,
            "gate_results": gates,
            "files_changed": apply_result.normalized_files_changed(),
            "actions_applied": apply_result.actions_applied,
            "errors": apply_result.errors,
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
        RunHistory.log_milestone_attempt(
            milestone_id=milestone_id,
            milestone_title=milestone.title,
            status=status,
            error_message=err,
            artifact_summary=f"{artifact_summary}; gates: {gate_summary}",
        )

        return {
            "ok": ok_final,
            "apply_ok": apply_ok,
            "gates_ok": gates_ok,
            "plan_id": plan_id,
            "milestone_id": milestone_id,
            "title": milestone.title,
            "artifact_summary": artifact_summary,
            "gate_summary": gate_summary,
            "gate_results": gates,
            "files_changed": apply_result.normalized_files_changed(),
            "actions_applied": apply_result.actions_applied,
            "errors": apply_result.errors,
            "result_artifact": str(reviewed_result_file),
            "message": "" if ok_final else (err or "Reviewed plan apply failed."),
        }

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
            plan = ExecutionPlanBuilder.build(milestone)
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
        apply_result = applier.apply(plan, milestone)

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
