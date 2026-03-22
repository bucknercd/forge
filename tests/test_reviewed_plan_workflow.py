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
    preview = Executor.save_reviewed_plan_for_task(1, 1)
    assert preview["ok"] is True
    assert preview.get("plan_id")
    assert preview["planner_metadata"]["mode"] == "deterministic"
    plan_id = preview["plan_id"]
    assert (Paths.SYSTEM_DIR / "reviewed_plans" / f"{plan_id}.json").exists()
    plan_payload = json.loads(
        (Paths.SYSTEM_DIR / "reviewed_plans" / f"{plan_id}.json").read_text(encoding="utf-8")
    )
    assert plan_payload["planner_metadata"]["mode"] == "deterministic"
    assert isinstance(plan_payload.get("warnings"), list)

    apply_res = Executor.apply_reviewed_plan(plan_id)
    assert apply_res["ok"] is True
    assert apply_res["planner_metadata"]["mode"] == "deterministic"
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
    preview = Executor.save_reviewed_plan_for_task(1, 1)
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
    preview = Executor.save_reviewed_plan_for_task(1, 1)
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
    assert "Milestones file changed" in res["message"] or "no longer matches" in res["message"]


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

    monkeypatch.setattr(
        "sys.argv", ["forge", "milestone-preview", "1", "--task", "1", "--save-plan", "--json"]
    )
    assert main() == 0
    preview_payload = json.loads(capsys.readouterr().out)
    assert preview_payload["ok"] is True
    assert "planner_metadata" in preview_payload
    assert "warnings" in preview_payload
    assert "review_enforcement" in preview_payload
    plan_id = preview_payload["plan_id"]

    monkeypatch.setattr("sys.argv", ["forge", "milestone-apply-plan", plan_id, "--json"])
    assert main() == 0
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["ok"] is True
    assert apply_payload["plan_id"] == plan_id
    assert "planner_metadata" in apply_payload
    assert "warnings" in apply_payload
    assert "review_enforcement" in apply_payload


def test_apply_reviewed_plan_with_validation_gate_fail(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Gate Validation Fail
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("GATE_VALID_FAIL")}
""",
    )
    preview = Executor.save_reviewed_plan_for_task(1, 1)
    plan_id = preview["plan_id"]

    # Break validation rule after review while keeping plan applyable.
    Paths.MILESTONES_FILE.write_text(
        """
# Milestones

## Milestone 1: Gate Validation Fail
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | GATE_VALID_FAIL
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements SOMETHING_ELSE
""",
        encoding="utf-8",
    )
    # Plan mismatch due to changed milestones hash would block earlier.
    # Re-save reviewed plan against updated milestones, then force validation failure via rule.
    preview2 = Executor.save_reviewed_plan_for_task(1, 1)
    plan_id2 = preview2["plan_id"]
    res = Executor.apply_reviewed_plan_with_gates(
        plan_id2, run_validation_gate=True, test_command=None
    )
    assert res["ok"] is False
    assert res["apply_ok"] is True
    assert res["gates_ok"] is False
    assert "milestone_validation=fail" in res["gate_summary"]
    result_artifact = Paths.SYSTEM_DIR / "results" / f"reviewed_apply_{plan_id2}.json"
    assert result_artifact.exists()
    payload = json.loads(result_artifact.read_text(encoding="utf-8"))
    assert payload["gates_ok"] is False
    assert payload["gate_results"]


def test_apply_reviewed_plan_with_test_gate_fail(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Gate Test Fail
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("GATE_TEST_FAIL")}
""",
    )
    preview = Executor.save_reviewed_plan_for_task(1, 1)
    plan_id = preview["plan_id"]
    res = Executor.apply_reviewed_plan_with_gates(
        plan_id,
        run_validation_gate=False,
        test_command="python -c \"import sys; sys.exit(3)\"",
    )
    assert res["ok"] is False
    assert res["apply_ok"] is True
    assert res["gates_ok"] is False
    assert "repo_test_command=fail" in res["gate_summary"]


def test_cli_apply_plan_json_includes_gate_results(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out
    (tmp_path / "docs" / "milestones.md").write_text(
        f"""
# Milestones

## Milestone 1: CLI Gate JSON
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("CLI_GATE_JSON")}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv", ["forge", "milestone-preview", "1", "--task", "1", "--save-plan", "--json"]
    )
    assert main() == 0
    plan_id = json.loads(capsys.readouterr().out)["plan_id"]

    monkeypatch.setattr(
        "sys.argv",
        [
            "forge",
            "milestone-apply-plan",
            plan_id,
            "--gate-test-cmd",
            "python -c \"print('ok')\"",
            "--json",
        ],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "milestone-apply-plan"
    assert payload["apply_ok"] is True
    assert "gate_results" in payload
