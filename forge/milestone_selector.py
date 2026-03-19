from forge.design_manager import DesignManager
from forge.paths import Paths
from forge.milestone_state import MilestoneStateRepository


VALID_STATUSES = {
    "not_started",
    "in_progress",
    "retry_pending",
    "completed",
    "failed",
}

SELECTABLE_STATUSES = {"not_started", "retry_pending"}


class MilestoneSelector:
    def __init__(self, milestone_service, state_repository: MilestoneStateRepository):
        self.milestone_service = milestone_service
        self.state_repository = state_repository

    def get_next_milestone(self):
        content = DesignManager.load_document(Paths.MILESTONES_FILE)
        milestones = self.milestone_service.parse_milestones(content)

        for milestone in milestones:
            milestone_id = str(milestone.id)
            milestone_state = self.state_repository.get(milestone_id)
            status = milestone_state["status"]

            if status not in VALID_STATUSES:
                raise ValueError(
                    f"Unknown status '{status}' for milestone {milestone_id}"
                )

            if status in SELECTABLE_STATUSES:
                return milestone

        return None