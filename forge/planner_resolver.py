from __future__ import annotations

from forge.llm import StubLLMClient
from forge.planner import DeterministicPlanner, LLMPlanner, Planner
from forge.policy_config import (
    PlannerPolicy,
    load_planner_policy,
    merge_planner_policy,
)


def resolve_planner(mode_override: str | None = None) -> tuple[Planner | None, str | None]:
    """
    Resolve planner from repo policy + optional CLI mode override.
    Returns (planner, error_message).
    """
    policy, err = load_planner_policy()
    if err:
        return None, err
    effective: PlannerPolicy = merge_planner_policy(policy, mode_override=mode_override)
    if effective.mode == "deterministic":
        return DeterministicPlanner(), None
    if effective.mode == "llm":
        if effective.llm_client == "stub":
            return LLMPlanner(StubLLMClient()), None
        if not effective.llm_client:
            return None, (
                "LLM planner selected but not configured. "
                "Set forge-policy.json planner.llm_client to 'stub' (or supported client)."
            )
        return None, (
            f"Unsupported planner llm_client '{effective.llm_client}'. "
            "Currently supported: stub."
        )
    return None, f"Unsupported planner mode '{effective.mode}'."
