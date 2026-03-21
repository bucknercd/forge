import pytest
from forge.executor import Executor
from forge.paths import Paths
import json

from tests.forge_test_project import configure_project, forge_block


def test_retry_milestone(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Retry Task
- **Objective**: Test retry logic
- **Scope**: Ensure retries work
- **Validation**: Verify retry behavior
{forge_block("FORGE_RETRY_OK")}
""",
    )

    # Simulate a failed milestone (validation failure from missing marker)
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state = {
        "1": {
            "status": "retry_pending",
            "attempts": 1
        }
    }
    with state_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=4)

    # Remove marker so first "retry" path could have failed; idempotent apply restores marker.
    Paths.REQUIREMENTS_FILE.write_text(
        "# Requirements\n\n## Overview\n\nBase content.\n", encoding="utf-8"
    )

    Executor.execute_milestone(1)

    with state_file.open("r", encoding="utf-8") as file:
        updated_state = json.load(file)
    assert updated_state["1"]["status"] == "completed"
    assert updated_state["1"]["attempts"] == 2
    assert "FORGE_RETRY_OK" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")
