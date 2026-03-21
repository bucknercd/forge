"""
Resolve LLMClient from planner policy (separate from Executor internals).
"""

from __future__ import annotations

from forge.llm import LLMClient, StubLLMClient
from forge.llm_openai import OpenAIChatClient, openai_api_key_from_env
from forge.policy_config import PlannerPolicy

SUPPORTED_LLM_CLIENTS = frozenset({"stub", "openai"})


def resolve_llm_client_from_policy(policy: PlannerPolicy) -> tuple[LLMClient | None, str | None]:
    """
    Build an LLMClient for LLM planner mode from repo policy.
    Returns (client, error_message). Secrets are never read from policy files.
    """
    client_id = policy.llm_client
    if not client_id:
        return None, (
            "LLM planner selected but not configured. "
            "Set forge-policy.json planner.llm_client to 'stub' (offline) or 'openai' "
            "(requires FORGE_OPENAI_API_KEY or OPENAI_API_KEY)."
        )
    if client_id not in SUPPORTED_LLM_CLIENTS:
        return None, (
            f"Unsupported planner.llm_client '{client_id}'. "
            f"Supported values: {', '.join(sorted(SUPPORTED_LLM_CLIENTS))}."
        )
    if client_id == "stub":
        return StubLLMClient(), None
    if client_id == "openai":
        if not openai_api_key_from_env():
            return None, (
                "LLM planner with llm_client 'openai' requires an API key. "
                "Set FORGE_OPENAI_API_KEY or OPENAI_API_KEY in the environment "
                "(do not put API keys in forge-policy.json)."
            )
        return OpenAIChatClient(model=policy.llm_model), None
    return None, f"Unsupported planner.llm_client '{client_id}'."
