import json

import pytest

from forge.cli import ForgeCLI
from forge.executor import Executor
from forge.paths import Paths


def _write_dependency_milestones(path):
    path.write_text(
        """
# Milestones

## Milestone 1: Prerequisite
- **Objective**: Do the prerequisite
- **Scope**: Scope for prereq
- **Validation**: Validate prereq

## Milestone 2: Dependent
- **Depends On**: 1
- **Objective**: Do dependent work
- **Scope**: Scope for dependent
- **Validation**: Validate dependent
"""
    )


def _write_failed_prereq_milestones(path):
    path.write_text(
        """
# Milestones

## Milestone 1: Prerequisite (Will Fail)
- **Objective**: Prerequisite exists
- **Scope**:
- **Validation**:

## Milestone 2: Dependent
- **Depends On**: 1
- **Objective**: Dependent objective
- **Scope**: Dependent scope
- **Validation**: Dependent validation
"""
    )


def test_dependent_becomes_runnable_after_prerequisite_completes(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_dependency_milestones(Paths.MILESTONES_FILE)

    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    ForgeCLI.milestone_sync_state()

    ForgeCLI.milestone_next()
    out1 = capsys.readouterr().out
    assert "Next milestone: 1." in out1

    Executor.execute_milestone(1)

    ForgeCLI.milestone_next()
    out2 = capsys.readouterr().out
    assert "Next milestone: 2." in out2


def test_dependent_is_blocked_when_prerequisite_fails_after_retries(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_failed_prereq_milestones(Paths.MILESTONES_FILE)

    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    ForgeCLI.milestone_sync_state()

    # Run prerequisite until it fails (MAX_RETRIES=2)
    Executor.execute_milestone(1)
    Executor.execute_milestone(1)

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "failed"
    assert state["1"]["attempts"] == 2

    ForgeCLI.milestone_next()
    out = capsys.readouterr().out
    assert "Progress is blocked by failed/unmet prerequisites." in out

    before = state["2"]
    Executor.execute_milestone(2)  # should refuse due to deps not completed
    state_after = json.loads(state_file.read_text())
    assert state_after["2"] == before


def test_project_reports_all_complete_when_no_runnable_milestones(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    Paths.MILESTONES_FILE.write_text(
        """
# Milestones

## Milestone 1: A
- **Objective**: A objective
- **Scope**: A scope
- **Validation**: A validation

## Milestone 2: B
- **Objective**: B objective
- **Scope**: B scope
- **Validation**: B validation
"""
    )

    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    ForgeCLI.milestone_sync_state()
    capsys.readouterr()
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"

    # Mark all as completed without executing.
    state = json.loads(state_file.read_text())
    for mid in ["1", "2"]:
        state[mid]["status"] = "completed"
    state_file.write_text(json.dumps(state, indent=4))

    ForgeCLI.milestone_next()
    out = capsys.readouterr().out
    assert out.strip() == "All milestones completed."

