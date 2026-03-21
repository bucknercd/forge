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
