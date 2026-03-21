import json

from forge.cli import main
from forge.executor import Executor
from forge.paths import Paths
from tests.forge_test_project import configure_project, forge_block


def test_preview_save_plan_and_apply_success(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Reviewed Flow
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("REVIEWED_OK")}
""",
    )
    preview = Executor.save_reviewed_plan_for_milestone(1)
    assert preview["ok"] is True
    assert preview.get("plan_id")
    plan_id = preview["plan_id"]
    assert (Paths.SYSTEM_DIR / "reviewed_plans" / f"{plan_id}.json").exists()

    apply_res = Executor.apply_reviewed_plan(plan_id)
    assert apply_res["ok"] is True
    assert "REVIEWED_OK" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")


def test_apply_reviewed_plan_fails_when_artifact_changed(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Stale Artifact
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("STALE")}
""",
    )
    preview = Executor.save_reviewed_plan_for_milestone(1)
    plan_id = preview["plan_id"]
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n\n## Overview\n\nchanged externally\n", encoding="utf-8")
    res = Executor.apply_reviewed_plan(plan_id)
    assert res["ok"] is False
    assert "Target artifact changed since review" in res["message"]


def test_apply_reviewed_plan_fails_when_milestone_definition_changed(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Mismatch
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("OLD")}
""",
    )
    preview = Executor.save_reviewed_plan_for_milestone(1)
    plan_id = preview["plan_id"]
    Paths.MILESTONES_FILE.write_text(
        f"""
# Milestones

## Milestone 1: Mismatch
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("NEW")}
""",
        encoding="utf-8",
    )
    res = Executor.apply_reviewed_plan(plan_id)
    assert res["ok"] is False
    assert "no longer matches current milestone definition" in res["message"]


def test_cli_reviewed_plan_json_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out
    (tmp_path / "docs" / "milestones.md").write_text(
        f"""
# Milestones

## Milestone 1: CLI Reviewed
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("CLI_REVIEWED")}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("sys.argv", ["forge", "milestone-preview", "1", "--save-plan", "--json"])
    assert main() == 0
    preview_payload = json.loads(capsys.readouterr().out)
    assert preview_payload["ok"] is True
    plan_id = preview_payload["plan_id"]

    monkeypatch.setattr("sys.argv", ["forge", "milestone-apply-plan", plan_id, "--json"])
    assert main() == 0
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["ok"] is True
    assert apply_payload["plan_id"] == plan_id
