import json

from forge.executor import Executor
from forge.paths import Paths
from forge.validator import Validator
from tests.forge_test_project import configure_project, forge_block


def test_invalid_forge_action_reports_line_and_milestone(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Bad Action
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section wrongtarget Overview | text
- **Forge Validation**:
  - file_contains requirements text
""",
    )

    Executor.execute_milestone(1)
    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "retry_pending"

    result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    assert result["apply_errors"]
    msg = result["apply_errors"][0]
    assert "Milestone 1 action parse error" in msg
    assert "forge action line" in msg


def test_malformed_forge_actions_block_reports_line(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Bad Block
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  append_section requirements Overview | text
- **Forge Validation**:
  - file_contains requirements text
""",
    )

    # Parsing fails before execution starts; ensure no artifact result is created.
    Executor.execute_milestone(1)
    assert not (Paths.SYSTEM_DIR / "results" / "milestone_1.json").exists()


def test_partial_failure_then_retry_success_updates_diagnostics(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Retry After Bad Validation
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | RETRY_OK
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements DOES_NOT_EXIST
""",
    )

    Executor.execute_milestone(1)
    first_state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert first_state["1"]["status"] == "retry_pending"

    first_result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    assert "validation_error" in first_result
    assert "file_contains failed" in first_result["validation_error"]

    # Fix validation rule, then retry.
    Paths.MILESTONES_FILE.write_text(
        f"""
# Milestones

## Milestone 1: Retry After Bad Validation
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("RETRY_OK")}
""",
        encoding="utf-8",
    )
    Executor.execute_milestone(1)
    second_state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert second_state["1"]["status"] == "completed"
    assert second_state["1"]["attempts"] == 2
    assert Validator.validate_milestone_with_report(1)[0] is True


def test_invalid_forge_validation_reports_line_and_context(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Bad Validation
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | VALIDATION_BAD
- **Forge Validation**:
  - unknown_rule requirements VALIDATION_BAD
""",
    )

    Executor.execute_milestone(1)
    result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    assert "validation_error" in result
    assert "Invalid Forge Validation for milestone 1" in result["validation_error"]
    assert "line" in result["validation_error"]
