"""Thin transport wrapper over the OpenAI SDK pointed at Novita. No business logic."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.novita.ai/openai"
RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, APIError)

# Novita returns 429 "server overload" in bursts that outlast a couple of
# seconds, so the backoff has to be able to wait one out. Capped rather than
# unbounded: 2, 4, 8, 8 is 22s of worst-case waiting before the turn is given up,
# which a player will accept behind a spinner. Doubling forever would not be.
MAX_BACKOFF = 8.0
ATTEMPTS = 5


def _worth_retrying(exc: Exception) -> bool:
    """A 400 means the request itself is wrong, and it will be just as wrong the
    second time. Only 429 and 5xx are worth a backoff — retrying "json_object is
    not supported" merely made startup six seconds slower.
    """
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return True  # timeouts and connection errors


class LLMError(RuntimeError):
    """Transport gave up. The game loop catches this; it never reaches the player raw."""


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        attempts: int = ATTEMPTS,
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
            # One retry layer, not two. The SDK retries twice by default, so the
            # loop below was silently issuing three requests per "attempt" —
            # `attempts=2` meant six. A retry budget nobody can read off the code
            # is a budget nobody can tune, and this one needed tuning.
            max_retries=0,
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
                    return self._iter(chunks, model)
                response = self._client.chat.completions.create(**payload)
                return response.choices[0].message.content or ""
            except RETRYABLE as exc:  # noqa: PERF203 - retry is the point
                last = exc
                if not _worth_retrying(exc):
                    log.warning("llm request rejected, not retrying: %s", exc)
                    break
                log.warning("llm attempt %s/%s failed: %s", attempt, self.attempts, exc)
                if attempt < self.attempts:
                    time.sleep(min(2**attempt, MAX_BACKOFF))
        raise LLMError(str(last)) from last

    @staticmethod
    def _iter(chunks, model: str = "?") -> Iterator[str]:
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
                "NARRATOR_MODEL=%s is a reasoning model: it spent its entire "
                "token budget on %s reasoning chunks and never emitted prose. "
                "Set NARRATOR_MODEL in your .env (NOT .env.example - .env is "
                "gitignored and a pull will not update it) to a model that does "
                "not think before it speaks - meta-llama/llama-3.3-70b-instruct "
                "is verified. An -instruct suffix means nothing: kimi-k2-instruct, "
                "kimi-k2-0905 and glm-4.7-flash all reason. Run --models for the "
                "catalog.",
                model,
                thought,
            )
        elif thought:
            log.info("%s: %s reasoning chunks before prose", model, thought)

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
