import pytest
from forge.cli import ForgeCLI, main
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


def test_init_creates_system_dir_and_baseline_files(tmp_path, capsys):
    Paths.DOCS_DIR = tmp_path / "docs"
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.VISION_FILE = Paths.DOCS_DIR / "vision.txt"
    Paths.REQUIREMENTS_FILE = Paths.DOCS_DIR / "requirements.md"
    Paths.ARCHITECTURE_FILE = Paths.DOCS_DIR / "architecture.md"
    Paths.DECISIONS_FILE = Paths.DOCS_DIR / "decisions.md"
    Paths.MILESTONES_FILE = Paths.DOCS_DIR / "milestones.md"

    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.RUN_HISTORY_FILE = Paths.SYSTEM_DIR / "run_history.log"

    ForgeCLI.init()

    # Validate system directory
    assert Paths.SYSTEM_DIR.exists()
    assert Paths.RUN_HISTORY_FILE.exists()
    assert Paths.VISION_FILE.exists()
    assert Paths.REQUIREMENTS_FILE.exists()
    assert Paths.ARCHITECTURE_FILE.exists()
    assert Paths.DECISIONS_FILE.exists()
    assert Paths.MILESTONES_FILE.exists()
    assert "Project Vision" in Paths.VISION_FILE.read_text(encoding="utf-8")
    assert "# Requirements" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")
    assert "# Architecture" in Paths.ARCHITECTURE_FILE.read_text(encoding="utf-8")
    assert "# Decisions" in Paths.DECISIONS_FILE.read_text(encoding="utf-8")
    assert "# Milestones" in Paths.MILESTONES_FILE.read_text(encoding="utf-8")

def _minimal_milestones_md() -> str:
    return """# Milestones

## Milestone 1: One
- **Objective**: O1
- **Scope**: S1
- **Validation**: V1

## Milestone 2: Two
- **Objective**: O2
- **Scope**: S2
- **Validation**: V2
"""


def test_milestone_list(tmp_path):
    Paths.refresh(tmp_path)
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.MILESTONES_FILE.write_text(_minimal_milestones_md(), encoding="utf-8")

    ForgeCLI.milestone_list()

def test_milestone_show(tmp_path):
    Paths.refresh(tmp_path)
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.MILESTONES_FILE.write_text(_minimal_milestones_md(), encoding="utf-8")

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
    assert state["1"]["status"] == "in_progress"
    assert state["1"]["attempts"] == 0

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
    assert state["1"]["status"] == "in_progress"
    assert state["1"]["attempts"] == 0
    assert state.get("2") == None  # Milestone 2 should not be started yet

    # Validate the milestone-status output
    ForgeCLI.milestone_status()


def _write_two_milestones(path):
    path.write_text(
        """
# Milestones

## Milestone 1: First Task
- **Objective**: Complete the first task
- **Scope**: Initial setup
- **Validation**: Verify basics

## Milestone 2: Second Task
- **Objective**: Complete the second task
- **Scope**: Advanced setup
- **Validation**: Verify advanced features
"""
    )


