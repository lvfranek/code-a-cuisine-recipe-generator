"""LLM access via OpenRouter: one call, JSON extraction, validation and auto-repair.

LLM output is untrusted. `complete_json` validates it against a Pydantic model
and, if that fails, asks the LLM to repair its own output (max N attempts).
"""

import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config import get_settings

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """The LLM could not deliver a usable answer."""


class RetryableLLMError(LLMError):
    """Temporary problem (rate limit, server error, network) worth retrying."""


@retry(
    retry=retry_if_exception_type(RetryableLLMError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
async def chat(messages: list[dict], *, temperature: float | None = None) -> str:
    """Send one chat request and return the text content of the answer."""
    s = get_settings()
    if not s.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not configured")

    payload = {
        "model": s.llm_model,
        "temperature": s.llm_temperature if temperature is None else temperature,
        "max_tokens": s.llm_max_tokens,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {s.openrouter_api_key}",
        "HTTP-Referer": s.app_url,
        "X-Title": s.app_title,
    }
    try:
        async with httpx.AsyncClient(timeout=s.llm_timeout_seconds) as client:
            res = await client.post(OPENROUTER_URL, json=payload, headers=headers)
    except httpx.TransportError as err:
        raise RetryableLLMError(f"Network error: {err}") from err

    if res.status_code == 429 or res.status_code >= 500:
        raise RetryableLLMError(f"OpenRouter returned {res.status_code}: {res.text[:300]}")
    if res.status_code >= 400:
        raise LLMError(f"OpenRouter returned {res.status_code}: {res.text[:300]}")

    try:
        content = res.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as err:
        raise RetryableLLMError(f"Unexpected OpenRouter response: {res.text[:300]}") from err
    if not content:
        raise RetryableLLMError("Empty response from model")
    return content


_FENCED = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_text(text: str) -> str:
    """Cut the JSON object out of a model answer (handles ```json fences and chatter)."""
    match = _FENCED.search(text or "")
    candidate = match.group(1) if match else (text or "")
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object in model response")
    return candidate[start : end + 1]


def parse_output(text: str, schema: type[T]) -> T:
    """Validate a model answer against the schema. Raises ValueError on failure."""
    return schema.model_validate_json(extract_json_text(text))


def build_repair_messages(bad_output: str, error: str, schema: type[BaseModel]) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "You repair invalid JSON. Return ONLY the corrected JSON object, no markdown, no comments.",
        },
        {
            "role": "user",
            "content": (
                "This output did not match the required JSON schema.\n\n"
                f"JSON schema:\n{json.dumps(schema.model_json_schema())}\n\n"
                f"Validation error:\n{error[:2000]}\n\n"
                f"Invalid output:\n{bad_output[:12000]}\n\n"
                "Fix it so it matches the schema. Keep all valid content unchanged."
            ),
        },
    ]


async def complete_json(messages: list[dict], schema: type[T]) -> T:
    """Call the LLM, validate the answer, auto-repair it if needed (max N times)."""
    max_repairs = get_settings().max_repair_attempts
    content = await chat(messages)

    for attempt in range(max_repairs + 1):
        try:
            return parse_output(content, schema)
        except ValueError as err:  # includes pydantic.ValidationError
            if attempt == max_repairs:
                raise LLMError(f"Invalid model output after {max_repairs} repair attempts: {err}") from err
            log.warning("LLM output invalid (repair %d/%d): %s", attempt + 1, max_repairs, _short(err))
            content = await chat(build_repair_messages(content, str(err), schema), temperature=0)

    raise LLMError("unreachable")  # pragma: no cover


def _short(err: Exception) -> str:
    if isinstance(err, ValidationError):
        return f"{err.error_count()} validation error(s)"
    return str(err)[:200]
