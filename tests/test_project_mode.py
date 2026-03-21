import json
from pathlib import Path

from forge.cli import main
from forge.paths import Paths


def _write_minimal_milestones(path: Path):
    path.write_text(
        """
# Milestones

## Milestone 1: First
- **Objective**: Build first
- **Scope**: Small scope
- **Validation**: Validate first
- **Forge Actions**:
  - append_section requirements Overview | FORGE_CLI_OK
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements FORGE_CLI_OK
"""
    )


def test_paths_refresh_uses_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh()
    assert Paths.BASE_DIR == tmp_path
    assert Paths.DOCS_DIR == tmp_path / "docs"
    assert Paths.SYSTEM_DIR == tmp_path / ".system"
    assert Paths.ARTIFACTS_DIR == tmp_path / "artifacts"


def test_ensure_project_structure_creates_required_dirs(tmp_path):
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    assert Paths.DOCS_DIR.exists()
    assert Paths.SYSTEM_DIR.exists()
    assert Paths.ARTIFACTS_DIR.exists()


def test_project_validation_false_for_non_forge_dir(tmp_path):
    Paths.refresh(tmp_path)
    is_valid, missing = Paths.project_validation()
    assert is_valid is False
    assert len(missing) > 0


def test_project_validation_true_for_initialized_project(tmp_path):
    Paths.refresh(tmp_path)
    Paths.initialize_project()
    is_valid, missing = Paths.project_validation()
    assert is_valid is True
    assert missing == []


def test_init_creates_required_directories_and_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    assert (tmp_path / "docs").exists()
    assert (tmp_path / ".system").exists()
    assert (tmp_path / "artifacts").exists()
    assert (tmp_path / "docs" / "vision.txt").exists()
    assert (tmp_path / "docs" / "requirements.md").exists()
    assert (tmp_path / "docs" / "architecture.md").exists()
    assert (tmp_path / "docs" / "decisions.md").exists()
    assert (tmp_path / "docs" / "milestones.md").exists()
    assert (tmp_path / ".system" / "run_history.log").exists()
    assert "Project Vision" in (tmp_path / "docs" / "vision.txt").read_text(encoding="utf-8")
    assert "# Requirements" in (tmp_path / "docs" / "requirements.md").read_text(encoding="utf-8")
    assert "# Architecture" in (tmp_path / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "# Decisions" in (tmp_path / "docs" / "decisions.md").read_text(encoding="utf-8")
    assert "# Milestones" in (tmp_path / "docs" / "milestones.md").read_text(encoding="utf-8")


def test_init_is_idempotent_and_does_not_overwrite_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    vision_file = tmp_path / "docs" / "vision.txt"
    vision_file.write_text("custom vision", encoding="utf-8")

    # Run init again; file content should remain unchanged.
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out
    assert vision_file.read_text(encoding="utf-8") == "custom vision"


def test_initialize_project_writes_templates_only_for_missing_files(tmp_path):
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()

    # Pre-create one file with custom content to verify no overwrite.
    Paths.VISION_FILE.write_text("my vision", encoding="utf-8")
    result = Paths.initialize_project()

    assert Paths.VISION_FILE.read_text(encoding="utf-8") == "my vision"
    assert Paths.REQUIREMENTS_FILE.exists()
    assert Paths.ARCHITECTURE_FILE.exists()
    assert Paths.DECISIONS_FILE.exists()
    assert Paths.MILESTONES_FILE.exists()
    assert Paths.RUN_HISTORY_FILE.exists()
    assert "# Requirements" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")
    # Existing file should not be marked as newly created
    assert Paths.VISION_FILE not in result["created_files"]


def test_non_init_command_fails_before_init(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "status"])
    main()
    out = capsys.readouterr().out
    assert "Repository Status:" in out
    assert "Project State: not_initialized" in out
    assert "Hint: run `forge init`" in out


def test_cli_commands_operate_after_init(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["forge", "status"])
    main()
    status_out = capsys.readouterr().out
    assert "Repository Status:" in status_out
    assert "Project State: initialized_incomplete" in status_out

    milestones_file = tmp_path / "docs" / "milestones.md"
    _write_minimal_milestones(milestones_file)

    monkeypatch.setattr("sys.argv", ["forge", "milestone-sync-state"])
    main()
    _ = capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["forge", "milestone-next"])
    main()
    next_out = capsys.readouterr().out
    assert "Next milestone: 1." in next_out

    monkeypatch.setattr("sys.argv", ["forge", "execute-next"])
    main()
    exec_out = capsys.readouterr().out
    assert "Milestone 1 completed." in exec_out

    state_file = tmp_path / ".system" / "milestone_state.json"
    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "completed"


def test_status_reports_ready_after_content_filled(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "vision.txt").write_text("Custom vision", encoding="utf-8")
    (tmp_path / "docs" / "requirements.md").write_text("# Requirements\n- custom", encoding="utf-8")
    (tmp_path / "docs" / "architecture.md").write_text("# Architecture\ncustom", encoding="utf-8")
    (tmp_path / "docs" / "decisions.md").write_text("# Decisions\ncustom", encoding="utf-8")
    (tmp_path / "docs" / "milestones.md").write_text(
        "# Milestones\n\n## Milestone 1: Ready\n- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["forge", "status"])
    main()
    out = capsys.readouterr().out
    assert "Project State: ready" in out


def test_malformed_milestones_produce_clear_error_for_milestone_next(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
        "# Milestones\n\n## Milestone One\n- **Objective**: Test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-next"])
    main()
    out = capsys.readouterr().out
    assert "Milestone definition error:" in out
    assert "Malformed milestone heading" in out


def test_missing_objective_prevents_execute_next_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
        "# Milestones\n\n## Milestone 1: Bad Milestone\n- **Scope**: S\n- **Validation**: V\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["forge", "execute-next"])
    main()
    out = capsys.readouterr().out
    assert "Milestone definition error:" in out
    assert "missing required objective" in out.lower()


def test_milestone_lint_main_returns_zero_on_success(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
        """
# Milestones

## Milestone 1: Good
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | OK
- **Forge Validation**:
  - file_contains requirements OK
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-lint"])
    rc = main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Lint Summary: 0 error(s) across 1 milestone(s) checked." in out


def test_milestone_lint_main_returns_one_on_failure_all(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
        """
# Milestones

## Milestone 1: Bad
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section badtarget Overview | BAD
- **Forge Validation**:
  - file_contains requirements BAD
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-lint"])
    rc = main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL] Milestone 1" in out


def test_milestone_lint_main_returns_one_on_failure_specific_id(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
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
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-lint", "99"])
    rc = main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "Milestone 99 not found." in out
