"""
OpenAI Chat Completions client (stdlib HTTP only).

Credentials: FORGE_OPENAI_API_KEY or OPENAI_API_KEY (never repo config).
Optional: FORGE_OPENAI_BASE_URL (default https://api.openai.com/v1).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

from forge.llm import LLMClient

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# (url, headers, body) -> (status_code, response_bytes)
HttpPostFn = Callable[[str, dict[str, str], bytes], tuple[int, bytes]]


def openai_api_key_from_env() -> str | None:
    return os.environ.get("FORGE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")


def openai_base_url_from_env() -> str:
    return (os.environ.get("FORGE_OPENAI_BASE_URL") or DEFAULT_OPENAI_BASE).rstrip("/")


def parse_chat_completions_response(raw: bytes) -> str:
    """
    Extract assistant text from an OpenAI-style chat/completions JSON body.
    Raises ValueError with an actionable message on malformed payloads.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI provider returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("OpenAI provider response must be a JSON object.")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI provider response missing or empty 'choices' array.")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("OpenAI provider response 'choices[0]' must be an object.")
    msg = first.get("message")
    if not isinstance(msg, dict):
        raise ValueError("OpenAI provider response missing 'message' object.")
    content = msg.get("content")
    if not isinstance(content, str):
        raise ValueError("OpenAI provider response missing string 'message.content'.")
    return content.strip()


class OpenAIChatClient(LLMClient):
    """
    Minimal chat/completions client for planner prompts.
    Injected request_fn enables tests without network.
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        request_fn: HttpPostFn | None = None,
    ) -> None:
        self._model = model or DEFAULT_OPENAI_MODEL
        self._api_key = api_key if api_key is not None else openai_api_key_from_env()
        self._base_url = (base_url or openai_base_url_from_env()).rstrip("/")
        self._request_fn: HttpPostFn = request_fn or _default_http_post

    def generate(self, prompt: str) -> str:
        if not self._api_key:
            raise RuntimeError(
                "OpenAI API key is missing. Set FORGE_OPENAI_API_KEY or OPENAI_API_KEY "
                "in the environment (not in forge-policy.json)."
            )
        url = f"{self._base_url}/chat/completions"
        body = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        status, raw = self._request_fn(url, headers, body)
        if status != 200:
            snippet = raw[:800].decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI API request failed with HTTP {status}. Response body (truncated): {snippet}"
            )
        return parse_chat_completions_response(raw)

    @property
    def client_id(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str | None:
        return self._model


def _default_http_post(url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
