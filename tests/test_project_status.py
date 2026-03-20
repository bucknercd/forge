from forge.paths import Paths
from forge.project_status import analyze_project_status


def test_validation_reports_missing_files(tmp_path):
    Paths.refresh(tmp_path)
    report = analyze_project_status()
    assert report["state"] == "not_initialized"
    assert len(report["missing_paths"]) > 0


def test_validation_reports_template_only_and_empty_files(tmp_path):
    Paths.refresh(tmp_path)
    Paths.initialize_project()

    # Make one key file empty and leave another at template-only content.
    Paths.REQUIREMENTS_FILE.write_text("", encoding="utf-8")

    report = analyze_project_status()
    assert report["state"] == "initialized_incomplete"
    assert str(Paths.REQUIREMENTS_FILE) in report["empty_files"]
    assert str(Paths.VISION_FILE) in report["template_only_files"]


def test_validation_distinguishes_initialized_vs_ready(tmp_path):
    Paths.refresh(tmp_path)
    Paths.initialize_project()

    incomplete = analyze_project_status()
    assert incomplete["state"] == "initialized_incomplete"

    # Fill key docs with minimal non-template content and valid milestone heading.
    Paths.VISION_FILE.write_text("Custom vision", encoding="utf-8")
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n- custom", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\ncustom", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# Decisions\ncustom", encoding="utf-8")
    Paths.MILESTONES_FILE.write_text(
        "# Milestones\n\n## Milestone 1: Custom\n- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n",
        encoding="utf-8",
    )

    ready = analyze_project_status()
    assert ready["state"] == "ready"
    assert ready["missing_paths"] == []
