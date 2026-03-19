from forge.paths import Paths
import json
from forge.design_manager import MilestoneService

class Validator:
    @staticmethod
    def validate_milestone(milestone_id: int) -> bool:
        """Validate the milestone execution results."""
        plan_file = Paths.SYSTEM_DIR / "plans" / f"milestone_{milestone_id}.md"
        result_file = Paths.SYSTEM_DIR / "results" / f"milestone_{milestone_id}.json"

        # Check if plan and result files exist
        if not plan_file.exists() or not result_file.exists():
            return False

        # Check if result file contains required fields
        with result_file.open("r", encoding="utf-8") as file:
            result = json.load(file)

        required_fields = ["id", "title", "summary"]
        if not all(field in result for field in required_fields):
            return False

        # Load the milestone and validate its fields
        milestone = MilestoneService.get_milestone(milestone_id)
        if not milestone:
            return False

        if not milestone.objective.strip() or not milestone.scope.strip() or not milestone.validation.strip():
            return False

        return True