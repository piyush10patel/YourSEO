"""Async integration with a locally running Ollama server (Llama-3).

Sends prompts to Ollama's ``/api/chat`` endpoint and returns *structured*
JSON. Schema enforcement is belt-and-braces:

    1. The JSON schema is injected into the system prompt as an instruction
       (works with any model, including older builds).
    2. The same schema is passed to Ollama's native ``format`` field so the
       server constrains decoding to valid JSON matching the schema
       (Ollama >= 0.5 "structured outputs").
    3. If a Pydantic model is supplied, the parsed result is validated
       against it and returned as a model instance.

Timeouts and connection failures are caught and re-raised as the typed
errors in ``app.core.exceptions`` (``LLMTimeoutError`` / ``LLMConnectionError``
/ ``LLMResponseError``), each carrying the HTTP status the API layer surfaces.

Usage:
    async with OllamaClient() as llm:
        data = await llm.generate_json(
            prompt="List 3 SEO keywords for a vegan bakery.",
            schema=KeywordList,            # a Pydantic model *or* a dict schema
            system="You are an SEO expert.",
            temperature=0.3,
        )
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, TypeVar, overload

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings, get_settings
from app.core.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

# A JSON value type alias for the dict-schema return path.
JSONDict = dict[str, Any]


def _build_system_prompt(schema: JSONDict, user_system: str | None) -> str:
    """Compose a system prompt that pins the model to ``schema``."""
    schema_text = json.dumps(schema, indent=2, ensure_ascii=False)
    instructions = (
        "You must respond with a single, valid JSON object and nothing else. "
        "Do not wrap it in markdown code fences, and do not add commentary "
        "before or after the JSON. The object MUST conform exactly to this "
        "JSON Schema:\n\n"
        f"{schema_text}"
    )
    if user_system:
        return f"{user_system.strip()}\n\n{instructions}"
    return instructions


class OllamaClient:
    """Async client for a local Ollama server returning structured JSON."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.settings.ollama_base_url,
            timeout=httpx.Timeout(self.settings.ollama_timeout),
        )

    # ------------------------------------------------------------------ #
    # Lifecycle (async context manager)
    # ------------------------------------------------------------------ #
    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        # Only close the client if we created it; a caller-supplied client
        # is the caller's responsibility.
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @overload
    async def generate_json(
        self,
        prompt: str,
        *,
        schema: type[TModel],
        system: str | None = ...,
        temperature: float | None = ...,
        model: str | None = ...,
    ) -> TModel: ...

    @overload
    async def generate_json(
        self,
        prompt: str,
        *,
        schema: JSONDict,
        system: str | None = ...,
        temperature: float | None = ...,
        model: str | None = ...,
    ) -> JSONDict: ...

    async def generate_json(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | JSONDict,
        system: str | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> BaseModel | JSONDict:
        """Send ``prompt`` and return a JSON object matching ``schema``.

        ``schema`` may be a Pydantic model class (the validated instance is
        returned) or a raw JSON-Schema dict (a validated-by-the-model dict is
        returned). Raises a subclass of ``LLMError`` on failure.
        """
        is_model = isinstance(schema, type) and issubclass(schema, BaseModel)
        json_schema: JSONDict = schema.model_json_schema() if is_model else schema  # type: ignore[union-attr]

        system_prompt = _build_system_prompt(json_schema, system)
        temp = self.settings.ollama_temperature if temperature is None else temperature

        payload = {
            "model": model or self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            # Native structured-output enforcement (Ollama >= 0.5). Older
            # servers treat a dict here as "json" mode, which is still useful.
            "format": json_schema,
            "options": {"temperature": temp},
        }

        raw_content = await self._post_chat(payload)
        data = self._parse_json(raw_content)

        if is_model:
            return self._validate(schema, data)  # type: ignore[arg-type]
        return data

    # ------------------------------------------------------------------ #
    # Streaming (free-form text, token by token)
    # ------------------------------------------------------------------ #
    async def stream_chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant text chunks as they are generated (no JSON schema).

        Used for the ChatGPT-style typing effect. Transient transport failures
        are surfaced as the typed LLM errors, like the non-streaming path.
        """
        temp = self.settings.ollama_temperature if temperature is None else temperature
        messages: list[JSONDict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model or self.settings.ollama_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temp},
        }

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    chunk = (data.get("message") or {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama stream did not respond within {self.settings.ollama_timeout:.0f}s.",
                detail=str(exc),
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Could not connect to Ollama at {self.settings.ollama_base_url}.",
                detail=str(exc),
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMResponseError(
                f"Ollama returned HTTP {exc.response.status_code}.",
                detail=str(exc),
            ) from exc

    # ------------------------------------------------------------------ #
    # HTTP with graceful timeout / connection handling + retry
    # ------------------------------------------------------------------ #
    async def _post_chat(self, payload: JSONDict) -> str:
        """POST to /api/chat, retrying transient failures, return the message text."""
        s = self.settings
        attempts = max(1, s.ollama_max_retries + 1)

        try:
            async for attempt in AsyncRetrying(
                reraise=True,
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(
                    multiplier=s.backoff_initial,
                    exp_base=s.backoff_multiplier,
                    max=s.backoff_max,
                ),
                # Only retry the transient transport errors; bad responses
                # (parse/validation) are deterministic and must not retry.
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.ConnectError)
                ),
            ):
                with attempt:
                    resp = await self._client.post("/api/chat", json=payload)
                    resp.raise_for_status()
                    return self._extract_message(resp.json())
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama did not respond within {s.ollama_timeout:.0f}s.",
                detail=str(exc),
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMConnectionError(
                f"Could not connect to Ollama at {s.ollama_base_url}. "
                "Is the server running (`ollama serve`)?",
                detail=str(exc),
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMResponseError(
                f"Ollama returned HTTP {exc.response.status_code}.",
                detail=exc.response.text[:500],
            ) from exc
        except httpx.RequestError as exc:
            raise LLMConnectionError(
                "Request to Ollama failed.", detail=str(exc)
            ) from exc

        # AsyncRetrying with reraise=True always returns or raises inside the
        # loop; this is unreachable but keeps type-checkers happy.
        raise LLMResponseError("No response produced by Ollama.")

    # ------------------------------------------------------------------ #
    # Parsing / validation helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_message(body: JSONDict) -> str:
        """Pull the assistant text out of an /api/chat response body."""
        try:
            return body["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LLMResponseError(
                "Unexpected Ollama response shape (no message.content).",
                detail=json.dumps(body)[:500],
            ) from exc

    @staticmethod
    def _parse_json(content: str) -> JSONDict:
        """Parse the model's text as JSON, tolerating stray code fences."""
        text = content.strip()
        # Defensive: strip ```json ... ``` fences a model might add anyway.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                "Model did not return valid JSON.",
                detail=f"{exc}; got: {content[:300]}",
            ) from exc
        if not isinstance(data, dict):
            raise LLMResponseError(
                "Model returned JSON that is not an object.",
                detail=f"type={type(data).__name__}",
            )
        return data

    @staticmethod
    def _validate(model: type[TModel], data: JSONDict) -> TModel:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise LLMResponseError(
                f"Model output did not match {model.__name__} schema.",
                detail=str(exc),
            ) from exc
