"""Vertical-slice LLM bundle JSON extraction, retry, and raw artifact persistence."""

from __future__ import annotations

import json

import pytest

from forge.llm import LLMClient
from forge.paths import Paths
from forge.run_event_handlers import EventListCollector, JsonlRunLogHandler
from forge.run_events import RunEventBus
from forge.vertical_slice import generate_bundle_from_llm, run_vertical_slice
from forge.vertical_slice_json import (
    JsonExtractFailure,
    VerticalSliceLlmJsonError,
    extract_vertical_slice_json_inner,
    extract_vertical_slice_json_text,
    parse_vertical_slice_bundle_dict,
    write_llm_bundle_raw_artifact,
)


def _good_milestones_md() -> str:
    return """# Milestones

## Milestone 1: Logcheck

- **Objective**: Implement logcheck CLI for syslog review.
- **Scope**: examples/ only.
- **Validation**: File exists.

- **Forge Actions**:
  - write_file examples/logcheck.py | x\\n
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains examples/logcheck.py x
"""


def _idea_bundle_dict() -> dict:
    return {
        "vision": "logcheck vision",
        "requirements_md": "# Requirements\n\nLogcheck.\n",
        "architecture_md": "# Architecture\n\nexamples/logcheck.py\n",
        "milestones_md": _good_milestones_md(),
    }


def test_extract_direct_json():
    d = _idea_bundle_dict()
    raw = json.dumps(d)
    text, kind = extract_vertical_slice_json_text(raw)
    assert kind == "direct"
    assert json.loads(text) == d


def test_extract_json_markdown_fence():
    d = _idea_bundle_dict()
    raw = "```json\n" + json.dumps(d) + "\n```"
    text, kind = extract_vertical_slice_json_text(raw)
    assert kind == "markdown_fenced"
    assert json.loads(text)["vision"] == "logcheck vision"


def test_extract_prose_before_json():
    d = _idea_bundle_dict()
    raw = "Here is the bundle you asked for:\n" + json.dumps(d) + "\nThanks."
    text, kind = extract_vertical_slice_json_text(raw)
    assert kind == "balanced_object"
    assert json.loads(text)["milestones_md"]


def test_parse_vertical_slice_bundle_dict_requires_keys():
    d = {"vision": "v"}
    with pytest.raises(ValueError, match="missing keys"):
        parse_vertical_slice_bundle_dict(
            json.dumps(d), required_keys=("vision", "milestones_md")
        )


def test_balanced_extract_allows_apostrophe_inside_json_string():
    """Regression: old balancer treated ' as string delimiter and broke on it's."""
    raw = (
        'Sure.\n{"vision": "v", "requirements_md": "x", "architecture_md": "y", '
        '"milestones_md": "it\'s ok"}\n'
    )
    text, kind = extract_vertical_slice_json_text(raw)
    assert kind == "balanced_object"
    assert json.loads(text)["milestones_md"] == "it's ok"


def test_two_top_level_json_objects_is_ambiguous():
    raw = '{"a":1}{"b":2}'
    with pytest.raises(JsonExtractFailure, match="ambiguous"):
        extract_vertical_slice_json_inner(raw)


def test_truncated_json_no_valid_candidate():
    raw = '{"vision": "v", "requirements_md": "'
    with pytest.raises(JsonExtractFailure):
        extract_vertical_slice_json_inner(raw)


def test_invalid_json_not_accepted_as_candidate():
    """Trailing comma etc. never becomes a candidate (must json.loads as object)."""
    raw = '```json\n{"vision": 1,}\n```'  # invalid strict JSON
    with pytest.raises(JsonExtractFailure):
        extract_vertical_slice_json_inner(raw)


def test_fenced_json_with_leading_prose_succeeds_single_llm_call(tmp_path, monkeypatch):
    """One response: prose + ```json fence + trailing prose — still extracts unambiguously."""
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    good = json.dumps(_idea_bundle_dict())
    client = _SeqLLM(
        [
            "Here is the JSON:\n```json\n" + good + "\n```\nHope this helps.",
        ]
    )
    bundle = generate_bundle_from_llm(
        "Build logcheck tool for syslog parsing",
        client,
        bundle_llm_artifact_dir=tmp_path / "art",
    )
    assert client._i == 1
    assert "logcheck" in bundle.milestones_md.lower()


