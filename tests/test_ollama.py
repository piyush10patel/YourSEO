"""Ollama client tests using httpx.MockTransport — no real model is called."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.core.exceptions import LLMResponseError, LLMTimeoutError
from app.services.ollama import OllamaClient


class _Keyword(BaseModel):
    term: str
    volume: int


def _client(handler, settings: Settings) -> OllamaClient:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(base_url=settings.ollama_base_url, transport=transport)
    return OllamaClient(settings=settings, client=client)


async def test_generate_json_validates_into_model(settings: Settings) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        content = json.dumps({"term": "vegan cake", "volume": 1200})
        return httpx.Response(200, json={"message": {"content": content}})

    async with _client(handler, settings) as llm:
        result = await llm.generate_json("x", schema=_Keyword, temperature=0.3)

    assert isinstance(result, _Keyword)
    assert result.term == "vegan cake"
    # Schema injected into the system prompt + native format enforcement.
    assert "JSON Schema" in captured["body"]["messages"][0]["content"]
    assert captured["body"]["options"]["temperature"] == 0.3
    assert isinstance(captured["body"]["format"], dict)


async def test_code_fences_are_tolerated(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        fenced = '```json\n{"ok": true}\n```'
        return httpx.Response(200, json={"message": {"content": fenced}})

    async with _client(handler, settings) as llm:
        result = await llm.generate_json("x", schema={"type": "object"})
    assert result == {"ok": True}


async def test_timeout_raises_llm_timeout(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    async with _client(handler, settings) as llm:
        with pytest.raises(LLMTimeoutError):
            await llm.generate_json("x", schema={"type": "object"})


async def test_invalid_json_raises_response_error(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not json"}})

    async with _client(handler, settings) as llm:
        with pytest.raises(LLMResponseError):
            await llm.generate_json("x", schema={"type": "object"})


async def test_stream_chat_yields_tokens(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Ollama streams newline-delimited JSON objects.
        body = "\n".join(
            [
                json.dumps({"message": {"content": "Hello "}, "done": False}),
                json.dumps({"message": {"content": "world"}, "done": False}),
                json.dumps({"message": {"content": "!"}, "done": True}),
            ]
        )
        return httpx.Response(200, content=body.encode())

    async with _client(handler, settings) as llm:
        chunks = [c async for c in llm.stream_chat("hi", system="be brief")]

    assert chunks == ["Hello ", "world", "!"]
    assert "".join(chunks) == "Hello world!"
