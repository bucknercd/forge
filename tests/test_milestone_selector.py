import pytest
import json
from pathlib import Path
from forge.milestone_selector import MilestoneSelector
from forge.milestone_state import MilestoneStateRepository
from forge.design_manager import Milestone

@pytest.fixture
def mock_milestone_service():
    class MockMilestoneService:
        def parse_milestones(self, content):
            return [
                Milestone(id=1, title="First Task", objective="Complete the first task", scope="Initial setup", validation="Verify basics"),
                Milestone(id=2, title="Second Task", objective="Do the second task", scope="Intermediate setup", validation="Verify intermediate"),
                Milestone(id=3, title="Third Task", objective="Finalize the project", scope="Final setup", validation="Verify final"),
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
    assert next_milestone.id == 1
    assert next_milestone.title == "First Task"

def test_returns_retry_pending_before_not_started(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "retry_pending"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone.id == 1
    assert next_milestone.title == "First Task"

def test_skips_completed_milestones(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "completed"}, "2": {"status": "completed"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone.id == 3
    assert next_milestone.title == "Third Task"

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
    assert next_milestone.id == 1
    assert next_milestone.title == "First Task"

def test_raises_value_error_on_unknown_status(mock_milestone_service, temp_state_file):
    temp_state_file.write_text(json.dumps({"1": {"status": "unknown_status"}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(mock_milestone_service, state_repository)

    with pytest.raises(ValueError):
        selector.get_next_milestone()


def test_dependency_blocks_retry_pending_until_completed(mock_milestone_service, temp_state_file):
    # Override milestone graph with a dependent retry_pending milestone.
    class Service:
        def parse_milestones(self, content):
            return [
                Milestone(id=1, title="First Task", objective="o", scope="s", validation="v", depends_on=[]),
                Milestone(id=2, title="Second Task", objective="o", scope="s", validation="v", depends_on=[1]),
                Milestone(id=3, title="Third Task", objective="o", scope="s", validation="v", depends_on=[]),
            ]

    temp_state_file.write_text(json.dumps({"2": {"status": "retry_pending", "attempts": 0}}))
    state_repository = MilestoneStateRepository(temp_state_file)
    selector = MilestoneSelector(Service(), state_repository)

    # Milestone 2 is retry_pending, but dependency 1 isn't completed yet,
    # so selector should choose milestone 1 first.
    next_milestone = selector.get_next_milestone()
    assert next_milestone.id == 1


def test_dependent_runnable_after_prerequisite_completed(tmp_path):
    class Service:
        def parse_milestones(self, content):
            return [
                Milestone(id=1, title="Prereq", objective="o", scope="s", validation="v", depends_on=[]),
                Milestone(id=2, title="Dependent", objective="o", scope="s", validation="v", depends_on=[1]),
            ]

    state_file = tmp_path / "milestone_state.json"
    state_file.write_text(json.dumps({"1": {"status": "completed", "attempts": 0}, "2": {"status": "not_started", "attempts": 0}}))
    state_repository = MilestoneStateRepository(state_file)
    selector = MilestoneSelector(Service(), state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone.id == 2


def test_blocked_report_when_failed_prerequisite_blocks_dependent(tmp_path):
    class Service:
        def parse_milestones(self, content):
            return [
                Milestone(id=1, title="Prereq", objective="o", scope="s", validation="v", depends_on=[]),
                Milestone(id=2, title="Dependent", objective="o", scope="s", validation="v", depends_on=[1]),
            ]

    state_file = tmp_path / "milestone_state.json"
    state_file.write_text(json.dumps({"1": {"status": "failed", "attempts": 2}, "2": {"status": "not_started", "attempts": 0}}))
    state_repository = MilestoneStateRepository(state_file)
    selector = MilestoneSelector(Service(), state_repository)

    next_milestone, report = selector.get_next_milestone_with_report()
    assert next_milestone is None
    assert report["kind"] == "blocked"


def test_failed_prerequisite_prevents_dependent_selection_even_if_retry_pending(tmp_path):
    class Service:
        def parse_milestones(self, content):
            return [
                Milestone(id=1, title="Prereq", objective="o", scope="s", validation="v", depends_on=[]),
                Milestone(id=2, title="Dependent Retry", objective="o", scope="s", validation="v", depends_on=[1]),
                Milestone(id=3, title="Independent Retry", objective="o", scope="s", validation="v", depends_on=[]),
            ]

    state_file = tmp_path / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": {"status": "failed", "attempts": 2},
                "2": {"status": "retry_pending", "attempts": 1},
                "3": {"status": "retry_pending", "attempts": 0},
            }
        )
    )
    state_repository = MilestoneStateRepository(state_file)
    selector = MilestoneSelector(Service(), state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone.id == 3


def test_retry_pending_preferred_over_not_started_when_eligible(tmp_path):
    class Service:
        def parse_milestones(self, content):
            return [
                Milestone(id=1, title="First Task", objective="o", scope="s", validation="v", depends_on=[]),
                Milestone(id=2, title="Second Task", objective="o", scope="s", validation="v", depends_on=[]),
            ]

    state_file = tmp_path / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": {"status": "not_started", "attempts": 0},
                "2": {"status": "retry_pending", "attempts": 1},
            }
        )
    )
    state_repository = MilestoneStateRepository(state_file)
    selector = MilestoneSelector(Service(), state_repository)

    next_milestone = selector.get_next_milestone()
    assert next_milestone.id == 2