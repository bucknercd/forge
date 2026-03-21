from __future__ import annotations

import json
from dataclasses import dataclass

from forge.design_manager import Milestone
from forge.execution.models import ExecutionPlan
from forge.execution.parse import parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.llm import LLMClient


class Planner:
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(self, milestone: Milestone) -> ExecutionPlan:
        raise NotImplementedError


class DeterministicPlanner(Planner):
    mode = "deterministic"
    stable_for_recheck = True

    def build_plan(self, milestone: Milestone) -> ExecutionPlan:
        return ExecutionPlanBuilder.build(milestone)


@dataclass
class LLMPlanner(Planner):
    llm_client: LLMClient
    mode: str = "llm"
    stable_for_recheck: bool = False
    fallback_to_milestone_actions: bool = True

    def build_plan(self, milestone: Milestone) -> ExecutionPlan:
        prompt = (
            "Generate a Forge execution plan for this milestone.\n"
            "Return ONLY valid JSON object: {\"actions\": [\"...\"]}\n"
            "Allowed action formats:\n"
            "- append_section <target> <Section Heading> | <body>\n"
            "- replace_section <target> <Section Heading> | <body>\n"
            "- add_decision | <title> | <rationale>\n"
            "- mark_milestone_completed\n"
            "Allowed targets: requirements, architecture, decisions, milestones.\n\n"
            f"Milestone ID: {milestone.id}\n"
            f"Title: {milestone.title}\n"
            f"Objective: {milestone.objective}\n"
            f"Scope: {milestone.scope}\n"
            f"Validation: {milestone.validation}\n"
        )
        raw = self.llm_client.generate(prompt)
        try:
            parsed = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"LLM planner returned invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("LLM planner output must be a JSON object.")
        actions_raw = parsed.get("actions")
        if not isinstance(actions_raw, list):
            if self.fallback_to_milestone_actions and milestone.forge_actions:
                actions_raw = list(milestone.forge_actions)
            else:
                raise ValueError("LLM planner output must include an 'actions' array.")

        actions = []
        for idx, item in enumerate(actions_raw, start=1):
            if not isinstance(item, str):
                raise ValueError(f"LLM planner action {idx} must be a string.")
            try:
                actions.append(parse_forge_action_line(item, milestone))
            except ValueError as exc:
                raise ValueError(f"LLM planner action {idx} invalid: {exc}") from exc
        return ExecutionPlan(milestone_id=milestone.id, actions=actions)
