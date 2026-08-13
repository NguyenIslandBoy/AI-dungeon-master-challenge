"""Thin transport wrapper over the OpenAI SDK pointed at Novita. No business logic."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.novita.ai/openai"
RETRYABLE = (APITimeoutError, RateLimitError, APIError)


class LLMError(RuntimeError):
    """Transport gave up. The game loop catches this; it never reaches the player raw."""


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        attempts: int = 2,
    ) -> None:
        key = api_key or os.environ.get("NOVITA_API_KEY", "")
        if not key:
            raise LLMError(
                "NOVITA_API_KEY is not set. Copy .env.example to .env and paste your key."
            )
        self.attempts = attempts
        self._client = OpenAI(
            api_key=key,
            base_url=base_url or os.environ.get("NOVITA_BASE_URL", DEFAULT_BASE_URL),
            timeout=timeout,
        )
        self._json_support: dict[str, bool] = {}

    # -- transport ----------------------------------------------------------
    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        model: str,
        max_tokens: int = 600,
        temperature: float = 0.8,
        stream: bool = False,
        json_mode: bool = False,
    ) -> str | Iterator[str]:
        payload: dict = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                if stream:
                    # Open the stream *here*, inside the try. `_iter` is a
                    # generator, so returning it directly would defer the HTTP
                    # call until first iteration — outside this retry block,
                    # where transport errors escape unwrapped.
                    chunks = self._client.chat.completions.create(**payload, stream=True)
                    return self._iter(chunks)
                response = self._client.chat.completions.create(**payload)
                return response.choices[0].message.content or ""
            except RETRYABLE as exc:  # noqa: PERF203 - retry is the point
                last = exc
                log.warning("llm attempt %s/%s failed: %s", attempt, self.attempts, exc)
                if attempt < self.attempts:
                    time.sleep(2**attempt)
        raise LLMError(str(last)) from last

    @staticmethod
    def _iter(chunks) -> Iterator[str]:
        """Yield visible content only.

        Reasoning models put their scratchpad in `reasoning_content` and leave
        `content` empty until they are done thinking. Yielding the scratchpad
        would print the model's private deliberation to the player, so it is
        counted and logged but never emitted.
        """
        thought = spoken = 0
        for chunk in chunks:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if piece := getattr(delta, "content", None):
                spoken += 1
                yield piece
            elif getattr(delta, "reasoning_content", None):
                thought += 1

        if thought and not spoken:
            log.warning(
                "the narrator model spent its entire token budget reasoning (%s "
                "chunks) and never emitted prose. This model is a reasoning "
                "model; set NARRATOR_MODEL to a non-reasoning instruct model "
                "(e.g. zai-org/glm-4.7-flash) — see --models",
                thought,
            )
        elif thought:
            log.info("stream carried %s reasoning chunks before prose", thought)

    # -- catalog ------------------------------------------------------------
    def list_models(self) -> list[str]:
        """Novita rotates its catalog; display names on the website are not API ids."""
        return sorted(m.id for m in self._client.models.list().data)

    def supports_json_mode(self, model: str) -> bool:
        """Probe once, cache. Structured-output support is per-model on Novita."""
        if model not in self._json_support:
            try:
                self.complete(
                    "Reply with {\"ok\": true} and nothing else.",
                    [{"role": "user", "content": "ping"}],
                    model=model,
                    max_tokens=16,
                    temperature=0,
                    json_mode=True,
                )
                self._json_support[model] = True
            except Exception as exc:  # noqa: BLE001 - any failure means fall back
                log.info("json_mode unsupported for %s (%s); prompt-enforcing", model, exc)
                self._json_support[model] = False
        return self._json_support[model]
