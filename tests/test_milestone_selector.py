import pytest
import json
from pathlib import Path
from forge.milestone_selector import MilestoneSelector
from forge.milestone_state import MilestoneStateRepository

@pytest.fixture
def mock_milestone_service():
    class MockMilestoneService:
        def parse_milestones(self):
            return [
                {"id": 1, "objective": "First milestone"},
                {"id": 2, "objective": "Second milestone"},
                {"id": 3, "objective": "Third milestone"},
            ]

    return MockMilestoneService()

@pytest.fixture
def temp_state_file(tmp_path):
    return tmp_path / "milestone_state.json"

def test_returns_first_not_started_milestone(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"2": {"status": "completed"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone['id'] == 1
    assert next_milestone['status'] == "not_started"

def test_returns_retry_pending_before_not_started(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "retry_pending"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone['id'] == 1
    assert next_milestone['status'] == "retry_pending"

def test_skips_completed_milestones(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "completed"}, "2": {"status": "completed"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone['id'] == 3
    assert next_milestone['status'] == "not_started"

def test_returns_none_when_no_selectable_milestones(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "completed"}, "2": {"status": "completed"}, "3": {"status": "completed"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone is None

def test_handles_missing_state_file(mock_milestone_service, tmp_path):
    state_repository = MilestoneStateRepository(tmp_path / "nonexistent.json")
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone['id'] == 1
    assert next_milestone['status'] == "not_started"

def test_raises_value_error_on_unknown_status(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "unknown_status"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    with pytest.raises(ValueError):
        selector.get_next_milestone()