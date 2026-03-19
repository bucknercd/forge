import pytest
from forge.executor import Executor
from forge.paths import Paths
import json

def test_retry_milestone(tmp_path):
    # Setup milestone file
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("""
# Milestones

## Milestone 1: Retry Task
- **Objective**: Test retry logic
- **Scope**: Ensure retries work
- **Validation**: Verify retry behavior
""")

    # Setup system directory
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    # Simulate a failed milestone
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state = {
        "1": {
            "status": "retry_pending",
            "attempts": 1
        }
    }
    with state_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=4)

    # Retry the milestone
    Executor.execute_milestone(1)

    # Validate milestone state
    with state_file.open("r", encoding="utf-8") as file:
        updated_state = json.load(file)
    assert updated_state["1"]["status"] == "completed"
    assert updated_state["1"]["attempts"] == 2