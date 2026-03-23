"""Synthesize reviewed plans from task JSON ``forge_actions`` (skip LLM planner when valid)."""

from __future__ import annotations

import json

import pytest

from forge.design_manager import MilestoneService
from forge.executor import Executor
from forge.llm import LLMClient
from forge.paths import Paths
from forge.planner import LLMPlanner
from forge.run_event_handlers import EventListCollector
from forge.run_events import RunEventBus, TASK_PLAN_SYNTHESIZED
from forge.task_service import Task, ensure_tasks_for_milestone, list_tasks, save_tasks
from tests.forge_test_project import compat_forge_block, configure_project
from tests.test_planner_abstraction import CapturingLLM, FakeLLM


class ExplodingLLM(LLMClient):
    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise AssertionError("LLMClient.generate should not be called for embedded task actions")


def test_preview_uses_embedded_forge_actions_without_calling_llm(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: T
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("EMB_OK")}
""",
    )
    ensure_tasks_for_milestone(1)
    preview = Executor.preview_milestone(
        1, planner=LLMPlanner(ExplodingLLM()), task_id=1
    )
    assert preview["ok"], preview.get("message")
    assert preview["planner_metadata"].get("plan_source") == "task_forge_actions"
    assert preview["planner_metadata"].get("plan_synthesis") == "embedded_task_actions"
    assert preview["planner_mode"] == "deterministic"


def test_empty_embedded_actions_uses_llm_planner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: L
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    ensure_tasks_for_milestone(1)
    tasks = list_tasks(1)
    assert len(tasks) == 1
    t0 = tasks[0]
    empty_task = Task(
        id=t0.id,
        milestone_id=t0.milestone_id,
        title=t0.title,
        objective=t0.objective,
        summary=t0.summary,
        depends_on=list(t0.depends_on),
        files_allowed=t0.files_allowed,
        validation=t0.validation,
        done_when=t0.done_when,
        status=t0.status,
        forge_actions=[],
        forge_validation=list(t0.forge_validation),
    )
    save_tasks(1, [empty_task])

    payload = {
        "actions": [
            "append_section requirements Overview | FROM_LLM",
            "mark_milestone_completed",
        ]
    }
    cap = CapturingLLM(json.dumps(payload))
    preview = Executor.preview_milestone(1, planner=LLMPlanner(cap), task_id=1)
    assert preview["ok"], preview.get("message")
    assert cap.last_prompt != ""
    assert preview["planner_metadata"].get("plan_source") != "task_forge_actions"


def test_invalid_embedded_forge_actions_fail_structured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: X
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("BAD")}
""",
    )
    ensure_tasks_for_milestone(1)
    tasks = list_tasks(1)
    t0 = tasks[0]
    bad = Task(
        id=t0.id,
        milestone_id=t0.milestone_id,
        title=t0.title,
        objective=t0.objective,
        summary=t0.summary,
        depends_on=list(t0.depends_on),
        files_allowed=t0.files_allowed,
        validation=t0.validation,
        done_when=t0.done_when,
        status=t0.status,
        forge_actions=["this is not a forge action line"],
        forge_validation=list(t0.forge_validation),
    )
    save_tasks(1, [bad])

    out = Executor.preview_milestone(1, planner=LLMPlanner(FakeLLM("{}")), task_id=1)
    assert out["ok"] is False
    assert out.get("failure_type") == "task_action_validation_error"
    assert out.get("task_id") == 1
    assert out.get("offending_action") == "this is not a forge action line"


def test_save_reviewed_plan_emits_task_plan_synthesized(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: E
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("EVT_OK")}
""",
    )
    ensure_tasks_for_milestone(1)
    collector = EventListCollector()
    bus = RunEventBus("emb_test", [collector])
    res = Executor.save_reviewed_plan_for_task(
        1, 1, planner=LLMPlanner(ExplodingLLM()), event_bus=bus
    )
    assert res["ok"], res.get("message")
    synth = [e for e in collector.events if e["type"] == TASK_PLAN_SYNTHESIZED]
    assert len(synth) == 1
    data = synth[0]["data"]
    assert data["milestone_id"] == 1
    assert data["task_id"] == 1
    assert int(data["action_count"]) >= 1
    assert data["reason"] == "embedded_forge_actions_present"
