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


def test_non_init_command_fails_before_init(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "status"])
    main()
    out = capsys.readouterr().out
    assert "not an initialized Forge project" in out
    assert "forge init" in out


def test_cli_commands_operate_after_init(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr("sys.argv", ["forge", "init"])
    main()
    _ = capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["forge", "status"])
    main()
    status_out = capsys.readouterr().out
    assert "Repository Status:" in status_out

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
