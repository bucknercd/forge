import json

from forge.cli import main


def _init_and_write_milestone(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out
    (tmp_path / "docs" / "milestones.md").write_text(
        """
# Milestones

## Milestone 1: Policy Defaults
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | POLICY_OK
- **Forge Validation**:
  - file_contains requirements POLICY_OK
""",
        encoding="utf-8",
    )


def _save_plan_id(monkeypatch, capsys) -> str:
    monkeypatch.setattr(
        "sys.argv",
        ["forge", "task-preview", "1", "--task", "1", "--save-plan", "--json"],
    )
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    return preview["plan_id"]


def test_no_config_present_uses_existing_behavior(tmp_path, monkeypatch, capsys):
    _init_and_write_milestone(tmp_path, monkeypatch, capsys)
    plan_id = _save_plan_id(monkeypatch, capsys)

    monkeypatch.setattr("sys.argv", ["forge", "task-apply-plan", plan_id, "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["policy"]["run_validation_gate"] is False
    assert payload["policy"]["test_command"] is None


def test_valid_config_defaults_are_applied(tmp_path, monkeypatch, capsys):
    _init_and_write_milestone(tmp_path, monkeypatch, capsys)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps(
            {
                "reviewed_plan_apply": {
                    "run_validation_gate": True,
                    "test_command": "python -c \"print('ok')\"",
                    "test_timeout_seconds": 45,
                    "test_output_max_chars": 222,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    plan_id = _save_plan_id(monkeypatch, capsys)

    monkeypatch.setattr("sys.argv", ["forge", "task-apply-plan", plan_id, "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["policy"]["run_validation_gate"] is True
    assert payload["policy"]["test_command"] == "python -c \"print('ok')\""
    assert payload["policy"]["test_timeout_seconds"] == 45
    assert payload["policy"]["test_output_max_chars"] == 222
    assert payload["gate_results"]


def test_cli_flags_override_config_defaults(tmp_path, monkeypatch, capsys):
    _init_and_write_milestone(tmp_path, monkeypatch, capsys)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps(
            {
                "reviewed_plan_apply": {
                    "run_validation_gate": True,
                    "test_command": "python -c \"import sys; sys.exit(9)\"",
                },
                "task_execution": {"artifact_test_generation": False},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    plan_id = _save_plan_id(monkeypatch, capsys)

    monkeypatch.setattr(
        "sys.argv",
        [
            "forge",
            "task-apply-plan",
            plan_id,
            "--no-gate-validate",
            "--no-gate-test-cmd",
            "--json",
        ],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["policy"]["run_validation_gate"] is False
    assert payload["policy"]["test_command"] is None
    assert payload["gate_results"] == []


def test_invalid_config_reports_actionable_error(tmp_path, monkeypatch, capsys):
    _init_and_write_milestone(tmp_path, monkeypatch, capsys)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"reviewed_plan_apply": {"run_validation_gate": "yes"}}),
        encoding="utf-8",
    )
    plan_id = _save_plan_id(monkeypatch, capsys)

    monkeypatch.setattr("sys.argv", ["forge", "task-apply-plan", plan_id, "--json"])
    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "Invalid policy file" in payload["message"]
