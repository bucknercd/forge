from forge.paths import Paths
import json
from forge.design_manager import MilestoneService

class Validator:
    @staticmethod
    def validate_milestone_with_report(milestone_id: int) -> tuple[bool, str]:
        """Validate the milestone execution results and return a reason on failure."""
        plan_file = Paths.SYSTEM_DIR / "plans" / f"milestone_{milestone_id}.md"
        result_file = Paths.SYSTEM_DIR / "results" / f"milestone_{milestone_id}.json"

        # Check if plan and result files exist
        if not plan_file.exists() or not result_file.exists():
            return False, "Missing plan file or result file."

        # Check if result file contains required fields
        with result_file.open("r", encoding="utf-8") as file:
            result = json.load(file)

        required_fields = ["id", "title", "summary"]
        missing = [field for field in required_fields if field not in result]
        if missing:
            return False, f"Result missing required fields: {', '.join(missing)}"

        if not str(result.get("summary", "")).strip():
            return False, "Result summary is empty."

        # Load the milestone and validate its fields
        milestone = MilestoneService.get_milestone(milestone_id)
        if not milestone:
            return False, "Milestone not found during validation."

        if (
            not milestone.objective.strip()
            or not milestone.scope.strip()
            or not milestone.validation.strip()
        ):
            return False, (
                "Milestone objective/scope/validation fields must be non-empty."
            )

        return True, ""

    @staticmethod
    def validate_milestone(milestone_id: int) -> bool:
        ok, _reason = Validator.validate_milestone_with_report(milestone_id)
        return ok