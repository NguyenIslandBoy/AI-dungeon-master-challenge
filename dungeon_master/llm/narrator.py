"""The narrator owns prose and nothing else. It proposes no state."""

from __future__ import annotations

import os
from collections.abc import Iterator

from .client import LLMClient

DEFAULT_MODEL = "deepseek/deepseek-v3.2"


def narrator_model() -> str:
    return os.environ.get("NARRATOR_MODEL", DEFAULT_MODEL)


def narrate(
    client: LLMClient, system: str, messages: list[dict], *, stream: bool = True
) -> Iterator[str]:
    """Yield prose pieces. Streaming is what hides the extractor's latency behind
    the player's reading time, which is the reason two-pass costs nothing felt."""
    result = client.complete(
        system,
        messages,
        model=narrator_model(),
        max_tokens=500,
        temperature=0.85,
        stream=stream,
    )
    if isinstance(result, str):
        yield result
    else:
        yield from result
