import json
from pathlib import Path

class MilestoneStateRepository:
    def __init__(self, state_file: Path):
        self.state_file = state_file

    def load(self):
        if not self.state_file.exists():
            return {}
        with self.state_file.open("r", encoding="utf-8") as file:
            return json.load(file)

    def get(self, milestone_id):
        state = self.load()
        value = state.get(str(milestone_id))

        if isinstance(value, str):
            # Backward compatibility for string format
            return {"status": value, "attempts": 0}
        elif isinstance(value, dict):
            # Return dict format unchanged
            return value
        else:
            # Default for missing entries
            return {"status": "not_started", "attempts": 0}