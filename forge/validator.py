from forge.paths import Paths
import json
from forge.design_manager import MilestoneService
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.validation_rules import validate_all_rules


class Validator:
    @staticmethod
    def validate_milestone_with_report(milestone_id: int) -> tuple[bool, str]:
        """Validate artifact-driven execution results and return a reason on failure."""
        result_file = Paths.SYSTEM_DIR / "results" / f"milestone_{milestone_id}.json"

        if not result_file.exists():
            return False, (
                f"Milestone {milestone_id} has no execution result file at "
                f"{result_file}. Run execution first."
            )

        with result_file.open("r", encoding="utf-8") as file:
            result = json.load(file)

        apply_errors = result.get("apply_errors") or []
        if apply_errors:
            return False, (
                f"Milestone {milestone_id} apply step failed: {'; '.join(apply_errors)}"
            )

        required_fields = [
            "id",
            "title",
            "summary",
            "files_changed",
            "actions_applied",
            "execution_plan",
        ]
        missing = [field for field in required_fields if field not in result]
        if missing:
            return False, (
                f"Milestone {milestone_id} result missing required fields: "
                f"{', '.join(missing)}"
            )

        if not str(result.get("summary", "")).strip():
            return False, f"Milestone {milestone_id} result summary is empty."

        milestone = MilestoneService.get_milestone(milestone_id)
        if not milestone:
            return False, f"Milestone {milestone_id} not found during validation."

        if (
            not milestone.objective.strip()
            or not milestone.scope.strip()
            or not milestone.validation.strip()
        ):
            return False, (
                f"Milestone {milestone_id} objective/scope/validation fields "
                "must be non-empty."
            )

        if not milestone.forge_actions:
            return False, (
                f"Milestone {milestone_id} has no Forge Actions. "
                "Add a '- **Forge Actions**:' block with deterministic actions."
            )

        if milestone.forge_actions and not milestone.forge_validation:
            return False, (
                f"Milestone {milestone_id} has Forge Actions but no Forge Validation rules."
            )

        try:
            rules = ExecutionPlanBuilder.parse_validation_rules(milestone)
        except ValueError as exc:
            return False, f"Invalid Forge Validation for milestone {milestone_id}: {exc}"

        ok, reason = validate_all_rules(rules, Paths)
        if not ok:
            return False, reason

        return True, ""

    @staticmethod
    def validate_milestone(milestone_id: int) -> bool:
        ok, _reason = Validator.validate_milestone_with_report(milestone_id)
        return ok