def test_integration_invalid_then_fenced_valid_bundle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    good = json.dumps(_idea_bundle_dict())
    client = _SeqLLM(
        [
            "preamble only { broken",
            "Here is the JSON:\n```json\n" + good + "\n```\nHope this helps.",
        ]
    )
    bundle = generate_bundle_from_llm(
        "Build logcheck tool for syslog parsing",
        client,
        bundle_llm_artifact_dir=tmp_path / "art",
    )
    assert client._i == 2
    assert "logcheck" in bundle.milestones_md.lower()


class _SeqLLM(LLMClient):
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs
        self._i = 0

    def generate(self, prompt: str) -> str:
        o = self._outputs[self._i]
        self._i += 1
        return o

    @property
    def client_id(self) -> str:
        return "seq"


def test_json_invalid_then_valid_succeeds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    good = json.dumps(_idea_bundle_dict())
    client = _SeqLLM(
        [
            "preamble only { broken",
            good,
        ]
    )
    bundle = generate_bundle_from_llm(
        "Build logcheck tool for syslog parsing",
        client,
        bundle_llm_artifact_dir=tmp_path / "art",
    )
    assert client._i == 2
    assert "logcheck" in bundle.milestones_md.lower()
    p1 = tmp_path / "art" / "llm_bundle_raw_01.txt"
    p2 = tmp_path / "art" / "llm_bundle_raw_02.txt"
    assert p1.is_file()
    assert p2.is_file()


def test_json_invalid_twice_raises_with_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    client = _SeqLLM(["not json {", "still not {"])
    art = tmp_path / "art"
    with pytest.raises(VerticalSliceLlmJsonError) as ei:
        generate_bundle_from_llm(
            "Build logcheck tool for syslog parsing",
            client,
            bundle_llm_artifact_dir=art,
        )
    assert len(ei.value.artifact_paths) == 2
    assert (art / "llm_bundle_raw_01.txt").is_file()
    assert (art / "llm_bundle_raw_02.txt").is_file()
    assert "llm_bundle_raw" in ei.value.artifact_paths[0]


def test_write_llm_bundle_raw_artifact_none_dir():
    assert write_llm_bundle_raw_artifact(None, sequence=1, raw="x") is None


def test_run_vertical_slice_json_failure_records_paths_in_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["forge", "init"])
    from forge.cli import main

    assert main() == 0
    Paths.refresh(tmp_path)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "stub"}}, indent=2),
        encoding="utf-8",
    )

    class _Bad(LLMClient):
        @property
        def client_id(self) -> str:
            return "bad"

        def generate(self, prompt: str) -> str:
            return "Expecting ':' delimiter: not valid json {"

    monkeypatch.setattr(
        "forge.vertical_slice.resolve_docs_llm_client",
        lambda: (_Bad(), None),
    )

    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    events_path = run_dir / "events.jsonl"
    collector = EventListCollector()
    bus = RunEventBus("testrun12", [JsonlRunLogHandler(events_path), collector])

    out = run_vertical_slice(
        demo=False,
        idea="Build logcheck for syslog",
        fixed_vision=None,
        milestone_id=1,
        planner_mode="deterministic",
        gate_validate=True,
        gate_test_cmd=None,
        disable_gate_test_cmd=True,
        gate_test_timeout_seconds=None,
        gate_test_output_max_chars=None,
        event_bus=bus,
        llm_bundle_artifact_dir=run_dir,
    )
    assert out["ok"] is False
    bad_stages = [s for s in out["stages"] if s.get("stage") == "llm_generation" and not s.get("ok")]
    assert bad_stages
    assert bad_stages[-1].get("json_parse_failed") is True
    paths = bad_stages[-1].get("llm_bundle_raw_paths") or []
    assert len(paths) == 2
    assert all("llm_bundle_raw_" in p for p in paths)

    phase_ev = [
        e
        for e in collector.events
        if e.get("type") == "phase_completed"
        and (e.get("data") or {}).get("phase") == "llm_generation"
        and (e.get("data") or {}).get("json_parse_failed")
    ]
    assert phase_ev
    ev_paths = (phase_ev[-1].get("data") or {}).get("llm_bundle_raw_paths") or []
    assert len(ev_paths) == 2
