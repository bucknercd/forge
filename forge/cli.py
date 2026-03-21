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
from forge.project_status import analyze_project_status
from forge.execution.plan import ExecutionPlanBuilder

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
        result = Paths.initialize_project()
        for directory in result["created_dirs"]:
            print(f"Created: {directory}")
        for file_path in result["created_files"]:
            print(f"Created: {file_path}")
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
        report = analyze_project_status()
        print("Repository Status:")
        print(f"- Project State: {report['state']}")

        if report["missing_paths"]:
            print("- Missing required paths:")
            for path in report["missing_paths"]:
                print(f"  - {path}")
            print("- Hint: run `forge init`")

        if report["empty_files"]:
            print("- Empty files:")
            for path in report["empty_files"]:
                print(f"  - {path}")

        if report["template_only_files"]:
            print("- Template-only files (needs customization):")
            for path in report["template_only_files"]:
                print(f"  - {path}")

        if report["milestones_issue"]:
            print("- Milestones file has no recognized milestone headings (## Milestone ...).")

        if report["state"] == "ready":
            print("- Project is minimally ready for Forge workflows.")

        # Include runtime milestone state summary when available
        state = ForgeCLI.load_milestone_state()
        if state:
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

        try:
            next_milestone, report = selector.get_next_milestone_with_report()
        except ValueError as exc:
            print(f"Milestone definition error: {exc}")
            return

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
    def milestone_lint(milestone_id: int | None = None) -> bool:
        """Lint milestone action/validation definitions without executing actions."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return False

        try:
            milestones = MilestoneService.list_milestones()
        except ValueError as exc:
            print(f"Milestone definition error: {exc}")
            print("Lint Summary: 1 error(s) across 0 milestone(s) checked.")
            return False

        if milestone_id is not None:
            milestones = [m for m in milestones if m.id == milestone_id]
            if not milestones:
                print(f"Milestone {milestone_id} not found.")
                print("Lint Summary: 1 error(s) across 0 milestone(s) checked.")
                return False

        total_errors = 0
        checked = 0
        for m in milestones:
            checked += 1
            errors: list[str] = []

            if not m.forge_actions:
                errors.append("Missing Forge Actions block.")
            if m.forge_actions and not m.forge_validation:
                errors.append("Missing Forge Validation block.")

            if not errors:
                try:
                    _plan = ExecutionPlanBuilder.build(m)
                except ValueError as exc:
                    errors.append(str(exc))
                try:
                    _rules = ExecutionPlanBuilder.parse_validation_rules(m)
                except ValueError as exc:
                    errors.append(str(exc))

            if errors:
                total_errors += len(errors)
                print(f"[FAIL] Milestone {m.id}: {m.title}")
                for e in errors:
                    print(f"  - {e}")
            else:
                print(f"[OK] Milestone {m.id}: {m.title}")

        print(f"Lint Summary: {total_errors} error(s) across {checked} milestone(s) checked.")
        return total_errors == 0

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

def main() -> int:
    Paths.refresh()
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
    milestone_lint_parser = subparsers.add_parser(
        "milestone-lint", help="Lint milestone execution definitions"
    )
    milestone_lint_parser.add_argument(
        "id", nargs="?", type=int, help="Optional milestone ID to lint"
    )
    subparsers.add_parser("execute-next", help="Execute the next eligible milestone")

    args = parser.parse_args()

    if args.command not in {"init", "status"}:
        is_valid, missing = Paths.project_validation()
        if not is_valid:
            print("Current directory is not an initialized Forge project.")
            print("Run `forge init` to bootstrap required directories/files.")
            if missing:
                print("Missing:")
                for path in missing:
                    print(f"- {path}")
            return 0

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
    elif args.command == "milestone-lint":
        return 0 if ForgeCLI.milestone_lint(args.id) else 1
    elif args.command == "execute-next":
        ForgeCLI.execute_next()
    else:
        parser.print_help()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())