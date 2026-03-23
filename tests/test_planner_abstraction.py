import json

import pytest

from forge.execution.plan import ExecutionPlanBuilder
from forge.design_manager import MilestoneService
from forge.executor import Executor
from forge.llm import LLMClient
from forge.paths import Paths
from forge.planner import DeterministicPlanner, LLMPlanner
from forge.task_service import Task, ensure_tasks_for_milestone, list_tasks, save_tasks
from tests.forge_test_project import compat_forge_block, configure_project, forge_block


class FakeLLM(LLMClient):
    def __init__(self, output: str):
        self._output = output

    def generate(self, prompt: str) -> str:
        return self._output


class CapturingLLM(LLMClient):
    def __init__(self, output: str):
        self._output = output
        self.last_prompt = ""

    @property
    def client_id(self) -> str:
        return "capture"

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._output


class SequenceLLM(LLMClient):
    def __init__(self, outputs: list[str]):
        self._outputs = list(outputs)
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        out = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        return out


def test_deterministic_planner_matches_existing_builder(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Deterministic
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("DET_OK")}
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    expected = ExecutionPlanBuilder.build(milestone).to_serializable()
    actual = DeterministicPlanner().build_plan(milestone).to_serializable()
    assert expected == actual


def test_llm_planner_builds_valid_execution_plan(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: LLM Plan
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    llm = FakeLLM(
        json.dumps(
            {
                "actions": [
                    "append_section requirements Overview | LLM_OK",
                    "mark_milestone_completed",
                ]
            }
        )
    )
    plan = LLMPlanner(llm).build_plan(milestone)
    assert plan.milestone_id == 1
    assert len(plan.actions) == 2


def test_llm_planner_prompt_includes_repo_context(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: LLM Context
- **Objective**: Capture context
- **Scope**: Use artifacts
- **Validation**: Must parse
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    llm = CapturingLLM(
        json.dumps(
            {
                "actions": [
                    "append_section requirements Overview | CONTEXT_OK",
                    "mark_milestone_completed",
                ]
            }
        )
    )
    _plan = LLMPlanner(llm).build_plan(milestone)
    prompt = llm.last_prompt
    assert "Repository context excerpts" in prompt
    assert "=== requirements.md ===" in prompt
    assert "Base content." in prompt
    assert "Milestone:" in prompt
    assert "Capture context" in prompt


def test_llm_planner_prompt_includes_behavioral_depth_guidance_and_context(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Behavioral Context
- **Objective**: Parse logs and count repeated ERROR messages.
- **Scope**: Implement core parser.
- **Validation**: Top 5 aggregated errors are returned.
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    milestone.scope = (
        "Task slice for parser.\n\n"
        "Parent milestone context:\n"
        "Ignore INFO/DEBUG, aggregate ERROR, and produce top 5."
    )
    llm = CapturingLLM(json.dumps({"actions": ["mark_milestone_completed"]}))
    _plan = LLMPlanner(llm).build_plan(milestone)
    prompt = llm.last_prompt
    assert "Behavioral depth requirements" in prompt
    assert "Detected behavior signals:" in prompt
    assert "Parent milestone context" in prompt
    assert "counting/aggregation/grouping/sorting" in prompt


def test_llm_planner_invalid_output_fails_clearly(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: LLM Bad
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    planner = LLMPlanner(FakeLLM(json.dumps({"actions": ["append_section badtarget X | Y"]})))
    with pytest.raises(ValueError) as exc:
        planner.build_plan(milestone)
    assert "LLM planner action 1 invalid" in str(exc.value)


def test_llm_planner_missing_actions_fails_without_fallback(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: LLM Missing Actions
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    planner = LLMPlanner(FakeLLM(json.dumps({"summary": "not a plan"})), fallback_to_milestone_actions=False)
    with pytest.raises(ValueError) as exc:
        planner.build_plan(milestone)
    assert "actions" in str(exc.value).lower()


def test_llm_generated_plan_flows_through_reviewed_save_and_apply(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: LLM Flow
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    planner = LLMPlanner(
        FakeLLM(
            json.dumps(
                {
                    "actions": [
                        "append_section requirements Overview | LLM_FLOW_OK",
                        "mark_milestone_completed",
                    ]
                }
            )
        )
    )
    preview = Executor.save_reviewed_plan_for_task(1, 1, planner=planner)
    assert preview["ok"] is True
    assert preview["planner_mode"] == "llm"
    assert preview["planner_metadata"]["is_nondeterministic"] is True
    assert preview["planner_metadata"]["llm_client"] == "unknown"
    assert preview["warnings"]
    plan_id = preview["plan_id"]

    applied = Executor.apply_reviewed_plan(plan_id)
    assert applied["ok"] is True
    assert applied["planner_mode"] == "llm"
    assert applied["planner_metadata"]["is_nondeterministic"] is True
    assert applied["warnings"]
    assert "LLM_FLOW_OK" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")


def test_llm_preview_warns_for_suspicious_duplicate_heavy_plan(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: LLM Suspicious
- **Objective**: O
- **Scope**: S
- **Validation**: V
{compat_forge_block("DUPBASE")}
""",
    )
    ensure_tasks_for_milestone(1)
    tasks = list_tasks(1)
    assert len(tasks) == 1
    t0 = tasks[0]
    save_tasks(
        1,
        [
            Task(
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
        ],
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    many = ["append_section requirements Overview | DUP"] * 13 + ["mark_milestone_completed"]
    planner = LLMPlanner(FakeLLM(json.dumps({"actions": many})))
    preview = Executor.preview_milestone(1, planner=planner, task_id=1)
    assert preview["ok"] is True
    text = " ".join(preview.get("warnings", []))
    assert "non-deterministic" in text
    assert "high action count" in text
    assert "duplicate" in text


def test_llm_planner_retries_on_malformed_insert_after_separator(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Retry malformed bounded edit
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    bad = json.dumps(
        {
            "actions": [
                "write_file src/log_parser.py | def read_log_file(path):\\n    return []\\n",
                "insert_after_in_file tests/test_log_parser.py | def test_read_log_file(): pass",
                "mark_milestone_completed",
            ]
        }
    )
    good = json.dumps(
        {
            "actions": [
                "write_file src/log_parser.py | def read_log_file(path):\\n    return []\\n",
                "write_file tests/test_log_parser.py | def test_read_log_file():\\n    assert read_log_file('x') == []\\n",
                "mark_milestone_completed",
            ]
        }
    )
    llm = SequenceLLM([bad, good])
    planner = LLMPlanner(llm, fallback_to_milestone_actions=False)
    plan = planner.build_plan(milestone)
    ser = plan.to_serializable()
    assert len(ser["actions"]) == 3
    assert ser["actions"][1]["type"] == "write_file"
    assert llm.calls == 2
    assert any("RETRY REQUIRED" in p for p in llm.prompts[1:])


def test_llm_planner_prompt_includes_python_profile_guidance(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Python profile
- **Objective**: Build Python CLI with pytest
- **Scope**: src/ and tests/
- **Validation**: pytest -q
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    llm = CapturingLLM(json.dumps({"actions": ["write_file src/app.py | def main():\\n    return 0\\n"]}))
    _ = LLMPlanner(llm, fallback_to_milestone_actions=False).build_plan(milestone)
    prompt = llm.last_prompt.lower()
    assert "detected project profile: python" in prompt
    assert "avoid relative imports such as from ..src" in prompt


def test_llm_planner_prompt_includes_go_profile_guidance(tmp_path):
    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Go profile
- **Objective**: Build golang service
- **Scope**: cmd/main.go and *_test.go
- **Validation**: go test ./...
""",
    )
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None
    llm = CapturingLLM(json.dumps({"actions": ["write_file main.go | package main\\nfunc main(){}\\n"]}))
    _ = LLMPlanner(llm, fallback_to_milestone_actions=False).build_plan(milestone)
    prompt = llm.last_prompt.lower()
    assert "detected project profile: go" in prompt
    assert "go test" in prompt
    assert "from ..src" not in prompt
