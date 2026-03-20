# tests/test_decision_tracker.py

import pytest
from forge.decision_tracker import DecisionTracker
from forge.models import Decision
from forge.paths import Paths
from datetime import datetime

def test_append_decision(tmp_path):
    # Create a temporary decisions file
    decisions_file = tmp_path / "decisions.md"

    # Override the path for testing
    original_path = Paths.DECISIONS_FILE
    Paths.DECISIONS_FILE = decisions_file

    try:
        # Append a decision
        decision = Decision(
            title="Test Decision",
            context="Test Context",
            decision="Test Decision Content",
            rationale="Test Rationale",
            timestamp=datetime.now(),
        )
        DecisionTracker.append_decision(decision)

        # Verify the decision was appended
        content = decisions_file.read_text()
        assert "Test Decision" in content
        assert "Test Context" in content
        assert "Test Decision Content" in content
        assert "Test Rationale" in content
    finally:
        # Restore the original path
        Paths.DECISIONS_FILE = original_path


def test_repeated_appends_preserve_existing_content(tmp_path):
    decisions_file = tmp_path / "decisions.md"
    original_path = Paths.DECISIONS_FILE
    Paths.DECISIONS_FILE = decisions_file
    try:
        decision1 = Decision(
            title="First",
            context="C1",
            decision="D1",
            rationale="R1",
            timestamp=datetime.now(),
        )
        decision2 = Decision(
            title="Second",
            context="C2",
            decision="D2",
            rationale="R2",
            timestamp=datetime.now(),
        )
        DecisionTracker.append_decision(decision1)
        DecisionTracker.append_decision(decision2)
        content = decisions_file.read_text(encoding="utf-8")
        assert "## First" in content
        assert "## Second" in content
    finally:
        Paths.DECISIONS_FILE = original_path