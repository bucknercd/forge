import pytest
from forge.executor import Executor
from forge.paths import Paths
from forge.validator import Validator
import json

from tests.forge_test_project import configure_project, forge_block


def test_execute_milestone_success(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: First Task
- **Objective**: Complete the first task
- **Scope**: Initial setup
- **Validation**: Verify basics
{forge_block("FORGE_M1_OK")}
""",
    )

    Executor.execute_milestone(1)

    result_file = Paths.SYSTEM_DIR / "results" / "milestone_1.json"
    assert result_file.exists()
    with result_file.open("r", encoding="utf-8") as file:
        result = json.load(file)
    assert result["id"] == 1
    assert "Milestone 1: First Task" in result["title"]
    assert "FORGE_M1_OK" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")
    assert "- **Forge Status**: completed" in Paths.MILESTONES_FILE.read_text(encoding="utf-8")

    assert Validator.validate_milestone_with_report(1)[0] is True

    # Validate milestone state
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "completed"
    assert state["1"]["attempts"] == 1

    # Validate decision entry append (default completion decision)
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
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: First Task
- **Objective**: Exists
- **Scope**: Has scope text so milestone parses; still no Forge Actions below.
- **Validation**: Validation text present.
""",
    )

    Executor.execute_milestone(1)

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
