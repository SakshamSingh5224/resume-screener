"""
Single swappable adapter around the LLM provider. Every other module that
wants LLM assistance calls `call_llm_json(...)` — swap the provider here
without touching business logic elsewhere.

Never hard-code API keys; always read from environment variables (config.py).
"""
from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

import requests
from pydantic import BaseModel

from config import ANTHROPIC_API_KEY, LLM_MODEL

T = TypeVar("T", bound=BaseModel)


class LLMCallError(Exception):
    pass


def call_llm_json(system_prompt: str, user_prompt: str, schema: Type[T],
                   max_tokens: int = 1000, timeout: int = 30) -> Optional[T]:
    """Call the LLM and parse its reply into `schema`. Returns None (never
    raises to the caller) if the key is missing, the call fails, or the
    response doesn't parse — callers must have a deterministic fallback."""
    if not ANTHROPIC_API_KEY:
        return None

    full_system = (
        f"{system_prompt}\n\n"
        "Respond with ONLY a single valid JSON object matching this schema, "
        "no markdown fences, no preamble, no explanation outside the JSON:\n"
        f"{schema.model_json_schema()}"
    )

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "max_tokens": max_tokens,
                "system": full_system,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        raw_text = "\n".join(text_blocks).strip()
        raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw_text)
        return schema(**parsed)
    except (requests.RequestException, json.JSONDecodeError, TypeError, ValueError):
        return None
