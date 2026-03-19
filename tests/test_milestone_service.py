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