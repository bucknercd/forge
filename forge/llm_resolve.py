"""
Resolve LLMClient from planner policy (separate from Executor internals).
"""

from __future__ import annotations

from forge.llm import LLMClient, StubLLMClient
from forge.llm_anthropic import AnthropicMessagesClient, anthropic_api_key_from_env
from forge.llm_openai import OpenAIChatClient, openai_api_key_from_env
from forge.policy_config import LLM_CLIENT_IDS, PlannerPolicy

SUPPORTED_LLM_CLIENTS = LLM_CLIENT_IDS


def resolve_llm_client_from_policy(policy: PlannerPolicy) -> tuple[LLMClient | None, str | None]:
    """
    Build an LLMClient for LLM planner mode from repo policy.
    Returns (client, error_message). Secrets are never read from policy files.
    """
    client_id = policy.llm_client
    if not client_id:
        return None, (
            "LLM planner selected but not configured. "
            "Set forge-policy.json planner.llm_client to 'stub' (offline), 'openai' "
            "(FORGE_OPENAI_API_KEY or OPENAI_API_KEY), or 'anthropic' "
            "(FORGE_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY)."
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
    if client_id == "anthropic":
        if not anthropic_api_key_from_env():
            return None, (
                "LLM planner with llm_client 'anthropic' requires an API key. "
                "Set FORGE_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY in the environment "
                "(do not put API keys in forge-policy.json)."
            )
        return AnthropicMessagesClient(model=policy.llm_model), None
    return None, f"Unsupported planner.llm_client '{client_id}'."
