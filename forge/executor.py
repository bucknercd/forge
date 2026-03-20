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

from forge.llm import LLMClient, StubLLMClient
from forge.prompt_builder import build_execution_prompt, build_retry_prompt

MAX_RETRIES = 2

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
    def execute_milestone(milestone_id: int, llm_client: LLMClient | None = None):
        return Executor._execute_milestone_internal(milestone_id, llm_client=llm_client)

    @staticmethod
    def _execute_milestone_internal(milestone_id: int, llm_client: LLMClient | None):
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
            timestamp=datetime.now()
        )
        RunHistory.log_run(entry)

        # Perform execution step
        result_dir = Paths.SYSTEM_DIR / "results"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_file = result_dir / f"milestone_{milestone_id}.json"

        llm_client = llm_client or StubLLMClient()

        attempt_number = milestone_state["attempts"]

        previous_validation_error = ""
        if attempt_number > 1 and result_file.exists():
            try:
                with result_file.open("r", encoding="utf-8") as file:
                    previous = json.load(file)
                previous_validation_error = previous.get("validation_error", "") or ""
            except Exception:
                previous_validation_error = ""

        if attempt_number <= 1 or not previous_validation_error:
            prompt = build_execution_prompt(milestone, attempt_number)
        else:
            prompt = build_retry_prompt(milestone, attempt_number, previous_validation_error)

        llm_output = llm_client.generate(prompt)

        result_payload = {"id": milestone_id, "title": milestone.title}
        if isinstance(llm_output, str) and llm_output.strip():
            try:
                parsed = json.loads(llm_output)
                if isinstance(parsed, dict) and parsed.get("summary") is not None:
                    result_payload["summary"] = parsed.get("summary")
                    result_payload["llm_output"] = llm_output
                else:
                    result_payload["raw_output"] = llm_output
            except Exception:
                result_payload["raw_output"] = llm_output

        with result_file.open("w", encoding="utf-8") as file:
            json.dump(result_payload, file, indent=4)

        # Create the plan file
        plan_dir = Paths.SYSTEM_DIR / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / f"milestone_{milestone_id}.md"
        with plan_file.open("w", encoding="utf-8") as file:
            file.write(f"# Plan for {milestone.title}\n\n")
            file.write(f"## Objective\n{milestone.objective}\n\n")
            file.write(f"## Scope\n{milestone.scope}\n\n")
            file.write(f"## Validation\n{milestone.validation}\n")

        # Perform validation step
        is_valid, reason = Validator.validate_milestone_with_report(milestone_id)
        if is_valid:
            # Log completion
            entry = RunHistoryEntry(
                task=f"Execute milestone {milestone_id} (Attempt {milestone_state['attempts']})",
                summary=f"{milestone.title}: {milestone.objective}",
                status="completed",
                timestamp=datetime.now()
            )
            RunHistory.log_run(entry)

            # Update state to completed
            milestone_state["status"] = "completed"

            # Record append-only decision history for successful execution.
            DecisionTracker.append_milestone_success_decision(
                milestone_id=milestone_id,
                milestone_title=milestone.title,
                summary=str(result_payload.get("summary", "Execution completed successfully.")),
            )
        else:
            if milestone_state["attempts"] < MAX_RETRIES:
                milestone_state["status"] = "retry_pending"
            else:
                milestone_state["status"] = "failed"

            # Store validation error for prompt retry context.
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
                timestamp=datetime.now()
            )
            RunHistory.log_run(entry)

        # Persist updated state
        state[str(milestone_id)] = milestone_state
        with state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)