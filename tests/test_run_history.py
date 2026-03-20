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


def test_log_milestone_attempt_success_format(tmp_path):
    run_history_file = tmp_path / "run_history.log"
    original_path = Paths.RUN_HISTORY_FILE
    original_system_dir = Paths.SYSTEM_DIR
    Paths.SYSTEM_DIR = tmp_path
    Paths.RUN_HISTORY_FILE = run_history_file
    try:
        RunHistory.log_milestone_attempt(
            milestone_id=1,
            milestone_title="Milestone 1: First",
            status="success",
        )
        entry = json.loads(run_history_file.read_text(encoding="utf-8").strip())
        assert entry["milestone_id"] == 1
        assert entry["milestone_title"] == "Milestone 1: First"
        assert entry["status"] == "success"
        assert "ts" in entry
        assert "error_message" not in entry
    finally:
        Paths.RUN_HISTORY_FILE = original_path
        Paths.SYSTEM_DIR = original_system_dir


def test_log_milestone_attempt_failure_format(tmp_path):
    run_history_file = tmp_path / "run_history.log"
    original_path = Paths.RUN_HISTORY_FILE
    original_system_dir = Paths.SYSTEM_DIR
    Paths.SYSTEM_DIR = tmp_path
    Paths.RUN_HISTORY_FILE = run_history_file
    try:
        RunHistory.log_milestone_attempt(
            milestone_id=2,
            milestone_title="Milestone 2: Second",
            status="failure",
            error_message="Validation failed",
        )
        entry = json.loads(run_history_file.read_text(encoding="utf-8").strip())
        assert entry["milestone_id"] == 2
        assert entry["status"] == "failure"
        assert entry["error_message"] == "Validation failed"
    finally:
        Paths.RUN_HISTORY_FILE = original_path
        Paths.SYSTEM_DIR = original_system_dir


def test_log_milestone_attempt_repeated_appends(tmp_path):
    run_history_file = tmp_path / "run_history.log"
    original_path = Paths.RUN_HISTORY_FILE
    original_system_dir = Paths.SYSTEM_DIR
    Paths.SYSTEM_DIR = tmp_path
    Paths.RUN_HISTORY_FILE = run_history_file
    try:
        RunHistory.log_milestone_attempt(1, "M1", "success")
        RunHistory.log_milestone_attempt(1, "M1", "failure", error_message="err")
        lines = run_history_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        e1 = json.loads(lines[0])
        e2 = json.loads(lines[1])
        assert e1["status"] == "success"
        assert e2["status"] == "failure"
    finally:
        Paths.RUN_HISTORY_FILE = original_path
        Paths.SYSTEM_DIR = original_system_dir