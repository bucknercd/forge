import json
from pathlib import Path
from forge.milestone_state import MilestoneStateRepository

class MilestoneSelector:
    def __init__(self, milestone_service, state_repository: MilestoneStateRepository):
        self.milestone_service = milestone_service
        self.state_repository = state_repository

    def get_next_milestone(self):
        milestones = self.milestone_service.parse_milestones()

        for milestone in milestones:
            milestone_id = str(milestone['id'])
            milestone_state = self.state_repository.get(milestone_id)

            if milestone_state['status'] not in {"not_started", "in_progress", "retry_pending", "completed", "failed"}:
                raise ValueError(f"Unknown status '{milestone_state['status']}' for milestone {milestone_id}")

            if milestone_state['status'] in {"not_started", "retry_pending"}:
                return {**milestone, "status": milestone_state['status']}

        return None