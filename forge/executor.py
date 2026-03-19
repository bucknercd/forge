from datetime import datetime
import json
from forge.paths import Paths
from forge.design_manager import MilestoneService
from forge.run_history import RunHistory
from forge.models import RunHistoryEntry
from forge.validator import Validator

MAX_RETRIES = 2

class Executor:
    @staticmethod
    def execute_milestone(milestone_id: int):
        milestone = MilestoneService.get_milestone(milestone_id)
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

        milestone_state = state.get(str(milestone_id), {"status": "not_started", "attempts": 0})

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
        with result_file.open("w", encoding="utf-8") as file:
            json.dump({
                "id": milestone_id,
                "title": milestone.title,
                "summary": "Execution completed successfully."
            }, file, indent=4)

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
        if Validator.validate_milestone(milestone_id):
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
        else:
            if milestone_state["attempts"] < MAX_RETRIES:
                milestone_state["status"] = "retry_pending"
            else:
                milestone_state["status"] = "failed"

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