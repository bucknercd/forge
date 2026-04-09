from __future__ import annotations

import pytest

from forge.cli import main
from forge.milestone_status_md import (
    MilestoneStatusSyncError,
    milestone_section_ranges,
    sync_milestones_md_for_completed_prompt_task,
    update_milestones_md_for_task_completion,
)
from forge.paths import Paths
from forge.prompt_task_state import (
    PromptTask,
    PromptTaskState,
    complete_task,
    save_prompt_task_state,
)
from tests.test_prompt_workflow_transitions import _seed_prompt_tasks


def _milestone_body_two_tasks() -> str:
    return (
        "# Milestones\n\n"
        "## Milestone 1: Alpha\n"
        "- **Objective**: O\n"
        "- **Scope**: S\n"
        "- **Validation**: V\n"
        "\n"
        "Status: not started\n"
        "\n"
        "<!-- FORGE:STATUS START -->\n"
        "\n"
        "* [ ] First item\n"
        "* [ ] Second item\n"
        "\n"
        "<!-- FORGE:STATUS END -->\n"
        "\n"
        "## Milestone 2: Beta\n"
        "UNIQUE_UNTOUCHED_LINE\n"
        "- **Objective**: O2\n"
        "\n"
        "Status: not started\n"
        "\n"
        "<!-- FORGE:STATUS START -->\n"
        "\n"
        "* [ ] Beta only\n"
        "\n"
        "<!-- FORGE:STATUS END -->\n"
    )


def test_update_marks_one_checkbox_not_started_to_in_progress():
    md = _milestone_body_two_tasks()
    out = update_milestones_md_for_task_completion(
        md, milestone_id=1, milestone_task_id=1, task_title=""
    )
    assert "Status: in progress" in out
    assert "* [x] First item" in out
    assert "* [ ] Second item" in out


def test_update_second_checkbox_reaches_completed():
    md = _milestone_body_two_tasks()
    step1 = update_milestones_md_for_task_completion(
        md, milestone_id=1, milestone_task_id=1, task_title=""
    )
    step2 = update_milestones_md_for_task_completion(
        step1, milestone_id=1, milestone_task_id=2, task_title=""
    )
    assert "Status: completed" in step2
    assert "* [x] First item" in step2
    assert "* [x] Second item" in step2


def test_other_milestone_section_bytes_preserved():
    md = _milestone_body_two_tasks()
    before_lines = md.split("\n")
    ranges = milestone_section_ranges(before_lines)
    s2, e2 = ranges[1]
    second_before = "\n".join(before_lines[s2:e2])

    out = update_milestones_md_for_task_completion(
        md, milestone_id=1, milestone_task_id=1, task_title=""
    )
    after_lines = out.split("\n")
    second_after = "\n".join(after_lines[s2:e2])
    assert second_before == second_after


def test_sync_skips_when_section_has_no_managed_block(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.MILESTONES_FILE.write_text(
        "# Milestones\n\n## Milestone 1: X\n- **Objective**: O\n",
        encoding="utf-8",
    )
    before = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    sync_milestones_md_for_completed_prompt_task(
        milestone_id=1,
        milestone_task_id=1,
        task_title="t",
    )
    assert Paths.MILESTONES_FILE.read_text(encoding="utf-8") == before


def test_missing_managed_block_raises():
    bad = (
        "# Milestones\n\n## Milestone 1: X\n"
        "- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n\n"
        "Status: not started\n\n"
        "* [ ] Only a checkbox\n"
    )
    with pytest.raises(MilestoneStatusSyncError, match="managed status block"):
        update_milestones_md_for_task_completion(
            bad, milestone_id=1, milestone_task_id=1, task_title=""
        )


def test_milestone_out_of_range_raises():
    md = _milestone_body_two_tasks()
    with pytest.raises(MilestoneStatusSyncError, match="does not match"):
        update_milestones_md_for_task_completion(
            md, milestone_id=99, milestone_task_id=1, task_title=""
        )


def test_no_milestone_sections_raises():
    with pytest.raises(MilestoneStatusSyncError, match="No ## Milestone"):
        update_milestones_md_for_task_completion(
            "# Title\n\nNo milestone here.\n",
            milestone_id=1,
            milestone_task_id=1,
            task_title="",
        )


def test_stray_text_inside_managed_block_raises():
    md = (
        "# Milestones\n\n## Milestone 1: X\n"
        "- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n\n"
        "Status: not started\n\n"
        "<!-- FORGE:STATUS START -->\n\n"
        "* [ ] A\n"
        "oops not a checkbox\n"
        "<!-- FORGE:STATUS END -->\n"
    )
    with pytest.raises(MilestoneStatusSyncError, match="only blank lines"):
        update_milestones_md_for_task_completion(
            md, milestone_id=1, milestone_task_id=1, task_title=""
        )


def test_match_checkbox_by_title_when_task_id_none():
    md = (
        "# Milestones\n\n## Milestone 1: X\n"
        "- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n\n"
        "Status: not started\n\n"
        "<!-- FORGE:STATUS START -->\n\n"
        "- [ ] Alpha task\n"
        "- [ ] Beta task\n"
        "<!-- FORGE:STATUS END -->\n"
    )
    out = update_milestones_md_for_task_completion(
        md, milestone_id=1, milestone_task_id=None, task_title="Beta task"
    )
    assert "- [ ] Alpha task" in out
    assert "- [x] Beta task" in out
    assert "Status: in progress" in out


def test_cli_prompt_task_complete_updates_milestones(tmp_path, monkeypatch, capsys):
    _seed_prompt_tasks(tmp_path, monkeypatch)
    monkeypatch.setattr("sys.argv", ["forge", "prompt-task-complete", "--id", "1"])
    assert main() == 0
    capsys.readouterr()
    text = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    assert "Status: in progress" in text
    assert "* [x] Task one" in text
    assert "* [ ] Task two" in text


def test_complete_task_updates_milestone_md_by_task_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.MILESTONES_FILE.write_text(
        "# Milestones\n\n## Milestone 1: M\n"
        "- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n\n"
        "Status: not started\n\n"
        "<!-- FORGE:STATUS START -->\n\n"
        "* [ ] Checkbox A\n"
        "* [ ] Checkbox B\n\n"
        "<!-- FORGE:STATUS END -->\n",
        encoding="utf-8",
    )
    save_prompt_task_state(
        PromptTaskState(
            version=1,
            active_task_id=1,
            tasks=[
                PromptTask(
                    id=1,
                    title="title one",
                    objective="",
                    status="active",
                    milestone_id=1,
                    task_id=1,
                ),
                PromptTask(
                    id=2,
                    title="title two",
                    objective="",
                    status="pending",
                    milestone_id=1,
                    task_id=2,
                ),
            ],
        )
    )
    complete_task(1)
    md = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    assert "Status: in progress" in md
    assert "* [x] Checkbox A" in md
    assert "* [ ] Checkbox B" in md
