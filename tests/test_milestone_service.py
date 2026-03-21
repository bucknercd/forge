# tests/test_milestone_service.py

import pytest
from forge.design_manager import MilestoneService, Milestone
from forge.paths import Paths
from forge.repository import FileRepository

def test_parse_milestones():
    content = """# Milestones

## Milestone 1: Bootstrap Repository
- **Objective**: Create the initial repository structure and documentation.
- **Scope**: Define the repo structure, draft documentation, and set up Python dependencies.
- **Validation**: Ensure all documentation is complete and Python environment is functional.

## Milestone 2: Vision Loader
- **Objective**: Implement the ability to load and persist a project vision.
- **Scope**: Support reading and writing the `vision.txt` file.
- **Validation**: Verify that the vision can be loaded, edited, and saved.
"""
    milestones = MilestoneService.parse_milestones(content)

    assert len(milestones) == 2

    assert milestones[0].id == 1
    assert milestones[0].title == "Milestone 1: Bootstrap Repository"
    assert milestones[0].objective == "Create the initial repository structure and documentation."
    assert milestones[0].scope == "Define the repo structure, draft documentation, and set up Python dependencies."
    assert milestones[0].validation == "Ensure all documentation is complete and Python environment is functional."

    assert milestones[1].id == 2
    assert milestones[1].title == "Milestone 2: Vision Loader"
    assert milestones[1].objective == "Implement the ability to load and persist a project vision."
    assert milestones[1].scope == "Support reading and writing the `vision.txt` file."
    assert milestones[1].validation == "Verify that the vision can be loaded, edited, and saved."


def test_parse_milestones_with_dependencies():
    content = """# Milestones

## Milestone 1: Prerequisite
- **Objective**: Do the prerequisite
- **Scope**: Scope for prereq
- **Validation**: Validate prereq

## Milestone 2: Dependent
- **Depends On**: 1
- **Objective**: Do dependent work
- **Scope**: Scope for dependent
- **Validation**: Validate dependent

## Milestone 3: Dependent Again
- **Depends On**: 1, 2
- **Objective**: Do dependent again
- **Scope**: Scope for dependent again
- **Validation**: Validate dependent again
"""
    milestones = MilestoneService.parse_milestones(content)

    assert len(milestones) == 3
    assert milestones[0].depends_on == []
    assert milestones[1].depends_on == [1]
    assert milestones[2].depends_on == [1, 2]

def test_list_milestones(tmp_path):
    test_file = tmp_path / "milestones.md"
    test_file.write_text("""# Milestones

## Milestone 1: Test Milestone
- **Objective**: Test objective.
- **Scope**: Test scope.
- **Validation**: Test validation.
""")
    Paths.MILESTONES_FILE = test_file

    milestones = MilestoneService.list_milestones()
    assert len(milestones) == 1
    assert milestones[0].title == "Milestone 1: Test Milestone"

def test_get_milestone(tmp_path):
    test_file = tmp_path / "milestones.md"
    test_file.write_text("""# Milestones

## Milestone 1: Test Milestone
- **Objective**: Test objective.
- **Scope**: Test scope.
- **Validation**: Test validation.
""")
    Paths.MILESTONES_FILE = test_file

    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    assert milestone.title == "Milestone 1: Test Milestone"
    assert milestone.objective == "Test objective."
    assert milestone.scope == "Test scope."
    assert milestone.validation == "Test validation."


def test_malformed_milestone_heading_detected():
    content = """# Milestones

## Milestone One
- **Objective**: Test objective.
"""
    with pytest.raises(ValueError) as exc:
        MilestoneService.parse_milestones(content)
    assert "Malformed milestone heading" in str(exc.value)


def test_missing_objective_detected():
    content = """# Milestones

## Milestone 1: Missing Objective
- **Scope**: Test scope.
- **Validation**: Test validation.
"""
    with pytest.raises(ValueError) as exc:
        MilestoneService.parse_milestones(content)
    assert "missing required objective" in str(exc.value).lower()


def test_parse_milestones_extracts_forge_actions_and_validation():
    content = """# Milestones

## Milestone 1: With Forge
- **Objective**: O1
- **Scope**: S1
- **Validation**: V1
- **Forge Actions**:
  - append_section requirements Overview | HELLO
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements HELLO
"""
    milestones = MilestoneService.parse_milestones(content)
    assert len(milestones) == 1
    assert milestones[0].forge_actions == [
        "append_section requirements Overview | HELLO",
        "mark_milestone_completed",
    ]
    assert milestones[0].forge_validation == ["file_contains requirements HELLO"]


def test_multiple_milestones_parse_deterministically():
    content = """# Milestones

## Milestone 1: First
- **Objective**: O1

## Milestone 2: Second
- **Objective**: O2
"""
    milestones = MilestoneService.parse_milestones(content)
    assert [m.id for m in milestones] == [1, 2]
    assert [m.title for m in milestones] == ["Milestone 1: First", "Milestone 2: Second"]