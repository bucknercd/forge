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
        FileRepository.append_to_file(Paths.DECISIONS_FILE, entry)