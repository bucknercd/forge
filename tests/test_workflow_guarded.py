from __future__ import annotations

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

## Milestone 1: Existing
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | WF_OK
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements WF_OK
""",
        encoding="utf-8",
    )


def test_workflow_guarded_json_stages_happy_path(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(
        "forge.cli.synthesize_milestones",
        lambda _client, desired_count=3: {
            "kind": "milestone_synthesis",
            "synthesis_id": "s123",
            "milestones": [
                {"title": "T", "objective": "O", "scope": "S", "validation": "V"}
            ],
            "warnings": [],
            "quality_warnings": [],
            "markdown_preview": "## Milestone 2: T\n- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n",
        },
    )
    monkeypatch.setattr(
        "forge.cli.accept_synthesized_milestones",
        lambda sid: {"ok": True, "synthesis_id": sid, "message": "accepted"},
    )
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "forge",
            "workflow-guarded",
            "--synthesize",
            "--accept-synthesized",
            "--milestone-id",
            "1",
            "--planner",
            "deterministic",
            "--apply-plan",
            "--json",
        ],
    )
    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "workflow-guarded"
    assert payload["ok"] is True
    assert len(payload["stages"]) == 4
    assert [s["stage"] for s in payload["stages"]] == [
        "synthesize",
        "accept_synthesized",
        "preview_save_plan",
        "apply_plan",
    ]


def test_workflow_guarded_fails_early_and_reports_stage(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(
        "sys.argv",
        ["forge", "workflow-guarded", "--accept-synthesized", "--json"],
    )
    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["stages"][0]["stage"] == "accept_synthesized"
    assert "No synthesis artifact ID available" in payload["stages"][0]["message"]


def test_workflow_guarded_human_output_lists_stages(tmp_path, monkeypatch, capsys):
    _bootstrap(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(
        "sys.argv", ["forge", "workflow-guarded", "--milestone-id", "1", "--planner", "deterministic"]
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "Guarded workflow:" in out
    assert "[OK] preview_save_plan" in out
