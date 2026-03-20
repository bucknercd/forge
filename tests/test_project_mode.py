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


def test_cli_commands_operate_against_temp_project_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    # status should run against cwd and auto-create required dirs
    monkeypatch.setattr("sys.argv", ["forge", "status"])
    main()
    status_out = capsys.readouterr().out
    assert "Repository Status:" in status_out
    assert (tmp_path / "docs").exists()
    assert (tmp_path / ".system").exists()
    assert (tmp_path / "artifacts").exists()

    # prepare milestones in target project directory
    milestones_file = tmp_path / "docs" / "milestones.md"
    _write_minimal_milestones(milestones_file)

    # sync state then run milestone-next
    monkeypatch.setattr("sys.argv", ["forge", "milestone-sync-state"])
    main()
    _ = capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["forge", "milestone-next"])
    main()
    next_out = capsys.readouterr().out
    assert "Next milestone: 1." in next_out

    # execute-next should execute within the temp project directory
    monkeypatch.setattr("sys.argv", ["forge", "execute-next"])
    main()
    exec_out = capsys.readouterr().out
    assert "Milestone 1 completed." in exec_out

    state_file = tmp_path / ".system" / "milestone_state.json"
    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "completed"
