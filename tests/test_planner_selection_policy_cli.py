import json

from forge.cli import main


def _bootstrap(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out
    (tmp_path / "docs" / "milestones.md").write_text(
        """
# Milestones

## Milestone 1: Planner Select
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | PLAN_SEL
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements PLAN_SEL
""",
        encoding="utf-8",
    )


def test_no_planner_config_defaults_to_deterministic(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr("sys.argv", ["forge", "milestone-preview", "1", "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["planner_mode"] == "deterministic"


def test_repo_default_planner_mode_llm(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-preview", "1", "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["planner_mode"] == "llm"


def test_cli_override_planner_mode(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv", ["forge", "milestone-preview", "1", "--planner", "deterministic", "--json"]
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["planner_mode"] == "deterministic"


def test_llm_planner_selected_but_not_configured_fails_clearly(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr("sys.argv", ["forge", "milestone-preview", "1", "--planner", "llm", "--json"])
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "LLM planner selected but not configured" in payload["message"]


def test_save_plan_json_includes_planner_mode(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(
        "sys.argv", ["forge", "milestone-preview", "1", "--save-plan", "--json"]
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["planner_mode"] == "deterministic"
    assert payload["plan_id"]


def test_cli_human_preview_shows_llm_provenance_warning(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-preview", "1"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Planner: llm (stub)" in out
    assert "Warning:" in out
