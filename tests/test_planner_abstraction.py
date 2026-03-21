import json

import pytest

from forge.execution.plan import ExecutionPlanBuilder
from forge.design_manager import MilestoneService
from forge.executor import Executor
from forge.llm import LLMClient
from forge.paths import Paths
from forge.planner import DeterministicPlanner, LLMPlanner
from tests.forge_test_project import configure_project, forge_block


class FakeLLM(LLMClient):
    def __init__(self, output: str):
        self._output = output

    def generate(self, prompt: str) -> str:
        return self._output


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
    preview = Executor.save_reviewed_plan_for_milestone(1, planner=planner)
    assert preview["ok"] is True
    assert preview["planner_mode"] == "llm"
    plan_id = preview["plan_id"]

    applied = Executor.apply_reviewed_plan(plan_id)
    assert applied["ok"] is True
    assert applied["planner_mode"] == "llm"
    assert "LLM_FLOW_OK" in Paths.REQUIREMENTS_FILE.read_text(encoding="utf-8")
