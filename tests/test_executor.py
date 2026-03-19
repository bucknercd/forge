import pytest
from forge.executor import Executor
from forge.paths import Paths
from forge.validator import Validator
import json

def test_execute_milestone_success(tmp_path):
    # Setup milestone file
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("""
# Milestones

## Milestone 1: First Task
- **Objective**: Complete the first task
- **Scope**: Initial setup
- **Validation**: Verify basics
""")

    # Setup system directory
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    # Execute the milestone
    Executor.execute_milestone(1)

    # Validate plan file creation
    plan_file = Paths.SYSTEM_DIR / "plans" / "milestone_1.md"
    assert plan_file.exists()

    # Validate result file creation
    result_file = Paths.SYSTEM_DIR / "results" / "milestone_1.json"
    assert result_file.exists()
    with result_file.open("r", encoding="utf-8") as file:
        result = json.load(file)
    assert result["id"] == 1
    assert result["title"] == "Milestone 1: First Task"
    assert result["summary"] == "Execution completed successfully."

    # Validate milestone state
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "completed"
    assert state["1"]["attempts"] == 1

def test_execute_milestone_failure(tmp_path):
    # Setup milestone file with missing required fields
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("""
# Milestones

## Milestone 1: First Task
- **Objective**: 
- **Scope**: 
- **Validation**: 
""")

    # Setup system directory
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    # Execute the milestone
    Executor.execute_milestone(1)

    # Validate plan file creation
    plan_file = Paths.SYSTEM_DIR / "plans" / "milestone_1.md"
    assert plan_file.exists()

    # Validate milestone state
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "retry_pending"
    assert state["1"]["attempts"] == 1