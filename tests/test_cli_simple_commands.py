"""Tests for simplified CLI entry points (build, fix, start, doctor, logs)."""

from __future__ import annotations

import json

from forge.cli import ForgeCLI, main
from forge.llm import LLMClient
from forge.paths import Paths


def test_cli_build_routes_to_vertical_slice_demo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["forge", "build", "--json"])
    rc = main()
    assert rc in (0, 1)
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload.get("command") == "vertical-slice"
    assert "stages" in payload


def test_cli_fix_aliases_run_next(tmp_path, monkeypatch, capsys):
    """`forge fix` should dispatch to the same handler as run-next."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    called = {"n": 0}

    def fake_execute_next():
        called["n"] += 1
        print("executed-next-stub")

    monkeypatch.setattr(ForgeCLI, "execute_next", staticmethod(fake_execute_next))
    monkeypatch.setattr("sys.argv", ["forge", "fix"])
    Paths.refresh(tmp_path)
    main()
    assert called["n"] == 1


def test_cli_doctor_runs_without_full_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "doctor"])
    rc = main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Forge doctor" in out


def test_build_from_vision_stops_before_apply_and_only_prepares_planning_artifacts(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    capsys.readouterr()
    Paths.refresh(tmp_path)
    Paths.VISION_FILE.write_text("Build a tiny checker tool.", encoding="utf-8")

    class _DocsOnlyLLM(LLMClient):
        def generate(self, prompt: str) -> str:  # noqa: ARG002
            payload = {
                "requirements_md": "# Requirements\n\n## Overview\nChecker behavior.\n",
                "architecture_md": "# Architecture\n\n## Overview\nSingle module.\n",
                "milestones_md": (
                    "# Milestones\n\n"
                    "## Milestone 1: Plan checker\n"
                    "- **Objective**: Define the first implementation task.\n"
                    "- **Scope**: Planning artifacts only.\n"
                    "- **Validation**: Task file exists for milestone 1.\n"
                ),
            }
            return json.dumps(payload)

    monkeypatch.setattr(
        "forge.vertical_slice.resolve_docs_llm_client",
        lambda: (_DocsOnlyLLM(), None),
    )
    monkeypatch.setattr("sys.argv", ["forge", "build", "--from-vision", "--json"])
    assert main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out.get("ok") is True
    stages = out.get("stages") or []
    stage_names = [s.get("stage") for s in stages]
    assert "materialize_docs" in stage_names
    assert "task_prepare" in stage_names
    assert "preview_save_plan" not in stage_names
    assert "apply_plan" not in stage_names
    assert (tmp_path / "docs" / "requirements.md").exists()
    assert (tmp_path / "docs" / "architecture.md").exists()
    assert (tmp_path / "docs" / "milestones.md").exists()
    assert (tmp_path / ".system" / "tasks" / "m1.json").exists()
    assert not (tmp_path / "src" / "todo_cli.py").exists()
    state_path = tmp_path / ".system" / "milestone_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state.get("1", {}).get("status") != "completed"
