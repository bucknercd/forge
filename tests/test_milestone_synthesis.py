from __future__ import annotations

import json

from forge.cli import main
from forge.llm import LLMClient
from forge.milestone_synthesis import (
    accept_synthesized_milestones,
    load_synthesized_milestones,
    synthesize_milestones,
)
from forge.paths import Paths
from tests.forge_test_project import configure_project


class FakeLLM(LLMClient):
    def __init__(self, output: str):
        self.output = output

    @property
    def client_id(self) -> str:
        return "fake"

    def generate(self, prompt: str) -> str:
        return self.output


def _bootstrap(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Existing
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )


def test_synthesize_saves_reviewed_artifact_without_writing_milestones(tmp_path):
    _bootstrap(tmp_path)
    before = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    llm = FakeLLM(
        json.dumps(
            {
                "milestones": [
                    {
                        "title": "Add API requirements",
                        "objective": "Document API endpoints.",
                        "scope": "Update requirements.",
                        "validation": "API endpoint requirements are listed.",
                    }
                ]
            }
        )
    )
    payload = synthesize_milestones(llm, desired_count=3)
    assert payload["synthesis_id"]
    assert payload["kind"] == "milestone_synthesis"
    assert Paths.MILESTONES_FILE.read_text(encoding="utf-8") == before
    artifact = load_synthesized_milestones(payload["synthesis_id"])
    assert artifact is not None
    assert "milestones" in artifact
    assert artifact["planner_metadata"]["llm_client"] == "fake"
    assert "quality_warnings" in artifact


def test_synthesize_malformed_output_fails_clearly(tmp_path):
    _bootstrap(tmp_path)
    llm = FakeLLM('{"bad":"shape"}')
    try:
        _ = synthesize_milestones(llm, desired_count=2)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "milestones" in str(exc).lower()


def test_accept_synthesized_milestones_merges_safely(tmp_path):
    _bootstrap(tmp_path)
    llm = FakeLLM(
        json.dumps(
            {
                "milestones": [
                    {
                        "title": "Plan migration",
                        "objective": "Plan DB migration.",
                        "scope": "Architecture and risks.",
                        "validation": "Migration plan documented.",
                    }
                ]
            }
        )
    )
    payload = synthesize_milestones(llm, desired_count=1)
    res = accept_synthesized_milestones(payload["synthesis_id"])
    assert res["ok"] is True
    assert "quality_warnings" in res
    text = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
    assert "## Milestone 2: Plan migration" in text


def test_accept_synthesized_milestones_fails_when_stale(tmp_path):
    _bootstrap(tmp_path)
    llm = FakeLLM(
        json.dumps(
            {
                "milestones": [
                    {
                        "title": "Stale candidate",
                        "objective": "O",
                        "scope": "S",
                        "validation": "V",
                    }
                ]
            }
        )
    )
    payload = synthesize_milestones(llm, desired_count=1)
    Paths.MILESTONES_FILE.write_text(
        Paths.MILESTONES_FILE.read_text(encoding="utf-8") + "\n<!-- external change -->\n",
        encoding="utf-8",
    )
    res = accept_synthesized_milestones(payload["synthesis_id"])
    assert res["ok"] is False
    assert "changed since synthesis" in res["message"]


def test_cli_milestone_synthesize_and_accept_json(tmp_path, monkeypatch, capsys):
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
""",
        encoding="utf-8",
    )
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "forge.cli.synthesize_milestones",
        lambda _client, desired_count=3: {
            "kind": "milestone_synthesis",
            "synthesis_id": "abc123def456",
            "milestones": [
                {
                    "title": "Synth CLI",
                    "objective": "O",
                    "scope": "S",
                    "validation": "V",
                }
            ],
            "markdown_preview": "## Milestone 2: Synth CLI\n- **Objective**: O\n- **Scope**: S\n- **Validation**: V\n",
            "warnings": [],
            "quality_warnings": ["Milestone 1 has weak/generic objective text."],
            "planner_metadata": {"mode": "llm", "llm_client": "stub"},
            "source_hashes": {"milestones": "x"},
            "created_at": "now",
            "desired_count": desired_count,
        },
    )
    monkeypatch.setattr(
        "forge.cli.accept_synthesized_milestones",
        lambda synthesis_id: {
            "ok": True,
            "synthesis_id": synthesis_id,
            "accepted_count": 1,
            "message": "Accepted 1 synthesized milestone(s).",
        },
    )
    monkeypatch.setattr(
        "sys.argv", ["forge", "milestone-synthesize", "--count", "2", "--json"]
    )
    assert main() == 0
    synth_payload = json.loads(capsys.readouterr().out)
    assert synth_payload["ok"] is True
    assert synth_payload["synthesis_id"] == "abc123def456"
    assert synth_payload["quality_warnings"]

    monkeypatch.setattr(
        "sys.argv",
        ["forge", "milestone-synthesis-accept", "abc123def456", "--json"],
    )
    assert main() == 0
    accept_payload = json.loads(capsys.readouterr().out)
    assert accept_payload["ok"] is True


def test_quality_warnings_detect_vague_fields(tmp_path):
    _bootstrap(tmp_path)
    llm = FakeLLM(
        json.dumps(
            {
                "milestones": [
                    {
                        "title": "General improvements",
                        "objective": "Improve things",
                        "scope": "Update stuff",
                        "validation": "Looks good",
                    }
                ]
            }
        )
    )
    payload = synthesize_milestones(llm, desired_count=1)
    joined = " ".join(payload.get("quality_warnings", [])).lower()
    assert "weak/generic objective" in joined
    assert "weak/generic scope" in joined
    assert "weak validation text" in joined


def test_quality_warnings_detect_redundancy_against_existing(tmp_path):
    _bootstrap(tmp_path)
    llm = FakeLLM(
        json.dumps(
            {
                "milestones": [
                    {
                        "title": "Existing",
                        "objective": "O",
                        "scope": "Concrete scoped changes",
                        "validation": "file contains marker",
                    }
                ]
            }
        )
    )
    payload = synthesize_milestones(llm, desired_count=1)
    joined = " ".join(payload.get("quality_warnings", [])).lower()
    assert "redundant" in joined


def test_cli_human_show_surfaces_quality_warnings(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    assert main() == 0
    _ = capsys.readouterr().out
    monkeypatch.setattr(
        "forge.cli.load_synthesized_milestones",
        lambda _sid: {
            "synthesis_id": "abc",
            "markdown_preview": "## Milestone 2: Demo",
            "warnings": ["General warning"],
            "quality_warnings": ["Milestone 1 has weak/generic objective text."],
        },
    )
    monkeypatch.setattr("sys.argv", ["forge", "milestone-synthesis-show", "abc"])
    assert main() == 0
    out = capsys.readouterr().out
    assert "Warning: General warning" in out
    assert "Quality warning:" in out
