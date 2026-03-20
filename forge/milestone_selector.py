from forge.design_manager import DesignManager
from forge.paths import Paths
from forge.milestone_state import MilestoneStateRepository


VALID_STATUSES = {
    "not_started",
    "in_progress",
    "retry_pending",
    "completed",
    "failed",
    "blocked",
}

SELECTABLE_STATUSES = {"not_started", "retry_pending"}


class MilestoneSelector:
    def __init__(self, milestone_service, state_repository: MilestoneStateRepository):
        self.milestone_service = milestone_service
        self.state_repository = state_repository

    def _deps_completed(self, milestone):
        for dep_id in getattr(milestone, "depends_on", []):
            dep_state = self.state_repository.get(dep_id)
            if dep_state["status"] != "completed":
                return False
        return True

    def _derive_effective_status(self, milestone, milestone_state: dict) -> str:
        """
        Effective status is derived from runtime status + dependency completion.
        `blocked` is effective-only and is not intended to be a prerequisite for
        parsing/execution state storage.
        """
        runtime_status = milestone_state["status"]
        if runtime_status == "completed":
            return "completed"

        if not self._deps_completed(milestone):
            return "blocked"

        return runtime_status

    def get_next_milestone_with_report(self):
        content = DesignManager.load_document(Paths.MILESTONES_FILE)
        milestones = self.milestone_service.parse_milestones(content)

        derived = []
        for milestone in milestones:
            milestone_id = str(milestone.id)
            milestone_state = self.state_repository.get(milestone_id)
            status = milestone_state["status"]

            if status not in VALID_STATUSES:
                raise ValueError(
                    f"Unknown status '{status}' for milestone {milestone_id}"
                )

            effective_status = self._derive_effective_status(milestone, milestone_state)
            derived.append((milestone, effective_status, milestone_state))

        # Prefer retry_pending when eligible.
        for milestone, effective_status, _ in derived:
            if effective_status == "retry_pending":
                return milestone, {"kind": "selected"}

        for milestone, effective_status, _ in derived:
            if effective_status == "not_started":
                return milestone, {"kind": "selected"}

        all_complete = all(m_state["status"] == "completed" for _, _, m_state in derived)
        in_progress = any(effective_status == "in_progress" for _, effective_status, _ in derived)
        if all_complete:
            return None, {"kind": "all_complete"}
        if in_progress:
            return None, {"kind": "in_progress"}

        # Anything not runnable now is treated as blocked by unmet prerequisites
        # (including dependent work blocked behind failed/unmet deps).
        return None, {"kind": "blocked"}

    def get_next_milestone(self):
        milestone, _report = self.get_next_milestone_with_report()
        return milestone