def test_milestone_sync_state_initializes_missing_file(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_two_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"

    ForgeCLI.milestone_sync_state()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["1"] == {"status": "not_started", "attempts": 0}
    assert state["2"] == {"status": "not_started", "attempts": 0}


def test_milestone_sync_state_adds_missing_entries(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_two_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(json.dumps({"1": {"status": "completed", "attempts": 1}}, indent=4))

    ForgeCLI.milestone_sync_state()

    state = json.loads(state_file.read_text())
    assert state["1"] == {"status": "completed", "attempts": 1}
    assert state["2"] == {"status": "not_started", "attempts": 0}


def test_milestone_sync_state_preserves_valid_existing_entries(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_two_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    original = {
        "1": {"status": "completed", "attempts": 2},
        "2": {"status": "retry_pending", "attempts": 1},
    }
    state_file.write_text(json.dumps(original, indent=4))

    ForgeCLI.milestone_sync_state()

    state = json.loads(state_file.read_text())
    assert state == original


def test_milestone_sync_state_removes_stale_entries(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_two_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": {"status": "in_progress", "attempts": 1},
                "2": {"status": "not_started", "attempts": 0},
                "999": {"status": "completed", "attempts": 3},
            },
            indent=4,
        )
    )

    ForgeCLI.milestone_sync_state()

    state = json.loads(state_file.read_text())
    assert "999" not in state
    assert "1" in state
    assert "2" in state


def test_milestone_sync_state_cli_output(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True)
    _write_two_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"

    ForgeCLI.milestone_sync_state()
    first_out = capsys.readouterr().out
    assert "Milestone state synchronized." in first_out
    assert "Initialized state file." in first_out
    assert "Added entries: 2" in first_out
    assert "Removed entries" not in first_out

    ForgeCLI.milestone_sync_state()
    second_out = capsys.readouterr().out
    assert second_out.strip() == "Milestone state is already synchronized."


def test_status_formats_milestone_states_consistently(tmp_path, capsys):
    Paths.DOCS_DIR = tmp_path / "docs"
    Paths.DOCS_DIR.mkdir()
    Paths.VISION_FILE = Paths.DOCS_DIR / "vision.md"
    Paths.REQUIREMENTS_FILE = Paths.DOCS_DIR / "requirements.md"
    Paths.ARCHITECTURE_FILE = Paths.DOCS_DIR / "architecture.md"
    Paths.DECISIONS_FILE = Paths.DOCS_DIR / "decisions.md"
    Paths.MILESTONES_FILE = Paths.DOCS_DIR / "milestones.md"
    Paths.RUN_HISTORY_FILE = tmp_path / "run_history.log"
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    Paths.MILESTONES_FILE.write_text("## Milestone 1\nDetails")
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": "in_progress",
                "2": {"status": "not_started", "attempts": 0},
            },
            indent=4,
        )
    )

    ForgeCLI.status()
    out = capsys.readouterr().out
    assert "Milestone 1: status=in_progress, attempts=0" in out
    assert "Milestone 2: status=not_started, attempts=0" in out


def test_milestone_lint_all_reports_ok(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.MILESTONES_FILE.write_text(
        """
# Milestones

## Milestone 1: Good
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | GOOD
- **Forge Validation**:
  - file_contains requirements GOOD

## Milestone 2: Good2
- **Objective**: O2
- **Scope**: S2
- **Validation**: V2
- **Forge Actions**:
  - append_section architecture Design | TEXT
- **Forge Validation**:
  - file_contains architecture TEXT
""",
        encoding="utf-8",
    )
    ForgeCLI.milestone_lint()
    out = capsys.readouterr().out
    assert "[OK] Milestone 1" in out
    assert "[OK] Milestone 2" in out
    assert "Lint Summary: 0 error(s) across 2 milestone(s) checked." in out


def test_milestone_lint_specific_id_and_parse_error(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.MILESTONES_FILE.write_text(
        """
# Milestones

## Milestone 1: Good
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | GOOD
- **Forge Validation**:
  - file_contains requirements GOOD

## Milestone 2: Bad
- **Objective**: O2
- **Scope**: S2
- **Validation**: V2
- **Forge Actions**:
  - append_section badtarget Overview | BAD
- **Forge Validation**:
  - file_contains requirements BAD
""",
        encoding="utf-8",
    )
    ForgeCLI.milestone_lint(2)
    out = capsys.readouterr().out
    assert "[FAIL] Milestone 2" in out
    assert "line" in out
    assert "Lint Summary: 1 error(s) across 1 milestone(s) checked." in out


def test_milestone_lint_missing_id_reports_error(tmp_path, capsys):
    Paths.MILESTONES_FILE = tmp_path / "docs" / "milestones.md"
    Paths.MILESTONES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _write_two_milestones(Paths.MILESTONES_FILE)
    ForgeCLI.milestone_lint(99)
    out = capsys.readouterr().out
    assert "Milestone 99 not found." in out
    assert "Lint Summary: 1 error(s) across 0 milestone(s) checked." in out


def test_run_history_cli_prints_entries(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    Paths.refresh(tmp_path)
    Paths.RUN_HISTORY_FILE.write_text(
        json.dumps(
            {
                "ts": "2099-01-01T00:00:00",
                "task": "demo task",
                "status": "ok",
                "summary": "summary line",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "run-history", "--limit", "5"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "demo task" in out
    assert "summary line" in out