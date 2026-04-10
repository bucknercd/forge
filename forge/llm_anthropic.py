"""
Anthropic Messages API client (stdlib HTTP only).

Credentials: FORGE_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY (never repo config).
Optional: FORGE_ANTHROPIC_BASE_URL (default https://api.anthropic.com).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable

from forge.llm import LLMClient

DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 16384

HttpPostFn = Callable[[str, dict[str, str], bytes], tuple[int, bytes]]


def anthropic_api_key_from_env() -> str | None:
    return os.environ.get("FORGE_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


def anthropic_base_url_from_env() -> str:
    return (os.environ.get("FORGE_ANTHROPIC_BASE_URL") or DEFAULT_ANTHROPIC_BASE).rstrip("/")


def parse_messages_response(raw: bytes) -> str:
    """Extract assistant text from Anthropic Messages API JSON."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Anthropic provider returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Anthropic provider response must be a JSON object.")
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message", json.dumps(err))
        raise ValueError(f"Anthropic provider error: {msg}")
    content = data.get("content")
    if not isinstance(content, list) or not content:
        raise ValueError("Anthropic provider response missing or empty 'content' array.")
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    if not parts:
        raise ValueError("Anthropic provider response has no text content blocks.")
    return "\n".join(parts).strip()


class AnthropicMessagesClient(LLMClient):
    """Minimal Messages API wrapper; matches :meth:`LLMClient.generate` contract."""

    def __init__(
        self,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        request_fn: HttpPostFn | None = None,
    ) -> None:
        self._model = model or DEFAULT_ANTHROPIC_MODEL
        self._api_key = api_key if api_key is not None else anthropic_api_key_from_env()
        self._base_url = (base_url or anthropic_base_url_from_env()).rstrip("/")
        self._max_tokens = max(256, min(int(max_tokens), 200_000))
        self._request_fn: HttpPostFn = request_fn or _default_http_post

    def generate(self, prompt: str) -> str:
        if not self._api_key:
            raise RuntimeError(
                "Anthropic API key is missing. Set FORGE_ANTHROPIC_API_KEY or "
                "ANTHROPIC_API_KEY in the environment (not in forge-policy.json)."
            )
        url = f"{self._base_url}/v1/messages"
        body = json.dumps(
            {
                "model": self._model,
                "max_tokens": self._max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        status, raw = self._request_fn(url, headers, body)
        if status != 200:
            snippet = raw[:800].decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Anthropic API request failed with HTTP {status}. "
                f"Response body (truncated): {snippet}"
            )
        return parse_messages_response(raw)

    @property
    def client_id(self) -> str:
        return "anthropic"

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
