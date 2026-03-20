import json
from pathlib import Path


def normalize_milestone_state_value(value):
    """
    Normalize milestone state JSON value into:
      { "status": <str>, "attempts": <int> }

    Supports legacy values where the status was stored as a string.
    """
    if value is None:
        return {"status": "not_started", "attempts": 0}

    if isinstance(value, str):
        return {"status": value, "attempts": 0}

    if isinstance(value, dict):
        status = value.get("status", "not_started")
        attempts = value.get("attempts", 0)
        try:
            attempts_int = int(attempts)
        except (TypeError, ValueError):
            attempts_int = 0
        return {"status": status, "attempts": attempts_int}

    return {"status": "not_started", "attempts": 0}


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
        return normalize_milestone_state_value(value)