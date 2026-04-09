from __future__ import annotations

import json

from forge.cli import main
from forge.paths import Paths
from forge.prompt_compiler import compile_task_prompt, generate_prompt_artifact
from forge.prompt_task_state import (
    PromptTask,
    PromptTaskState,
    save_prompt_task_state,
    task_state_path,
)
from forge.task_service import expand_milestone_to_tasks, list_tasks, save_tasks
from tests.forge_test_project import configure_project, forge_block


def _setup_project_with_tasks(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Prompt compiler slice
- **Objective**: Build prompt generation.
- **Scope**: Task-first workflow only.
- **Validation**: Prompt artifact exists.
{forge_block("PROMPT_COMPILER")}
""",
    )
    Paths.VISION_FILE.write_text("Vision: build a prompt-first workflow.", encoding="utf-8")
    res = expand_milestone_to_tasks(milestone_id=1, force=True)
    assert res.get("ok")


def test_prompt_artifact_written_under_system_prompts(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    out = generate_prompt_artifact(1, 1)
    assert out["prompt_path"].endswith(".system/prompts/m1-t1.prompt.txt")
    assert (tmp_path / ".system" / "prompts" / "m1-t1.prompt.txt").exists()


def test_prompt_includes_task_and_project_context(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    text = compile_task_prompt(1, 1)
    assert "## Read First" in text
    assert "From this repository, read before editing:" in text
    assert "- docs/vision.txt" in text
    assert "- docs/requirements.md" in text
    assert "- docs/architecture.md" in text
    assert "## Milestone Context" in text
    assert "Milestone ID: 1" in text
    assert "Prompt compiler slice" in text
    assert "## Selected Task" in text
    assert "Task ID: 1" in text
    assert "## Forge Workflow" in text
    assert "Forge remains the source of truth for workflow state transitions." in text
    assert "Task completion is explicit in Forge; do not assume completion." in text
    assert "Vision: build a prompt-first workflow." not in text


def test_prompt_includes_implementation_constraints(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    text = compile_task_prompt(1, 1)
    assert "## Implementation Constraints" in text
    assert "Solve only the task described above." in text
    assert "Keep the blast radius small." in text
    assert "Prefer editing existing files over adding new ones." in text
    assert "Do not introduce new abstractions unless required by this task." in text
    assert "Avoid speculative future-proofing." in text
    assert "Add only the minimum tests needed for the changed behavior." in text
    assert "Stop once the task requirements are satisfied." in text


def test_prompt_discourages_unrelated_refactors_and_architecture_changes(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    text = compile_task_prompt(1, 1)
    assert "Do not refactor unrelated code" in text
    assert "Do not redesign the architecture." in text


def test_prompt_includes_return_section(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    text = compile_task_prompt(1, 1)
    assert "## Return" in text
    assert "Return a concise summary of changes, tests run, and any assumptions." in text


def test_prompt_includes_preferred_files_when_hints_present(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    tasks = list_tasks(1)
    assert tasks
    tasks[0].files_allowed = "src/foo.py, tests/test_foo.py"
    save_tasks(1, tasks)
    text = compile_task_prompt(1, 1)
    assert "## Preferred Files" in text
    assert "guidance only" in text
    assert "src/foo.py" in text
    assert "tests/test_foo.py" in text


def test_prompt_generate_does_not_mutate_prompt_task_completion_state(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=1,
            tasks=[
                PromptTask(
                    id=1,
                    title="Task 1",
                    objective="Obj 1",
                    status="active",
                    milestone_id=1,
                    task_id=1,
                )
            ],
        )
    )
    before = task_state_path().read_text(encoding="utf-8")
    generate_prompt_artifact(1, 1)
    after = task_state_path().read_text(encoding="utf-8")
    assert before == after


def test_prompt_generate_does_not_mark_milestone_completed(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    state_path = tmp_path / ".system" / "milestone_state.json"
    if state_path.exists():
        before = state_path.read_text(encoding="utf-8")
    else:
        before = None
    generate_prompt_artifact(1, 1)
    if before is None:
        assert not state_path.exists()
    else:
        assert state_path.read_text(encoding="utf-8") == before


def test_invalid_task_fails_clearly(tmp_path, monkeypatch):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    try:
        generate_prompt_artifact(1, 999)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "No task 999 for milestone 1." in str(exc)


def test_cli_prompt_generate_text_mode(tmp_path, monkeypatch, capsys):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv", ["forge", "prompt-generate", "--milestone", "1", "--task", "1"]
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "Generated prompt for milestone 1 task 1." in out
    assert ".system/prompts/m1-t1.prompt.txt" in out
    assert "## Selected Task" in out


def test_cli_prompt_generate_json_mode(tmp_path, monkeypatch, capsys):
    _setup_project_with_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv",
        ["forge", "prompt-generate", "--milestone", "1", "--task", "1", "--json"],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is True
    assert payload.get("milestone_id") == 1
    assert payload.get("task_id") == 1
    assert payload.get("prompt_path", "").endswith(".system/prompts/m1-t1.prompt.txt")
    assert "## Milestone Context" in payload.get("prompt", "")
