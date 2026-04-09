"""CLI help and deprecated aliases (task-first surface)."""

from __future__ import annotations

import json

import pytest

from forge.cli import ForgeCLI, main
from forge.paths import Paths

from tests.forge_test_project import compat_forge_block


def test_help_lists_task_first_commands_not_hidden_legacy(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "-h"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "init" in out
    assert "build" in out
    assert "status" in out
    assert "milestone-list" in out
    assert "milestone-show" in out
    assert "task-expand" in out
    assert "task-list" in out
    assert "task-complete" in out
    assert "prompt-generate" in out
    assert "prompt-task-sync" in out
    assert "prompt-task-start" in out
    assert "doctor" in out
    assert "logs" in out
    assert "prompt-task-list" not in out
    assert "prompt-task-activate" not in out
    assert "prompt-task-complete" not in out
    assert "vertical-slice" not in out
    assert "task-preview" not in out
    assert "task-apply-plan" not in out
    assert "run-next" not in out


def test_double_dash_help_is_curated(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "task-complete" in out
    assert "prompt-task-sync" in out
    assert "doctor" in out
    assert "logs" in out
    assert "vertical-slice" not in out


def test_help_command_default_is_curated_and_mentions_help_all(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "help"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "status" in out
    assert "prompt-task-sync" in out
    assert "doctor" in out
    assert "logs" in out
    assert "vertical-slice" not in out
    assert "Use `forge help all`" in out


def test_help_all_shows_full_list_including_hidden(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "help", "all"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "vertical-slice" in out
    assert "run-next" in out
    assert "task-apply-plan" in out
    assert "prompt-task-complete" in out


def test_hidden_command_vertical_slice_remains_callable(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "vertical-slice", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "vertical-slice" in out


def test_deprecated_execute_next_prints_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    Paths.refresh(tmp_path)
    Paths.MILESTONES_FILE.write_text(
        f"""
# Milestones

## Milestone 1: A
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("RN")}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ForgeCLI, "execute_next", staticmethod(lambda: None))
    monkeypatch.setattr("sys.argv", ["forge", "execute-next"])
    assert main() == 0
    cap = capsys.readouterr()
    assert "deprecated" in cap.err.lower()
    assert "run-next" in cap.err.lower()


def test_deprecated_milestone_preview_prints_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    Paths.refresh(tmp_path)
    Paths.MILESTONES_FILE.write_text(
        f"""
# Milestones

## Milestone 1: A
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("DEP")}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv", ["forge", "milestone-preview", "1", "--task", "1", "--json"]
    )
    assert main() == 0
    cap = capsys.readouterr()
    assert "deprecated" in cap.err.lower()
    assert "task-preview" in cap.err.lower()
    body = json.loads(cap.out)
    assert body.get("ok") is True
    assert body.get("command") == "task-preview"


def test_deprecated_milestone_execute_missing_id_prints_warning(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "milestone-execute"])
    assert main() == 2
    cap = capsys.readouterr()
    err = cap.err.lower()
    assert "deprecated" in err
    assert "milestone-execute" in err
    assert "run-next" in err


def test_deprecated_milestone_retry_missing_id_prints_warning(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["forge", "milestone-retry"])
    assert main() == 2
    cap = capsys.readouterr()
    err = cap.err.lower()
    assert "deprecated" in err
    assert "milestone-retry" in err
    assert "run-next" in err


def test_deprecated_milestone_execute_routes_with_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    Paths.refresh(tmp_path)
    called: list[int] = []

    def fake_execute(mid: int) -> None:
        called.append(mid)

    monkeypatch.setattr(ForgeCLI, "milestone_execute", staticmethod(fake_execute))
    monkeypatch.setattr("sys.argv", ["forge", "milestone-execute", "1"])
    assert main() == 0
    cap = capsys.readouterr()
    assert called == [1]
    assert "deprecated" in cap.err.lower()
    assert "legacy non-reviewed" in cap.err.lower()


def test_deprecated_milestone_retry_routes_with_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    Paths.refresh(tmp_path)
    called: list[int] = []

    def fake_retry(mid: int) -> None:
        called.append(mid)

    monkeypatch.setattr(ForgeCLI, "milestone_retry", staticmethod(fake_retry))
    monkeypatch.setattr("sys.argv", ["forge", "milestone-retry", "2"])
    assert main() == 0
    cap = capsys.readouterr()
    assert called == [2]
    assert "deprecated" in cap.err.lower()
    assert "legacy full-milestone retry" in cap.err.lower()
