# forge/cli.py

import argparse
import uuid
from dataclasses import asdict

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
from forge.cli_output import (
    serialize_apply_plan_result,
    serialize_lint_result,
    serialize_preview_result,
)
from forge.policy_config import (
    ReviewedApplyPolicy,
    load_reviewed_apply_policy,
    merge_reviewed_apply_policy,
)
from forge.planner_resolver import resolve_planner
from forge.llm_resolve import resolve_llm_client_from_policy
from forge.policy_config import load_planner_policy
from forge.milestone_synthesis import (
    accept_synthesized_milestones,
    load_synthesized_milestones,
    synthesize_milestones,
)
from forge.run_event_handlers import (
    CliProgressHandler,
    EventListCollector,
    JsonlRunLogHandler,
    write_run_meta,
)
from forge.run_events import RunEventBus
from forge.task_service import (
    expand_milestone_to_tasks,
    get_task,
    list_tasks,
    task_count_for_milestone,
)
from forge.vertical_slice import (
    read_vision_file_text,
    resolve_vision_file_path,
    run_vertical_slice,
)


def _review_enforcement_status(planner, policy, *, save_plan: bool) -> dict:
    enabled = bool(getattr(policy, "require_review_for_nondeterministic", False))
    required = bool(planner and planner.metadata().get("is_nondeterministic"))
    compliant = (not enabled) or (not required) or bool(save_plan)
    return {
        "enabled": enabled,
        "required_for_plan": required and enabled,
        "compliant": compliant,
        "requires_save_plan": bool(enabled and required),
    }


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
        """List milestones parsed from milestones.md (with status and task counts)."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return
        try:
            milestones = MilestoneService.list_milestones()
        except ValueError as exc:
            print(f"Milestone definition error: {exc}")
            return
        state_path = Paths.SYSTEM_DIR / "milestone_state.json"
        state: dict = {}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                state = {}
        print("Milestones:")
        for m in milestones:
            raw = state.get(str(m.id), {})
            st = normalize_milestone_state_value(raw).get("status", "unknown")
            n_tasks = task_count_for_milestone(m.id)
            task_part = f" | tasks: {n_tasks}" if n_tasks else " | tasks: —"
            summ = (m.summary or "").strip()
            summ_part = f"\n   summary: {summ}" if summ else ""
            print(
                f"{m.id}. {m.title} | status: {st}{task_part}\n"
                f"   objective: {m.objective[:120]}{'…' if len(m.objective) > 120 else ''}"
                f"{summ_part}"
            )

    @staticmethod
    def milestone_show(milestone_id: int):
        """Show a single milestone (parsed fields + task hint)."""
        if not Paths.MILESTONES_FILE.exists():
            print("Milestones file is missing.")
            return
        m = MilestoneService.get_milestone(milestone_id)
        if not m:
            print("Invalid milestone ID.")
            return
        n = task_count_for_milestone(milestone_id)
        print(f"Milestone {milestone_id}: {m.title}")
        if (m.summary or "").strip():
            print(f"Summary: {m.summary}")
        print(f"Objective: {m.objective}")
        print(f"Scope: {m.scope}")
        print(f"Validation: {m.validation}")
        if m.depends_on:
            print(f"Depends on: {m.depends_on}")
        print(f"Forge Actions: {len(m.forge_actions)} line(s)")
        print(f"Forge Validation: {len(m.forge_validation)} line(s)")
        if n:
            print(f"Expanded tasks: {n}")
        else:
            print(
                f"Expanded tasks: — (run `forge task-expand --milestone {milestone_id}`)"
            )
        if n:
            print(f"Inspect: `forge task-list --milestone {milestone_id}`")

    @staticmethod
    def task_expand(milestone_id: int, *, force: bool = False, json_mode: bool = False) -> bool:
        """Expand milestone into tasks JSON (multi-task heuristic; compat fallback)."""
        r = expand_milestone_to_tasks(milestone_id=milestone_id, force=force)
        if json_mode:
            print(json.dumps(r, indent=2, sort_keys=True))
        else:
            print(r.get("message", ""))
        return bool(r.get("ok"))

    @staticmethod
    def task_list(milestone_id: int, json_mode: bool = False) -> None:
        tasks = list_tasks(milestone_id)
        if json_mode:
            print(json.dumps([asdict(t) for t in tasks], indent=2, sort_keys=True))
            return
        if not tasks:
            print(
                f"No tasks for milestone {milestone_id}. "
                f"Run `forge task-expand --milestone {milestone_id}`."
            )
            return
        print(f"Tasks for milestone {milestone_id}:")
        for t in tasks:
            deps_s = (
                ", ".join(str(d) for d in t.depends_on) if t.depends_on else "—"
            )
            obj = t.objective.replace("\n", " ")
            if len(obj) > 100:
                obj = obj[:97] + "…"
            print(f"  [{t.id}] {t.title}")
            print(f"      objective: {obj or '—'}")
            print(f"      depends_on: {deps_s}")

    @staticmethod
    def task_show(milestone_id: int, task_id: int, json_mode: bool = False) -> None:
        t = get_task(milestone_id, task_id)
        if not t:
            print(f"No task {task_id} for milestone {milestone_id}.")
            return
        if json_mode:
            print(json.dumps(asdict(t), indent=2, sort_keys=True))
            return
        print(f"Milestone {milestone_id} task {task_id}: {t.title}")
        print(f"Status: {t.status}")
        print(f"Objective: {t.objective}")
        if (t.summary or "").strip():
            print(f"Summary: {t.summary}")
        if t.depends_on:
            print(f"Depends on: {t.depends_on}")
        if t.files_allowed:
            print(f"Files allowed: {t.files_allowed}")
        print(f"Validation: {t.validation}")
        if (t.done_when or "").strip():
            print(f"Done when: {t.done_when}")
        print("Forge Actions:")
        for line in t.forge_actions:
            print(f"  - {line}")
        print("Forge Validation:")
        for line in t.forge_validation:
            print(f"  - {line}")

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
    def milestone_lint(milestone_id: int | None = None, json_mode: bool = False) -> bool:
        """Lint milestone action/validation definitions without executing actions."""
        payload = ForgeCLI._collect_milestone_lint_result(milestone_id)
        if json_mode:
            print(json.dumps(serialize_lint_result(payload), indent=2, sort_keys=True))
            return bool(payload.get("ok"))
        ForgeCLI._print_lint_human(payload)
        return bool(payload.get("ok"))

    @staticmethod
    def _collect_milestone_lint_result(milestone_id: int | None = None) -> dict:
        if not Paths.MILESTONES_FILE.exists():
            return {
                "command": "milestone-lint",
                "ok": False,
                "selected_milestone_id": milestone_id,
                "checked": 0,
                "total_errors": 1,
                "milestones": [],
                "message": "Milestones file is missing.",
            }

        try:
            milestones = MilestoneService.list_milestones()
        except ValueError as exc:
            return {
                "command": "milestone-lint",
                "ok": False,
                "selected_milestone_id": milestone_id,
                "checked": 0,
                "total_errors": 1,
                "milestones": [],
                "message": f"Milestone definition error: {exc}",
            }

        if milestone_id is not None:
            milestones = [m for m in milestones if m.id == milestone_id]
            if not milestones:
                return {
                    "command": "milestone-lint",
                    "ok": False,
                    "selected_milestone_id": milestone_id,
                    "checked": 0,
                    "total_errors": 1,
                    "milestones": [],
                    "message": f"Milestone {milestone_id} not found.",
                }

        total_errors = 0
        milestones_out: list[dict] = []
        for m in milestones:
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
            milestones_out.append(
                {
                    "milestone_id": m.id,
                    "title": m.title,
                    "ok": len(errors) == 0,
                    "errors": errors,
                }
            )
        return {
            "command": "milestone-lint",
            "ok": total_errors == 0,
            "selected_milestone_id": milestone_id,
            "checked": len(milestones),
            "total_errors": total_errors,
            "milestones": milestones_out,
            "message": "",
        }

    @staticmethod
    def _print_lint_human(payload: dict) -> None:
        message = payload.get("message")
        milestones = payload.get("milestones", [])
        if message and not milestones:
            print(message)
            print("Lint Summary: 1 error(s) across 0 milestone(s) checked.")
            return
        for m in milestones:
            if m.get("ok"):
                print(f"[OK] Milestone {m['milestone_id']}: {m['title']}")
            else:
                print(f"[FAIL] Milestone {m['milestone_id']}: {m['title']}")
                for e in m.get("errors", []):
                    print(f"  - {e}")
        print(
            "Lint Summary: "
            f"{payload.get('total_errors', 0)} error(s) across {payload.get('checked', 0)} milestone(s) checked."
        )

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

    @staticmethod
    def milestone_preview(
        milestone_id: int | None = None,
        json_mode: bool = False,
        save_plan: bool = False,
        planner_mode: str | None = None,
        task_id: int | None = None,
    ):
        """Dry-run preview of milestone (or task) execution (no writes)."""
        planner, planner_policy, planner_err = resolve_planner(mode_override=planner_mode)
        if planner_err:
            if json_mode:
                print(
                    json.dumps(
                        serialize_preview_result(
                            {"ok": False, "message": planner_err, "errors": [planner_err]}
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(planner_err)
            return
        assert planner is not None
        enforcement = _review_enforcement_status(planner, planner_policy, save_plan=save_plan)
        if enforcement["requires_save_plan"] and not save_plan:
            msg = (
                "Policy requires reviewed-plan workflow for non-deterministic planners. "
                "Re-run with --save-plan and apply via milestone-apply-plan."
            )
            payload = {
                "ok": False,
                "message": msg,
                "errors": [msg],
                "planner_mode": planner.mode,
                "planner_metadata": planner.metadata(),
                "review_enforcement": enforcement,
            }
            if json_mode:
                print(json.dumps(serialize_preview_result(payload), indent=2, sort_keys=True))
            else:
                print(msg)
                print("Enforcement: reviewed-plan required for this planner.")
            return

        if task_id is not None and milestone_id is None:
            result = {
                "ok": False,
                "message": "--task requires a milestone id (positional).",
                "errors": ["--task requires a milestone id (positional)."],
            }
        elif save_plan and milestone_id is None:
            if task_id is not None:
                result = {
                    "ok": False,
                    "message": "--save-plan with --task requires an explicit milestone id.",
                }
            else:
                result = Executor.preview_next() if planner and planner.mode == "deterministic" else None
                if result is None:
                    result = {
                        "ok": False,
                        "message": "Save-plan without milestone ID requires deterministic planner.",
                    }
                if result.get("ok") and result.get("milestone_id") is not None:
                    result = Executor.save_reviewed_plan_for_milestone(
                        result["milestone_id"], planner=planner, review_enforcement=enforcement
                    )
        elif save_plan:
            assert milestone_id is not None
            if task_id is not None:
                result = Executor.save_reviewed_plan_for_task(
                    milestone_id,
                    task_id,
                    planner=planner,
                    review_enforcement=enforcement,
                )
            else:
                result = Executor.save_reviewed_plan_for_milestone(
                    milestone_id, planner=planner, review_enforcement=enforcement
                )
        else:
            if milestone_id is None:
                if task_id is not None:
                    result = {
                        "ok": False,
                        "message": "--task requires a milestone id (positional).",
                    }
                elif planner and planner.mode == "deterministic":
                    result = Executor.preview_next()
                else:
                    # For non-deterministic planners, require explicit milestone id
                    result = {
                        "ok": False,
                        "message": "Previewing next milestone with non-deterministic planner requires explicit milestone ID.",
                    }
            elif task_id is not None:
                result = Executor.preview_milestone(
                    milestone_id, planner=planner, task_id=task_id
                )
            else:
                result = Executor.preview_milestone(milestone_id, planner=planner)
        result["review_enforcement"] = enforcement
        if json_mode:
            print(json.dumps(serialize_preview_result(result), indent=2, sort_keys=True))
            return

        if not result.get("ok"):
            print(result.get("message", "Preview unavailable."))
            return

        if result.get("task_id") is not None:
            print(
                f"Preview Task: milestone {result['milestone_id']} task {result['task_id']}. "
                f"{result.get('title', '')}"
            )
        else:
            print(
                f"Preview Milestone: {result['milestone_id']}. {result.get('title', '')}"
            )
        pmeta = result.get("planner_metadata", {}) or {}
        planner_line = f"Planner: {result.get('planner_mode', 'deterministic')}"
        if pmeta.get("llm_client"):
            planner_line += f" ({pmeta.get('llm_client')}"
            if pmeta.get("llm_model"):
                planner_line += f":{pmeta.get('llm_model')}"
            planner_line += ")"
        print(planner_line)
        if result.get("plan_id"):
            print(f"Reviewed Plan ID: {result['plan_id']}")
        for w in result.get("warnings", []):
            print(f"Warning: {w}")
        enf = result.get("review_enforcement", {})
        if enf.get("required_for_plan"):
            print("Enforcement: reviewed-plan required by policy (compliant).")
        print(f"Artifact Summary: {result.get('artifact_summary', '')}")
        files = result.get("files_changed", [])
        print("Targeted Artifacts:")
        if files:
            for f in files:
                print(f"- {f}")
        else:
            print("- (none)")

        print("Planned Actions:")
        for idx, action in enumerate(result.get("actions_applied", []), start=1):
            a_type = action.get("type", "unknown")
            outcome = action.get("outcome", "unknown")
            path = action.get("path", "")
            path_part = f" path={path}" if path else ""
            print(f"{idx}. {a_type} [{outcome}]{path_part}")
            diff = action.get("diff")
            if isinstance(diff, str) and diff.strip():
                print("   diff:")
                for line in diff.splitlines():
                    print(f"     {line}")

    @staticmethod
    def milestone_apply_plan(
        plan_id: str,
        json_mode: bool = False,
        gate_validate: bool | None = None,
        gate_test_cmd: str | None = None,
        disable_gate_test_cmd: bool = False,
        gate_test_timeout_seconds: int | None = None,
        gate_test_output_max_chars: int | None = None,
    ) -> bool:
        base_policy, policy_err = load_reviewed_apply_policy()
        if policy_err:
            if json_mode:
                print(
                    json.dumps(
                        serialize_apply_plan_result(
                            {
                                "ok": False,
                                "plan_id": plan_id,
                                "message": policy_err,
                                "errors": [policy_err],
                            }
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(policy_err)
            return False

        resolved_policy: ReviewedApplyPolicy = merge_reviewed_apply_policy(
            base_policy,
            gate_validate=gate_validate,
            test_command=gate_test_cmd,
            disable_test_command=disable_gate_test_cmd,
            test_timeout_seconds=gate_test_timeout_seconds,
            test_output_max_chars=gate_test_output_max_chars,
        )
        if resolved_policy.test_timeout_seconds <= 0:
            msg = "Invalid gate configuration: test timeout must be a positive integer."
            if json_mode:
                print(
                    json.dumps(
                        serialize_apply_plan_result(
                            {"ok": False, "plan_id": plan_id, "message": msg, "errors": [msg]}
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(msg)
            return False
        if resolved_policy.test_output_max_chars <= 0:
            msg = "Invalid gate configuration: test output max chars must be a positive integer."
            if json_mode:
                print(
                    json.dumps(
                        serialize_apply_plan_result(
                            {"ok": False, "plan_id": plan_id, "message": msg, "errors": [msg]}
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
            else:
                print(msg)
            return False

        result = Executor.apply_reviewed_plan_with_gates(
            plan_id,
            run_validation_gate=resolved_policy.run_validation_gate,
            test_command=resolved_policy.test_command,
            test_timeout_seconds=resolved_policy.test_timeout_seconds,
            test_output_max_chars=resolved_policy.test_output_max_chars,
        )
        result["review_enforcement"] = result.get("review_enforcement", {})
        if json_mode:
            print(json.dumps(serialize_apply_plan_result(result), indent=2, sort_keys=True))
            return bool(result.get("ok"))
        if not result.get("ok"):
            print(result.get("message", "Failed to apply reviewed plan."))
            if result.get("gate_summary"):
                print(f"Gates: {result['gate_summary']}")
            return False
        print(f"Applied reviewed plan: {result.get('plan_id')}")
        print(f"Milestone: {result.get('milestone_id')}. {result.get('title', '')}")
        pmeta = result.get("planner_metadata", {}) or {}
        planner_line = f"Planner: {result.get('planner_mode', 'deterministic')}"
        if pmeta.get("llm_client"):
            planner_line += f" ({pmeta.get('llm_client')}"
            if pmeta.get("llm_model"):
                planner_line += f":{pmeta.get('llm_model')}"
            planner_line += ")"
        print(planner_line)
        for w in result.get("warnings", []):
            print(f"Warning: {w}")
        enf = result.get("review_enforcement", {})
        if enf.get("required_for_plan"):
            print("Enforcement: reviewed-plan policy satisfied.")
        print(f"Artifact Summary: {result.get('artifact_summary', '')}")
        if result.get("gate_summary"):
            print(f"Gates: {result.get('gate_summary')}")
        files = result.get("files_changed", [])
        if files:
            print("Changed Artifacts:")
            for f in files:
                print(f"- {f}")
        return True

    @staticmethod
    def milestone_synthesize(desired_count: int, json_mode: bool = False) -> bool:
        planner_policy, err = load_planner_policy()
        if err:
            payload = {"ok": False, "message": err}
            if json_mode:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(err)
            return False
        llm_client, llm_err = resolve_llm_client_from_policy(planner_policy)
        if llm_err:
            payload = {"ok": False, "message": llm_err}
            if json_mode:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(llm_err)
            return False
        assert llm_client is not None
        try:
            payload = synthesize_milestones(llm_client, desired_count=desired_count)
        except ValueError as exc:
            payload = {"ok": False, "message": str(exc)}
            if json_mode:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(str(exc))
            return False
        payload["ok"] = True
        if json_mode:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return True
        print(f"Synthesized milestone artifact: {payload.get('synthesis_id')}")
        print("Review proposed milestones:")
        print(payload.get("markdown_preview", "").rstrip())
        for w in payload.get("warnings", []):
            print(f"Warning: {w}")
        for w in payload.get("quality_warnings", []):
            print(f"Quality warning: {w}")
        print(f"Use: forge milestone-synthesis-accept {payload.get('synthesis_id')}")
        return True

    @staticmethod
    def milestone_synthesis_show(synthesis_id: str, json_mode: bool = False) -> bool:
        payload = load_synthesized_milestones(synthesis_id)
        if payload is None:
            msg = f"Synthesized milestone artifact '{synthesis_id}' not found."
            if json_mode:
                print(json.dumps({"ok": False, "message": msg}, indent=2, sort_keys=True))
            else:
                print(msg)
            return False
        payload["ok"] = True
        if json_mode:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return True
        print(f"Synthesized milestone artifact: {synthesis_id}")
        print(payload.get("markdown_preview", "").rstrip())
        for w in payload.get("warnings", []):
            print(f"Warning: {w}")
        for w in payload.get("quality_warnings", []):
            print(f"Quality warning: {w}")
        return True

    @staticmethod
    def milestone_synthesis_accept(synthesis_id: str, json_mode: bool = False) -> bool:
        payload = accept_synthesized_milestones(synthesis_id)
        if json_mode:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return bool(payload.get("ok"))
        if not payload.get("ok"):
            print(payload.get("message", "Failed to accept synthesized milestones."))
            return False
        print(payload.get("message", "Accepted synthesized milestones."))
        for w in payload.get("warnings", []):
            print(f"Warning: {w}")
        for w in payload.get("quality_warnings", []):
            print(f"Quality warning: {w}")
        return True

    @staticmethod
    def workflow_guarded(
        *,
        synthesize: bool,
        synthesis_count: int,
        accept_synthesized: bool,
        synthesis_id: str | None,
        milestone_id: int | None,
        planner_mode: str | None,
        apply_plan: bool,
        json_mode: bool,
        gate_validate: bool | None,
        gate_test_cmd: str | None,
        disable_gate_test_cmd: bool,
        gate_test_timeout_seconds: int | None,
        gate_test_output_max_chars: int | None,
    ) -> bool:
        stages: list[dict] = []
        latest_synthesis_id: str | None = None
        latest_plan_id: str | None = None

        if synthesize:
            planner_policy, err = load_planner_policy()
            if err:
                stage = {"stage": "synthesize", "ok": False, "message": err}
                stages.append(stage)
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=latest_synthesis_id, plan_id=latest_plan_id
                )
            llm_client, llm_err = resolve_llm_client_from_policy(planner_policy)
            if llm_err:
                stage = {"stage": "synthesize", "ok": False, "message": llm_err}
                stages.append(stage)
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=latest_synthesis_id, plan_id=latest_plan_id
                )
            assert llm_client is not None
            try:
                synth_payload = synthesize_milestones(llm_client, desired_count=synthesis_count)
                latest_synthesis_id = synth_payload.get("synthesis_id")
                stages.append(
                    {
                        "stage": "synthesize",
                        "ok": True,
                        "synthesis_id": latest_synthesis_id,
                        "warnings": synth_payload.get("warnings", []),
                        "quality_warnings": synth_payload.get("quality_warnings", []),
                        "message": "Synthesized reviewed milestone artifact.",
                    }
                )
            except ValueError as exc:
                stages.append({"stage": "synthesize", "ok": False, "message": str(exc)})
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=latest_synthesis_id, plan_id=latest_plan_id
                )

        chosen_synthesis_id = synthesis_id or latest_synthesis_id
        if accept_synthesized:
            if not chosen_synthesis_id:
                stages.append(
                    {
                        "stage": "accept_synthesized",
                        "ok": False,
                        "message": "No synthesis artifact ID available. Use --synthesis-id or --synthesize.",
                    }
                )
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=latest_synthesis_id, plan_id=latest_plan_id
                )
            accept_payload = accept_synthesized_milestones(chosen_synthesis_id)
            stages.append({"stage": "accept_synthesized", **accept_payload})
            if not accept_payload.get("ok"):
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
                )

        if milestone_id is not None:
            planner, planner_policy, planner_err = resolve_planner(mode_override=planner_mode)
            if planner_err:
                stages.append({"stage": "preview_save_plan", "ok": False, "message": planner_err})
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
                )
            assert planner is not None
            enforcement = _review_enforcement_status(planner, planner_policy, save_plan=True)
            preview = Executor.save_reviewed_plan_for_milestone(
                milestone_id, planner=planner, review_enforcement=enforcement
            )
            stages.append({"stage": "preview_save_plan", **preview})
            if not preview.get("ok"):
                return ForgeCLI._print_workflow_result(
                    stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
                )
            latest_plan_id = preview.get("plan_id")

            if apply_plan:
                if not latest_plan_id:
                    stages.append(
                        {
                            "stage": "apply_plan",
                            "ok": False,
                            "message": "No reviewed plan ID available from preview/save phase.",
                        }
                    )
                    return ForgeCLI._print_workflow_result(
                        stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
                    )
                base_policy, policy_err = load_reviewed_apply_policy()
                if policy_err:
                    stages.append({"stage": "apply_plan", "ok": False, "message": policy_err})
                    return ForgeCLI._print_workflow_result(
                        stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
                    )
                resolved_policy: ReviewedApplyPolicy = merge_reviewed_apply_policy(
                    base_policy,
                    gate_validate=gate_validate,
                    test_command=gate_test_cmd,
                    disable_test_command=disable_gate_test_cmd,
                    test_timeout_seconds=gate_test_timeout_seconds,
                    test_output_max_chars=gate_test_output_max_chars,
                )
                apply_res = Executor.apply_reviewed_plan_with_gates(
                    latest_plan_id,
                    run_validation_gate=resolved_policy.run_validation_gate,
                    test_command=resolved_policy.test_command,
                    test_timeout_seconds=resolved_policy.test_timeout_seconds,
                    test_output_max_chars=resolved_policy.test_output_max_chars,
                )
                stages.append({"stage": "apply_plan", **apply_res})
                if not apply_res.get("ok"):
                    return ForgeCLI._print_workflow_result(
                        stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
                    )

        return ForgeCLI._print_workflow_result(
            stages, json_mode=json_mode, synthesis_id=chosen_synthesis_id, plan_id=latest_plan_id
        )

    @staticmethod
    def vertical_slice(
        *,
        demo: bool,
        idea: str | None,
        fixed_vision: str | None = None,
        milestone_id: int = 1,
        planner_mode: str | None = None,
        gate_validate: bool | None = None,
        gate_test_cmd: str | None = None,
        disable_gate_test_cmd: bool = False,
        gate_test_timeout_seconds: int | None = None,
        gate_test_output_max_chars: int | None = None,
        json_mode: bool = False,
        verbose: bool = False,
    ) -> bool:
        """Idea / vision file → docs → reviewed plan → apply → validation gates (see `forge vertical-slice`)."""
        run_id = uuid.uuid4().hex[:12]
        run_dir = Paths.forge_run_dir(run_id)
        events_path = run_dir / "events.jsonl"
        collector = EventListCollector()
        handlers: list = [JsonlRunLogHandler(events_path), collector]
        if not json_mode:
            handlers.insert(0, CliProgressHandler(verbose=verbose))
        bus = RunEventBus(run_id, handlers)
        if demo:
            input_mode = "demo"
        elif fixed_vision is not None:
            input_mode = "vision_file"
        else:
            input_mode = "idea"
        write_run_meta(
            run_dir,
            {
                "run_id": run_id,
                "command": "vertical-slice",
                "demo": demo,
                "input_mode": input_mode,
                "idea_provided": idea is not None,
                "fixed_vision_provided": fixed_vision is not None,
                "milestone_id": milestone_id,
                "verbose": verbose,
                "json_mode": json_mode,
            },
        )
        payload = run_vertical_slice(
            demo=demo,
            idea=idea,
            fixed_vision=fixed_vision,
            milestone_id=milestone_id,
            planner_mode=planner_mode,
            gate_validate=gate_validate,
            gate_test_cmd=gate_test_cmd,
            disable_gate_test_cmd=disable_gate_test_cmd,
            gate_test_timeout_seconds=gate_test_timeout_seconds,
            gate_test_output_max_chars=gate_test_output_max_chars,
            event_bus=bus,
        )
        payload["run_id"] = run_id
        payload["run_log_dir"] = str(run_dir)
        payload["events_path"] = str(events_path)
        payload["events"] = collector.events
        if json_mode:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return bool(payload.get("ok"))
        print(f"Run log: {events_path}")
        return bool(payload.get("ok"))

    @staticmethod
    def _print_workflow_result(
        stages: list[dict], *, json_mode: bool, synthesis_id: str | None, plan_id: str | None
    ) -> bool:
        ok = all(bool(s.get("ok")) for s in stages) if stages else True
        payload = {
            "command": "workflow-guarded",
            "ok": ok,
            "synthesis_id": synthesis_id,
            "plan_id": plan_id,
            "stages": stages,
        }
        if json_mode:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return ok
        print("Guarded workflow:")
        for s in stages:
            status = "OK" if s.get("ok") else "FAIL"
            print(f"- [{status}] {s.get('stage')}")
            msg = s.get("message")
            if msg:
                print(f"  {msg}")
            if s.get("synthesis_id"):
                print(f"  synthesis_id={s.get('synthesis_id')}")
            if s.get("plan_id"):
                print(f"  plan_id={s.get('plan_id')}")
        return ok

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
    milestone_preview_parser = subparsers.add_parser(
        "milestone-preview", help="Preview milestone execution without writing files"
    )
    milestone_preview_parser.add_argument(
        "id", nargs="?", type=int, help="Optional milestone ID to preview"
    )
    milestone_preview_parser.add_argument(
        "--planner",
        choices=["deterministic", "llm"],
        help="Override planner mode for this preview/save-plan command",
    )
    milestone_preview_parser.add_argument(
        "--save-plan", action="store_true", help="Persist a reviewed plan artifact for later apply"
    )
    milestone_preview_parser.add_argument(
        "--task",
        type=int,
        default=None,
        metavar="ID",
        help="Build preview/saved plan from this task id under .system/tasks/ (requires milestone id)",
    )
    milestone_preview_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    task_expand_parser = subparsers.add_parser(
        "task-expand",
        help="Create or refresh task breakdown for a milestone (default: one compatibility task)",
    )
    task_expand_parser.add_argument(
        "--milestone",
        type=int,
        required=True,
        metavar="ID",
        help="Milestone id",
    )
    task_expand_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing task file from current milestone Forge Actions",
    )
    task_expand_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    task_list_parser = subparsers.add_parser(
        "task-list", help="List tasks for a milestone"
    )
    task_list_parser.add_argument(
        "--milestone",
        type=int,
        required=True,
        metavar="ID",
        help="Milestone id",
    )
    task_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    task_show_parser = subparsers.add_parser(
        "task-show", help="Show one task under a milestone"
    )
    task_show_parser.add_argument(
        "--milestone",
        type=int,
        required=True,
        metavar="ID",
        help="Milestone id",
    )
    task_show_parser.add_argument(
        "--task",
        type=int,
        required=True,
        metavar="ID",
        help="Task id",
    )
    task_show_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    milestone_apply_plan_parser = subparsers.add_parser(
        "milestone-apply-plan", help="Apply a previously reviewed milestone plan"
    )
    milestone_apply_plan_parser.add_argument("plan_id", type=str, help="Reviewed plan ID")
    gate_validate_group = milestone_apply_plan_parser.add_mutually_exclusive_group()
    gate_validate_group.add_argument(
        "--gate-validate",
        action="store_true",
        help="Run milestone validation gate after apply",
    )
    gate_validate_group.add_argument(
        "--no-gate-validate",
        action="store_true",
        help="Disable milestone validation gate for this apply",
    )
    milestone_apply_plan_parser.add_argument(
        "--gate-test-cmd",
        type=str,
        help="Run explicit repository test command gate after apply",
    )
    milestone_apply_plan_parser.add_argument(
        "--no-gate-test-cmd",
        action="store_true",
        help="Disable configured repository test command gate for this apply",
    )
    milestone_apply_plan_parser.add_argument(
        "--gate-test-timeout-seconds",
        type=int,
        help="Override timeout seconds for repository test command gate",
    )
    milestone_apply_plan_parser.add_argument(
        "--gate-test-output-max-chars",
        type=int,
        help="Override captured output size for repository test command gate",
    )
    milestone_apply_plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    milestone_lint_parser = subparsers.add_parser(
        "milestone-lint", help="Lint milestone execution definitions"
    )
    milestone_lint_parser.add_argument(
        "id", nargs="?", type=int, help="Optional milestone ID to lint"
    )
    milestone_lint_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    subparsers.add_parser("execute-next", help="Execute the next eligible milestone")
    synthesis_parser = subparsers.add_parser(
        "milestone-synthesize", help="Generate reviewed milestone proposals from repo context"
    )
    synthesis_parser.add_argument(
        "--count", type=int, default=3, help="Desired maximum number of synthesized milestones"
    )
    synthesis_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    milestone_generate_parser = subparsers.add_parser(
        "milestone-generate",
        help="Alias for milestone-synthesize (LLM milestone proposals)",
    )
    milestone_generate_parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Desired maximum number of synthesized milestones",
    )
    milestone_generate_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    synthesis_show_parser = subparsers.add_parser(
        "milestone-synthesis-show", help="Show synthesized milestone artifact"
    )
    synthesis_show_parser.add_argument("synthesis_id", type=str, help="Synthesis artifact ID")
    synthesis_show_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    synthesis_accept_parser = subparsers.add_parser(
        "milestone-synthesis-accept",
        help="Accept reviewed synthesized milestones into docs/milestones.md",
    )
    synthesis_accept_parser.add_argument("synthesis_id", type=str, help="Synthesis artifact ID")
    synthesis_accept_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )
    workflow_parser = subparsers.add_parser(
        "workflow-guarded", help="Run explicit guarded synthesis->plan->apply workflow"
    )
    workflow_parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Run milestone synthesis phase first",
    )
    workflow_parser.add_argument(
        "--synthesis-count",
        type=int,
        default=3,
        help="Desired maximum synthesized milestones when --synthesize is used",
    )
    workflow_parser.add_argument(
        "--accept-synthesized",
        action="store_true",
        help="Accept synthesized milestone artifact into docs/milestones.md",
    )
    workflow_parser.add_argument(
        "--synthesis-id",
        type=str,
        help="Existing synthesis artifact ID to accept",
    )
    workflow_parser.add_argument(
        "--milestone-id",
        type=int,
        help="Milestone ID to preview/save plan for",
    )
    workflow_parser.add_argument(
        "--planner",
        choices=["deterministic", "llm"],
        help="Override planner mode for preview/save phase",
    )
    workflow_parser.add_argument(
        "--apply-plan",
        action="store_true",
        help="Apply reviewed plan after preview/save phase",
    )
    wf_gate_validate_group = workflow_parser.add_mutually_exclusive_group()
    wf_gate_validate_group.add_argument(
        "--gate-validate",
        action="store_true",
        help="Run validation gate when --apply-plan is used",
    )
    wf_gate_validate_group.add_argument(
        "--no-gate-validate",
        action="store_true",
        help="Disable validation gate when --apply-plan is used",
    )
    workflow_parser.add_argument(
        "--gate-test-cmd",
        type=str,
        help="Run repository test command gate when --apply-plan is used",
    )
    workflow_parser.add_argument(
        "--no-gate-test-cmd",
        action="store_true",
        help="Disable configured repository test command gate when --apply-plan is used",
    )
    workflow_parser.add_argument(
        "--gate-test-timeout-seconds",
        type=int,
        help="Override test gate timeout when --apply-plan is used",
    )
    workflow_parser.add_argument(
        "--gate-test-output-max-chars",
        type=int,
        help="Override test gate output size when --apply-plan is used",
    )
    workflow_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )

    vertical_slice_parser = subparsers.add_parser(
        "vertical-slice",
        help="End-to-end: write vision/specs/milestones, save reviewed plan, apply, run gates",
    )
    vertical_slice_parser.add_argument(
        "--demo",
        action="store_true",
        help="Use built-in todo CLI example (no LLM for docs)",
    )
    vertical_slice_parser.add_argument(
        "--idea",
        type=str,
        default=None,
        metavar="TEXT",
        help="Generate vision + docs from a short idea via LLM (highest precedence vs file vision)",
    )
    vertical_slice_parser.add_argument(
        "--vision-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Load vision from this file; LLM generates requirements, architecture, milestones only",
    )
    vertical_slice_parser.add_argument(
        "--from-vision",
        action="store_true",
        help="Load vision from docs/vision.txt (same LLM behavior as --vision-file)",
    )
    vertical_slice_parser.add_argument(
        "--milestone-id",
        type=int,
        default=1,
        help="Milestone to plan/apply (default: 1)",
    )
    vertical_slice_parser.add_argument(
        "--planner",
        choices=["deterministic", "llm"],
        help="Planner for execution plan (default: from forge-policy.json)",
    )
    vs_gate_validate_group = vertical_slice_parser.add_mutually_exclusive_group()
    vs_gate_validate_group.add_argument(
        "--gate-validate",
        action="store_true",
        help="Run Forge Validation rules after apply (default: on)",
    )
    vs_gate_validate_group.add_argument(
        "--no-gate-validate",
        action="store_true",
        help="Skip Forge Validation rules after apply",
    )
    vertical_slice_parser.add_argument(
        "--gate-test-cmd",
        type=str,
        help="Shell command gate after apply (demo default: python examples/todo_cli.py)",
    )
    vertical_slice_parser.add_argument(
        "--no-gate-test-cmd",
        action="store_true",
        help="Disable repository test command gate",
    )
    vertical_slice_parser.add_argument(
        "--gate-test-timeout-seconds",
        type=int,
        help="Timeout for test command gate",
    )
    vertical_slice_parser.add_argument(
        "--gate-test-output-max-chars",
        type=int,
        help="Max captured chars for test command gate",
    )
    vertical_slice_parser.add_argument(
        "--verbose",
        action="store_true",
        help="More detailed progress (still event-driven; not debug logging)",
    )
    vertical_slice_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON output"
    )

    args = parser.parse_args()

    if args.command not in {"init", "status", None}:
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
    elif args.command == "milestone-preview":
        ForgeCLI.milestone_preview(
            args.id,
            json_mode=args.json,
            save_plan=args.save_plan,
            planner_mode=args.planner,
            task_id=args.task,
        )
    elif args.command == "task-expand":
        return (
            0
            if ForgeCLI.task_expand(
                args.milestone, force=args.force, json_mode=args.json
            )
            else 1
        )
    elif args.command == "task-list":
        ForgeCLI.task_list(args.milestone, json_mode=args.json)
    elif args.command == "task-show":
        ForgeCLI.task_show(args.milestone, args.task, json_mode=args.json)
    elif args.command == "milestone-apply-plan":
        gate_validate_override = (
            True
            if args.gate_validate
            else False
            if args.no_gate_validate
            else None
        )
        return 0 if ForgeCLI.milestone_apply_plan(
            args.plan_id,
            json_mode=args.json,
            gate_validate=gate_validate_override,
            gate_test_cmd=args.gate_test_cmd,
            disable_gate_test_cmd=args.no_gate_test_cmd,
            gate_test_timeout_seconds=args.gate_test_timeout_seconds,
            gate_test_output_max_chars=args.gate_test_output_max_chars,
        ) else 1
    elif args.command == "milestone-lint":
        return 0 if ForgeCLI.milestone_lint(args.id, json_mode=args.json) else 1
    elif args.command == "execute-next":
        ForgeCLI.execute_next()
    elif args.command == "milestone-synthesize":
        return 0 if ForgeCLI.milestone_synthesize(args.count, json_mode=args.json) else 1
    elif args.command == "milestone-generate":
        return 0 if ForgeCLI.milestone_synthesize(args.count, json_mode=args.json) else 1
    elif args.command == "milestone-synthesis-show":
        return 0 if ForgeCLI.milestone_synthesis_show(args.synthesis_id, json_mode=args.json) else 1
    elif args.command == "milestone-synthesis-accept":
        return 0 if ForgeCLI.milestone_synthesis_accept(args.synthesis_id, json_mode=args.json) else 1
    elif args.command == "workflow-guarded":
        wf_gate_validate_override = (
            True if args.gate_validate else False if args.no_gate_validate else None
        )
        return 0 if ForgeCLI.workflow_guarded(
            synthesize=args.synthesize,
            synthesis_count=args.synthesis_count,
            accept_synthesized=args.accept_synthesized,
            synthesis_id=args.synthesis_id,
            milestone_id=args.milestone_id,
            planner_mode=args.planner,
            apply_plan=args.apply_plan,
            json_mode=args.json,
            gate_validate=wf_gate_validate_override,
            gate_test_cmd=args.gate_test_cmd,
            disable_gate_test_cmd=args.no_gate_test_cmd,
            gate_test_timeout_seconds=args.gate_test_timeout_seconds,
            gate_test_output_max_chars=args.gate_test_output_max_chars,
        ) else 1
    elif args.command == "vertical-slice":
        vs_gate_validate_override = (
            True
            if args.gate_validate
            else False
            if args.no_gate_validate
            else None
        )
        idea_raw = (args.idea or "").strip()
        has_idea = bool(idea_raw)
        has_vision_file = bool(args.vision_file)
        has_from_vision = bool(args.from_vision)
        if args.demo:
            if has_idea or has_vision_file or has_from_vision:
                print(
                    "vertical-slice: do not combine --demo with --idea, --vision-file, or --from-vision."
                )
                return 1
            idea_text = None
            fixed_vision_text = None
        else:
            non_demo_modes = sum(
                1 for flag in (has_idea, has_vision_file, has_from_vision) if flag
            )
            if non_demo_modes == 0:
                print(
                    "vertical-slice: provide one of --demo, --idea, --vision-file PATH, or --from-vision."
                )
                return 1
            idea_text = None
            fixed_vision_text = None
            if has_idea:
                idea_text = idea_raw
            elif has_vision_file:
                vpath = resolve_vision_file_path(args.vision_file, base_dir=Paths.BASE_DIR)
                try:
                    fixed_vision_text = read_vision_file_text(vpath)
                except FileNotFoundError as exc:
                    print(f"vertical-slice: {exc}")
                    return 1
                except (OSError, ValueError) as exc:
                    print(f"vertical-slice: {exc}")
                    return 1
            elif has_from_vision:
                vpath = Paths.VISION_FILE
                try:
                    fixed_vision_text = read_vision_file_text(vpath)
                except FileNotFoundError as exc:
                    print(f"vertical-slice: {exc}")
                    return 1
                except (OSError, ValueError) as exc:
                    print(f"vertical-slice: {exc}")
                    return 1
        return (
            0
            if ForgeCLI.vertical_slice(
                demo=bool(args.demo),
                idea=idea_text,
                fixed_vision=fixed_vision_text,
                milestone_id=args.milestone_id,
                planner_mode=args.planner,
                gate_validate=vs_gate_validate_override,
                gate_test_cmd=args.gate_test_cmd,
                disable_gate_test_cmd=args.no_gate_test_cmd,
                gate_test_timeout_seconds=args.gate_test_timeout_seconds,
                gate_test_output_max_chars=args.gate_test_output_max_chars,
                json_mode=args.json,
                verbose=bool(getattr(args, "verbose", False)),
            )
            else 1
        )
    else:
        parser.print_help()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())