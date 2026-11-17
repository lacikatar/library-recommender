"""Thin, dependency-free clients for the optional LLM layer.

Plain HTTPS calls keep the install small and make the provider swappable.
Model names change often, so the model is always configurable via LLM_MODEL.
"""

from __future__ import annotations

import json
import re

import httpx

from ..config import Settings

DEFAULT_MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4o-mini"}


class LLMError(RuntimeError):
    pass


def complete_json(settings: Settings, system: str, user: str, max_tokens: int = 900) -> dict:
    """Send one prompt and return the JSON object in the reply."""
    provider = settings.llm_provider.lower()
    model = settings.llm_model or DEFAULT_MODELS.get(provider, "")
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            if provider == "anthropic":
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.llm_api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "system": system,
                        "messages": [{"role": "user", "content": user}],
                    },
                )
                response.raise_for_status()
                text = "".join(
                    block.get("text", "")
                    for block in response.json()["content"]
                    if block.get("type") == "text"
                )
            elif provider == "openai":
                response = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json={
                        "model": model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"]
            else:
                raise LLMError(f"Unknown LLM_PROVIDER {settings.llm_provider!r}")
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    return extract_json(text)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences)."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise LLMError("LLM reply contained no JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"LLM reply was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("LLM reply was not a JSON object")
    return data
