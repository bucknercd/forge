from __future__ import annotations

from forge.llm_resolve import resolve_llm_client_from_policy
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
        client, llm_err = resolve_llm_client_from_policy(effective)
        if llm_err:
            return None, llm_err
        assert client is not None
        return LLMPlanner(client), None
    return None, f"Unsupported planner mode '{effective.mode}'."
