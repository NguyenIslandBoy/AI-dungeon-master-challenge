"""One turn of the game. The lifecycle from ARCHITECTURE §4, with no I/O.

Display lives in cli.py: this module hands the narration stream to a `consume`
callback so the loop can be driven by a terminal, a test, or anything else.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import NamedTuple

from . import context
from .llm.client import LLMError
from .llm.extractor import extract
from .llm.narrator import narrate
from .memory.summarizer import maybe_compress
from .memory.transcript import Transcript
from .state.models import GameState
from .state.store import apply_delta
from .world.loader import World

log = logging.getLogger(__name__)


class TurnResult(NamedTuple):
    state: GameState
    narration: str
    rejected: list[str]
    failed: bool = False


def run_turn(
    client,
    world: World,
    state: GameState,
    transcript: Transcript,
    player_input: str,
    *,
    consume: Callable[[Iterator[str]], str] = lambda stream: "".join(stream),
) -> TurnResult:
    """Assemble context, narrate, extract, validate, apply, remember.

    A model failure costs the turn, never the session: on error the state is
    returned untouched and the loop carries on.
    """
    system, messages = context.build(state, world, transcript, player_input)

    try:
        narration = consume(narrate(client, system, messages))
    except LLMError as exc:
        log.error("narrator failed: %s", exc)
        return TurnResult(state, "", [], failed=True)

    # Extraction runs on the *complete* narration — extracting from a partial
    # stream silently drops whatever the last sentence established.
    delta = extract(client, world, state, player_input, narration)
    rejected: list[str] = []
    if delta is not None:
        state, rejected = apply_delta(state, delta, world)
        for reason in rejected:
            log.info("rejected — %s", reason)

    state.turn_count += 1
    transcript.append(player_input, narration)
    maybe_compress(client, transcript)
    return TurnResult(state, narration, rejected)
