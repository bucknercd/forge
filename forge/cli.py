# forge/cli.py

import argparse
from forge.vision import VisionManager
from forge.design_manager import DesignManager
from forge.decision_tracker import DecisionTracker
from forge.run_history import RunHistory
from forge.paths import Paths
from pathlib import Path
from forge.design_manager import MilestoneService
from datetime import datetime
import json
from forge.executor import Executor
from forge.milestone_selector import MilestoneSelector
from forge.milestone_state import MilestoneStateRepository
from forge.milestone_sync import sync_milestone_state
from forge.milestone_state import normalize_milestone_state_value

class RunHistoryEntry:
    def __init__(self, task, summary, status, timestamp):
        self.task = task
        self.summary = summary
        self.status = status
        self.timestamp = timestamp

class ForgeCLI:
    @staticmethod
    def init():
        """Bootstrap expected directories and files if missing."""
        Paths.DOCS_DIR.mkdir(exist_ok=True)
        for file in [
            Paths.VISION_FILE,
            Paths.REQUIREMENTS_FILE,
            Paths.ARCHITECTURE_FILE,
            Paths.DECISIONS_FILE,
            Paths.MILESTONES_FILE,
        ]:
            if not file.exists():
                file.touch()
                print(f"Created: {file}")
        # Ensure runtime directory exists before touching files under it.
        Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        if not Paths.RUN_HISTORY_FILE.exists():
            Paths.RUN_HISTORY_FILE.touch()
            print(f"Created: {Paths.RUN_HISTORY_FILE}")

        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        if not state_file.exists():
            state_file.write_text("{}", encoding="utf-8")
            print(f"Created: {state_file}")
        print("Forge repository initialized.")

    @staticmethod
    def load_milestone_state() -> dict:
        """Load milestone state from the state file."""
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        if state_file.exists():
            with state_file.open("r", encoding="utf-8") as file:
                raw_state = json.load(file)
                normalized = {}
                for k, v in raw_state.items():
                    normalized[k] = normalize_milestone_state_value(v)
                return normalized
        return {}

    @staticmethod
    def save_milestone_state(state: dict) -> None:
        """Save milestone state to the state file."""
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        with state_file.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=4)

    @staticmethod
    def milestone_status():
        """List all milestones with their current state."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return

        milestones = MilestoneService.list_milestones()
        state = ForgeCLI.load_milestone_state()

        print("Milestone Status:")
        for milestone in milestones:
            milestone_state = state.get(str(milestone.id), "not_started")
            print(f"{milestone.id}. {milestone.title} [{milestone_state}]")

    @staticmethod
    def status():
        """Show current repository state."""
        print("Repository Status:")
        for file in [
            ("Vision", Paths.VISION_FILE),
            ("Requirements", Paths.REQUIREMENTS_FILE),
            ("Architecture", Paths.ARCHITECTURE_FILE),
            ("Decisions", Paths.DECISIONS_FILE),
            ("Milestones", Paths.MILESTONES_FILE),
        ]:
            exists = "Exists" if file[1].exists() else "Missing"
            print(f"- {file[0]}: {exists}")
        if Paths.MILESTONES_FILE.exists():
            milestones = DesignManager.load_document(Paths.MILESTONES_FILE).split("\n## ")
            print(f"- Milestones: {len(milestones) - 1} found")
        if Paths.RUN_HISTORY_FILE.exists():
            history = RunHistory.get_recent_entries(1)
            if history:
                print(f"- Latest Run: {history[0]}")
            else:
                print("- Latest Run: No entries found")

        # Include milestone state summary
        state = ForgeCLI.load_milestone_state()
        print("- Milestone States:")
        for milestone_id, milestone_state in state.items():
            if isinstance(milestone_state, str):
                status = milestone_state
                attempts = 0
            elif isinstance(milestone_state, dict):
                status = milestone_state.get("status", "not_started")
                attempts = milestone_state.get("attempts", 0)
            else:
                status = "not_started"
                attempts = 0
            print(f"  Milestone {milestone_id}: status={status}, attempts={attempts}")

    @staticmethod
    def design_show():
        """Show a concise summary of the current design artifacts."""
        print("Design Artifacts Summary:")
        for file in [
            ("Vision", Paths.VISION_FILE),
            ("Requirements", Paths.REQUIREMENTS_FILE),
            ("Architecture", Paths.ARCHITECTURE_FILE),
            ("Decisions", Paths.DECISIONS_FILE),
        ]:
            if file[1].exists():
                content = DesignManager.load_document(file[1])
                print(f"\n--- {file[0]} ---\n{content[:200]}...\n")
            else:
                print(f"\n--- {file[0]} ---\nMissing\n")

    @staticmethod
    def milestone_list():
        """List milestones parsed from milestones.md."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return
        milestones = DesignManager.load_document(Paths.MILESTONES_FILE).split("\n## ")[1:]
        print("Milestones:")
        for i, milestone in enumerate(milestones, start=1):
            print(f"{i}. {milestone.splitlines()[0]}")

    @staticmethod
    def milestone_show(milestone_id: int):
        """Show a single milestone in detail."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return
        milestones = DesignManager.load_document(Paths.MILESTONES_FILE).split("\n## ")[1:]
        if 1 <= milestone_id <= len(milestones):
            print(f"Milestone {milestone_id}:")
            print(milestones[milestone_id - 1])
        else:
            print("Invalid milestone ID.")

    @staticmethod
    def milestone_start(milestone_id: int):
        """Start a milestone, create a plan file, and record its state."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return

        milestone = MilestoneService.get_milestone(milestone_id)
        if milestone:
            # Create the plan file
            plan_dir = Paths.SYSTEM_DIR / "plans"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_file = plan_dir / f"milestone_{milestone_id}.md"
            with plan_file.open("w", encoding="utf-8") as file:
                file.write(f"# Plan for {milestone.title}\n\n")
                file.write(f"## Objective\n{milestone.objective}\n\n")
                file.write(f"## Scope\n{milestone.scope}\n\n")
                file.write(f"## Validation\n{milestone.validation}\n")

            # Update milestone state
            state_file = Paths.SYSTEM_DIR / "milestone_state.json"
            if state_file.exists():
                with state_file.open("r", encoding="utf-8") as file:
                    state = json.load(file)
            else:
                state = {}

            state[str(milestone_id)] = "in_progress"
            state[str(milestone_id)] = {
                "status": "in_progress",
                "attempts": 0,
            }
            with state_file.open("w", encoding="utf-8") as file:
                json.dump(state, file, indent=4)

            # Log the run-history entry
            entry = RunHistoryEntry(
                task=f"Start milestone {milestone_id}",
                summary=f"{milestone.title}: {milestone.objective}",
                status="started",
                timestamp=datetime.now()
            )
            RunHistory.log_run(entry)

            print(f"Started milestone {milestone_id}: {milestone.title}")
        else:
            print("Invalid milestone ID.")

    @staticmethod
    def milestone_execute(milestone_id: int):
        """Execute a milestone."""
        Executor.execute_milestone(milestone_id)

    @staticmethod
    def milestone_retry(milestone_id: int):
        """Retry a milestone if it is in retry_pending state."""
        state_file = Paths.SYSTEM_DIR / "milestone_state.json"
        if not state_file.exists():
            print("No milestone state found.")
            return

        with state_file.open("r", encoding="utf-8") as file:
            state = json.load(file)

        milestone_state = normalize_milestone_state_value(state.get(str(milestone_id)))
        if milestone_state["status"] != "retry_pending":
            print("Milestone is not in a retryable state.")
            return

        Executor.execute_milestone(milestone_id)

    @staticmethod
    def milestone_next():
        milestone_service = MilestoneService()
        state_repository = MilestoneStateRepository(Paths.SYSTEM_DIR / "milestone_state.json")
        selector = MilestoneSelector(milestone_service, state_repository)

        next_milestone, report = selector.get_next_milestone_with_report()

        if next_milestone is None:
            kind = report.get("kind")
            if kind == "all_complete":
                print("All milestones completed.")
            elif kind == "in_progress":
                print("Progress is already in progress.")
            else:
                print("Progress is blocked by failed/unmet prerequisites.")
            return

        state = state_repository.get(next_milestone.id)

        print(f"Next milestone: {next_milestone.id}. {next_milestone.title}")
        print(f"Objective: {next_milestone.objective or 'No objective provided'}")
        print(f"Status: {state['status']}")

    @staticmethod
    def milestone_sync_state():
        """Reconcile milestone_state.json against parsed milestones."""
        result = sync_milestone_state()
        if result["unchanged"]:
            print("Milestone state is already synchronized.")
            return

        print("Milestone state synchronized.")
        if result["initialized"]:
            print("Initialized state file.")
        if result["added"]:
            print(f"Added entries: {len(result['added'])}")
        if result["removed"]:
            print(f"Removed entries: {len(result['removed'])}")

    @staticmethod
    def execute_next():
        """Execute the next eligible milestone in one orchestration step."""
        result = Executor.execute_next()
        outcome = result.get("outcome")
        milestone_id = result.get("milestone_id")
        print(result.get("message", ""))
        if milestone_id is not None and outcome in {"executed", "complete"}:
            # Provide a tiny bit of context without leaking orchestration internals.
            print(f"Milestone ID: {milestone_id}")

