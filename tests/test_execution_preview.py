import json

from forge.cli import main
from forge.executor import Executor
from forge.paths import Paths
from tests.forge_test_project import configure_project, forge_block


def test_preview_milestone_has_no_side_effects(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Preview
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("PREVIEW_OK")}
""",
    )
    before_req = Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")
    before_milestones = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    before_history = Paths.RUN_HISTORY_FILE.read_text(encoding="utf-8")

    result = Executor.preview_milestone(1, task_id=1)
    assert result["ok"] is True
    assert result["actions_applied"]
    assert any(a.get("diff") for a in result["actions_applied"] if a["outcome"] == "changed")

    # No writes in dry run.
    assert Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8") == before_req
    assert Paths.MILESTONES_FILE.read_text(encoding="utf-8") == before_milestones
    assert Paths.RUN_HISTORY_FILE.read_text(encoding="utf-8") == before_history
    assert not (Paths.SYSTEM_DIR / "results" / "milestone_1.json").exists()
    assert not (Paths.SYSTEM_DIR / "milestone_state.json").exists()
    # Task-scoped preview auto-materializes `.system/tasks/m1.json` (no execution).
    assert (Paths.SYSTEM_DIR / "tasks" / "m1.json").exists()


def test_preview_next_selects_runnable_milestone(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: First
- **Objective**: O1
- **Scope**: S1
- **Validation**: V1
{forge_block("P1")}

## Milestone 2: Second
- **Depends On**: 1
- **Objective**: O2
- **Scope**: S2
- **Validation**: V2
{forge_block("P2")}
""",
    )
    result = Executor.preview_next()
    assert result["ok"] is True
    assert result["milestone_id"] == 1
    assert result["artifact_summary"]


def test_cli_milestone_preview_specific_and_next(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
        f"""
# Milestones

## Milestone 1: First
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("CLI_PREVIEW")}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["forge", "task-preview", "1", "--task", "1"])
    assert main() == 0
    out_specific = capsys.readouterr().out
    assert "Preview Task: milestone 1 task 1." in out_specific
    assert "Planned Actions:" in out_specific
    assert "diff:" in out_specific

    monkeypatch.setattr("sys.argv", ["forge", "task-preview"])
    assert main() == 0
    out_next = capsys.readouterr().out
    assert "Preview Task: milestone 1 task 1." in out_next

    # Command preview should not create execution artifacts/state.
    assert not (tmp_path / ".system" / "results" / "milestone_1.json").exists()
    state_file = tmp_path / ".system" / "milestone_state.json"
    assert (not state_file.exists()) or (state_file.read_text(encoding="utf-8").strip() == "")


def test_cli_milestone_preview_json_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out

    (tmp_path / "docs" / "milestones.md").write_text(
        f"""
# Milestones

## Milestone 1: First
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("CLI_PREVIEW_JSON")}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["forge", "task-preview", "1", "--task", "1", "--json"])
    assert main() == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["command"] == "task-preview"
    assert payload["ok"] is True
    assert payload["milestone_id"] == 1
    assert payload["task_id"] == 1
    assert payload["artifact_summary"]
    assert payload["targeted_artifacts"]
    assert payload["planned_actions"]
    assert payload["actions_applied"]
    assert "planner_metadata" in payload
    assert "warnings" in payload
    assert "summary_counts" in payload
    assert "changed" in payload["summary_counts"]

    # Still no side effects in json preview mode.
    assert not (tmp_path / ".system" / "results" / "milestone_1.json").exists()
