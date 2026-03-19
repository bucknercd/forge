import pytest
from forge.cli import ForgeCLI
from forge.paths import Paths
from pathlib import Path
import json

def test_status(tmp_path):
    Paths.DOCS_DIR = tmp_path / "docs"
    Paths.DOCS_DIR.mkdir()
    Paths.VISION_FILE = Paths.DOCS_DIR / "vision.md"
    Paths.VISION_FILE.write_text("Vision content")
    Paths.MILESTONES_FILE = Paths.DOCS_DIR / "milestones.md"
    Paths.MILESTONES_FILE.write_text("## Milestone 1\nDetails\n## Milestone 2\nDetails")
    Paths.RUN_HISTORY_FILE = tmp_path / "run_history.log"
    Paths.RUN_HISTORY_FILE.write_text(json.dumps([{"action": "start", "milestone_id": 1, "title": "Milestone 1"}]))

    ForgeCLI.status()

def test_milestone_list(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("## Milestone 1\nDetails\n## Milestone 2\nDetails")

    ForgeCLI.milestone_list()

def test_milestone_show(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("## Milestone 1\nDetails\n## Milestone 2\nDetails")

    ForgeCLI.milestone_show(1)

def test_milestone_start(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("""
# Milestones

## Milestone 1: First Task
- **Objective**: Complete the first task
- **Scope**: Initial setup
- **Validation**: Verify basics
""")
    Paths.RUN_HISTORY_FILE = tmp_path / "run_history.log"

    ForgeCLI.milestone_start(1)

    # Validate the run history file format
    with Paths.RUN_HISTORY_FILE.open("r", encoding="utf-8") as file:
        lines = file.readlines()
    assert len(lines) == 1

    log_entry = json.loads(lines[0])
    assert log_entry["task"] == "Start milestone 1"
    assert log_entry["summary"] == "Milestone 1: First Task: Complete the first task"
    assert log_entry["status"] == "started"

def test_milestone_start_with_workflow(tmp_path):
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
    Paths.RUN_HISTORY_FILE = Paths.SYSTEM_DIR / "run_history.log"

    # Run the milestone_start command
    ForgeCLI.milestone_start(1)

    # Validate the plan file
    plan_file = Paths.SYSTEM_DIR / "plans" / "milestone_1.md"
    assert plan_file.exists()
    plan_content = plan_file.read_text()
    assert "# Plan for Milestone 1: First Task" in plan_content
    assert "## Objective\nComplete the first task" in plan_content

    # Validate the milestone state
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["1"] == "in_progress"

    # Validate the run history
    with Paths.RUN_HISTORY_FILE.open("r", encoding="utf-8") as file:
        lines = file.readlines()
    assert len(lines) == 1
    log_entry = json.loads(lines[0])
    assert log_entry["task"] == "Start milestone 1"
    assert log_entry["summary"] == "Milestone 1: First Task: Complete the first task"
    assert log_entry["status"] == "started"

def test_milestone_state_tracking(tmp_path):
    # Setup milestone file
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.MILESTONES_FILE.write_text("""
# Milestones

## Milestone 1: First Task
- **Objective**: Complete the first task
- **Scope**: Initial setup
- **Validation**: Verify basics

## Milestone 2: Second Task
- **Objective**: Complete the second task
- **Scope**: Advanced setup
- **Validation**: Verify advanced features
""")

    # Setup system directory
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.RUN_HISTORY_FILE = Paths.SYSTEM_DIR / "run_history.log"

    # Run the milestone_start command for milestone 1
    ForgeCLI.milestone_start(1)

    # Validate the milestone state file
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["1"] == "in_progress"
    assert state.get("2") == None  # Milestone 2 should not be started yet

    # Validate the milestone-status output
    ForgeCLI.milestone_status()