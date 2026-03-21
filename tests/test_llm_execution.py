"""
Legacy name: execution no longer depends on an LLM client.
These tests cover deterministic artifact application + validation.
"""

import json

from forge.executor import Executor
from forge.paths import Paths

from tests.forge_test_project import configure_project, forge_block


def test_execute_milestone_records_structured_result_and_summary(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Artifact task
- **Objective**: Do work
- **Scope**: Some scope
- **Validation**: Validate artifact changes
{forge_block("FORGE_SUMMARY_OK")}
""",
    )

    Executor.execute_milestone(1)

    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "completed"
    assert state["1"]["attempts"] == 1

    result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    assert result["summary"]
    assert "requirements" in result["summary"].lower() or "FORGE_SUMMARY_OK" in result["summary"]
    assert result["execution_plan"]["milestone_id"] == 1
    assert result["files_changed"]


def test_execute_milestone_handles_empty_plan_rejected_by_validator(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: No actions
- **Objective**: Do work
- **Scope**: Some scope
- **Validation**: Validate
""",
    )

    Executor.execute_milestone(1)
    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "retry_pending"