def main():
    parser = argparse.ArgumentParser(prog="forge", description="Forge CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Init command
    subparsers.add_parser("init", help="Bootstrap expected directories and files")

    # Status command
    subparsers.add_parser("status", help="Show current repository state")

    # Design commands
    subparsers.add_parser("design-show", help="Show a summary of the current design artifacts")

    # Milestone commands
    subparsers.add_parser("milestone-list", help="List milestones")
    milestone_show_parser = subparsers.add_parser("milestone-show", help="Show a specific milestone")
    milestone_show_parser.add_argument("id", type=int, help="Milestone ID")

    # Run history command
    subparsers.add_parser("run-history", help="Show recent run-history entries")

    # Execute milestone command
    subparsers.add_parser("milestone-execute", help="Execute a specific milestone").add_argument("id", type=int, help="Milestone ID")

    # Retry milestone command
    subparsers.add_parser("milestone-retry", help="Retry a specific milestone").add_argument("id", type=int, help="Milestone ID")

    subparsers.add_parser("milestone-next", help="Print the next milestone")
    subparsers.add_parser("milestone-sync-state", help="Reconcile milestone state with parsed milestones")
    subparsers.add_parser("execute-next", help="Execute the next eligible milestone")

    args = parser.parse_args()

    if args.command == "init":
        ForgeCLI.init()
    elif args.command == "status":
        ForgeCLI.status()
    elif args.command == "design-show":
        ForgeCLI.design_show()
    elif args.command == "milestone-list":
        ForgeCLI.milestone_list()
    elif args.command == "milestone-show":
        ForgeCLI.milestone_show(args.id)
    elif args.command == "milestone-start":
        ForgeCLI.milestone_start(args.id)
    elif args.command == "milestone-execute":
        ForgeCLI.milestone_execute(args.id)
    elif args.command == "milestone-retry":
        ForgeCLI.milestone_retry(args.id)
    elif args.command == "run-history":
        ForgeCLI.run_history()
    elif args.command == "milestone-next":
        ForgeCLI.milestone_next()
    elif args.command == "milestone-sync-state":
        ForgeCLI.milestone_sync_state()
    elif args.command == "execute-next":
        ForgeCLI.execute_next()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()