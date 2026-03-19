# tests/test_run_history.py

import pytest
from forge.run_history import RunHistory
from forge.models import RunHistoryEntry
from forge.paths import Paths
from datetime import datetime
import json

def test_log_run(tmp_path):
    # Create a temporary run history file
    run_history_file = tmp_path / "run_history.log"

    # Override the path for testing
    original_path = Paths.RUN_HISTORY_FILE
    Paths.RUN_HISTORY_FILE = run_history_file

    try:
        # Log a run
        entry = RunHistoryEntry(
            task="Test Task",
            summary="Test Summary",
            status="success",
            timestamp=datetime.now(),
        )
        RunHistory.log_run(entry)

        # Verify the log entry
        assert run_history_file.exists()
        content = run_history_file.read_text()
        log_entry = json.loads(content.strip())
        assert log_entry["task"] == "Test Task"
        assert log_entry["status"] == "success"
        assert log_entry["summary"] == "Test Summary"
    finally:
        # Restore the original path
        Paths.RUN_HISTORY_FILE = original_path

def test_get_recent_entries(tmp_path):
    # Create a temporary run history file
    run_history_file = tmp_path / "run_history.log"

    # Override the path for testing
    original_path = Paths.RUN_HISTORY_FILE
    Paths.RUN_HISTORY_FILE = run_history_file

    try:
        # Write multiple entries
        run_history_file.write_text(
            json.dumps({"ts": "2026-03-19T12:00:00", "task": "Task 1", "status": "success", "summary": "Summary 1"}) + "\n" +
            json.dumps({"ts": "2026-03-19T12:01:00", "task": "Task 2", "status": "failure", "summary": "Summary 2"}) + "\n"
        )

        # Get recent entries
        entries = RunHistory.get_recent_entries(1)
        assert len(entries) == 1
        assert entries[0]["task"] == "Task 2"
        assert entries[0]["status"] == "failure"
    finally:
        # Restore the original path
        Paths.RUN_HISTORY_FILE = original_path