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
    Paths.RUN_HISTORY_FILE = Paths.SYSTEM_DIR / "run_history.log"
    Paths.DOCS_DIR = tmp_path / "docs"
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.DECISIONS_FILE = Paths.DOCS_DIR / "decisions.md"
    Paths.DECISIONS_FILE.write_text("# Decisions\n", encoding="utf-8")

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

    # Validate decision entry append
    decisions_content = Paths.DECISIONS_FILE.read_text(encoding="utf-8")
    assert "Milestone 1 completed" in decisions_content
    assert "Execution outcome: completed" in decisions_content

    # Validate structured run attempt entry
    history_lines = Paths.RUN_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    structured_entries = [json.loads(line) for line in history_lines if "milestone_id" in json.loads(line)]
    assert structured_entries
    assert structured_entries[-1]["milestone_id"] == 1
    assert structured_entries[-1]["status"] == "success"

def test_execute_milestone_failure(tmp_path):
    # Setup milestone file with missing scope/validation (objective present)
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("""
# Milestones

## Milestone 1: First Task
- **Objective**: Exists
- **Scope**: 
- **Validation**: 
""")

    # Setup system directory
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()
    Paths.RUN_HISTORY_FILE = Paths.SYSTEM_DIR / "run_history.log"
    Paths.DOCS_DIR = tmp_path / "docs"
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.DECISIONS_FILE = Paths.DOCS_DIR / "decisions.md"
    Paths.DECISIONS_FILE.write_text("# Decisions\n", encoding="utf-8")

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

    # Failed execution should not append misleading success decision.
    decisions_content = Paths.DECISIONS_FILE.read_text(encoding="utf-8")
    assert "Milestone 1 completed" not in decisions_content

    history_lines = Paths.RUN_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    structured_entries = [json.loads(line) for line in history_lines if "milestone_id" in json.loads(line)]
    assert structured_entries
    assert structured_entries[-1]["milestone_id"] == 1
    assert structured_entries[-1]["status"] == "failure"
    assert "error_message" in structured_entries[-1]