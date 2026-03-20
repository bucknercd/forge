# forge/decision_tracker.py

from datetime import datetime
from forge.paths import Paths
from forge.repository import FileRepository
from forge.models import Decision

class DecisionTracker:
    @staticmethod
    def append_decision(decision: Decision) -> None:
        entry = (
            f"## {decision.title}\n"
            f"- **Context**: {decision.context}\n"
            f"- **Decision**: {decision.decision}\n"
            f"- **Rationale**: {decision.rationale}\n"
            f"- **Timestamp**: {decision.timestamp.isoformat()}\n"
        )
        Paths.DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        FileRepository.append_to_file(Paths.DECISIONS_FILE, entry)

    @staticmethod
    def append_milestone_success_decision(milestone_id: int, milestone_title: str, summary: str) -> None:
        """
        Record a structured append-only decision for successful milestone execution.
        """
        decision = Decision(
            title=f"Milestone {milestone_id} completed",
            context=f"Milestone {milestone_id}: {milestone_title}",
            decision="Execution outcome: completed",
            rationale=(summary or "Execution completed successfully.").strip(),
            timestamp=datetime.now(),
        )
        DecisionTracker.append_decision(decision)