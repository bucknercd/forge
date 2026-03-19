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
        return state.get(str(milestone_id), {"status": "not_started", "attempts": 0})