import asyncio
import json

import pytest
from pydantic import BaseModel

from core import llm
from core.llm import LLMError, complete_json, extract_json_text


class Dish(BaseModel):
    name: str
    minutes: int


def fake_chat(answers):
    """Replace llm.chat with a function that returns the given answers in order."""
    calls = []

    async def _chat(messages, *, temperature=None):
        calls.append(messages)
        return answers[len(calls) - 1]

    return _chat, calls


def test_extract_json_from_fenced_block():
    text = 'Sure! ```json\n{"name": "Soup", "minutes": 5}\n``` enjoy'
    assert json.loads(extract_json_text(text)) == {"name": "Soup", "minutes": 5}


def test_extract_json_without_object_raises():
    with pytest.raises(ValueError):
        extract_json_text("no json here")


def test_valid_output_needs_no_repair(monkeypatch):
    chat, calls = fake_chat(['{"name": "Soup", "minutes": 5}'])
    monkeypatch.setattr(llm, "chat", chat)
    result = asyncio.run(complete_json([], Dish))
    assert result == Dish(name="Soup", minutes=5)
    assert len(calls) == 1


def test_invalid_output_is_repaired(monkeypatch):
    chat, calls = fake_chat([
        '{"name": "Soup", "minutes": "a while"}',  # invalid
        '{"name": "Soup", "minutes": 10}',  # repaired
    ])
    monkeypatch.setattr(llm, "chat", chat)
    result = asyncio.run(complete_json([], Dish))
    assert result.minutes == 10
    assert len(calls) == 2
    repair_prompt = calls[1][-1]["content"]
    assert "a while" in repair_prompt and "Validation error" in repair_prompt


def test_repair_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    llm.get_settings.cache_clear()
    chat, calls = fake_chat(["broken"] * 10)
    monkeypatch.setattr(llm, "chat", chat)
    with pytest.raises(LLMError, match="after 2 repair attempts"):
        asyncio.run(complete_json([], Dish))
    assert len(calls) == 3  # 1 original + 2 repairs
