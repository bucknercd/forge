"""LLM provider resolution, OpenAI client behavior, and planner integration (mocked HTTP)."""

import json

import pytest

from forge.llm import StubLLMClient
from forge.llm_openai import OpenAIChatClient, parse_chat_completions_response
from forge.llm_resolve import resolve_llm_client_from_policy
from forge.planner import LLMPlanner
from forge.policy_config import PlannerPolicy
from tests.forge_test_project import configure_project


def test_stub_client_path_via_resolve():
    policy = PlannerPolicy(mode="llm", llm_client="stub", llm_model=None)
    client, err = resolve_llm_client_from_policy(policy)
    assert err is None
    assert isinstance(client, StubLLMClient)
    raw = client.generate("ignored")
    assert "summary" in json.loads(raw)


def test_resolve_openai_missing_credentials(monkeypatch):
    # Must not depend on developer machine env (keys often set globally).
    monkeypatch.delenv("FORGE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    policy = PlannerPolicy(mode="llm", llm_client="openai", llm_model="gpt-4o-mini")
    client, err = resolve_llm_client_from_policy(policy)
    assert client is None
    assert err is not None
    assert "FORGE_OPENAI_API_KEY" in err or "OPENAI_API_KEY" in err
    assert "forge-policy.json" in err or "not" in err.lower()


def test_resolve_openai_with_key(monkeypatch):
    monkeypatch.setenv("FORGE_OPENAI_API_KEY", "sk-test")
    policy = PlannerPolicy(mode="llm", llm_client="openai", llm_model="custom-model")
    client, err = resolve_llm_client_from_policy(policy)
    assert err is None
    assert isinstance(client, OpenAIChatClient)
    assert client._model == "custom-model"


def test_openai_malformed_api_json():
    with pytest.raises(ValueError) as exc:
        parse_chat_completions_response(b"not json")
    assert "json" in str(exc.value).lower()


def test_openai_malformed_api_missing_choices():
    with pytest.raises(ValueError) as exc:
        parse_chat_completions_response(json.dumps({"foo": 1}).encode())
    assert "choices" in str(exc.value).lower()


def test_openai_http_error_message():
    def fail_post(url, headers, body):
        return 401, b'{"error":{"message":"bad key"}}'

    c = OpenAIChatClient(
        model="m",
        api_key="k",
        base_url="https://api.openai.com/v1",
        request_fn=fail_post,
    )
    with pytest.raises(RuntimeError) as exc:
        c.generate("hi")
    assert "401" in str(exc.value)


def test_llm_planner_fails_on_non_json_assistant_content(tmp_path, monkeypatch):
    """Assistant message must be parseable JSON for LLMPlanner."""

    def bad_content(url, headers, body):
        payload = {"choices": [{"message": {"content": "this is not json"}}]}
        return 200, json.dumps(payload).encode()

    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Bad assistant
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    from forge.design_manager import MilestoneService

    monkeypatch.chdir(tmp_path)
    milestone = MilestoneService.get_milestone(1)
    client = OpenAIChatClient(
        model="fake",
        api_key="fake",
        base_url="https://example.invalid",
        request_fn=bad_content,
    )
    with pytest.raises(ValueError) as exc:
        LLMPlanner(client).build_plan(milestone)
    assert "invalid json" in str(exc.value).lower() or "llm planner" in str(exc.value).lower()


def test_policy_rejects_unknown_llm_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from forge.paths import Paths

    Paths.refresh(tmp_path)
    (tmp_path / "forge-policy.json").write_text(
        json.dumps({"planner": {"mode": "llm", "llm_client": "unknown_provider"}}),
        encoding="utf-8",
    )
    from forge.policy_config import load_planner_policy

    _policy, err = load_planner_policy()
    assert err is not None
    assert "llm_client" in err.lower()


def test_openai_successful_plan_via_mock_request(tmp_path, monkeypatch):
    plan_json = json.dumps(
        {
            "actions": [
                "append_section requirements Overview | MOCK_OK",
                "mark_milestone_completed",
            ]
        }
    )

    def ok_post(url, headers, body):
        payload = {
            "choices": [{"message": {"role": "assistant", "content": plan_json}}]
        }
        return 200, json.dumps(payload).encode()

    configure_project(
        tmp_path,
        """
# Milestones

## Milestone 1: Mock OpenAI
- **Objective**: O
- **Scope**: S
- **Validation**: V
""",
    )
    from forge.design_manager import MilestoneService

    monkeypatch.chdir(tmp_path)
    milestone = MilestoneService.get_milestone(1)
    assert milestone is not None

    client = OpenAIChatClient(
        model="fake",
        api_key="fake",
        base_url="https://example.invalid",
        request_fn=ok_post,
    )
    plan = LLMPlanner(client).build_plan(milestone)
    assert len(plan.actions) == 2
