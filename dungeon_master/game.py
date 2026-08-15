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
    # Extraction returned nothing usable, so this turn changed no state. Dropping
    # the delta is the right call — but doing it silently is not: the game would
    # go on narrating plausibly while quietly tracking nothing.
    extraction_failed: bool = False


def corrections_from(rejected: list[str], state: GameState, world: World) -> list[str]:
    """Turn validator rejections into instructions the narrator can act on.

    Only rejections the player would have *seen* in the prose become corrections.
    Bookkeeping ones — a de-duplicated fact, an out-of-scene item that was still
    allowed — are logged but never shown to the narrator, because nothing in the
    story needs to change for them.
    """
    here = world.locations[state.current_location].name
    out: list[str] = []
    for reason in rejected:
        if reason.startswith("move_to:"):
            exits = ", ".join(
                world.locations[e].name
                for e in world.locations[state.current_location].exits
            )
            arrived = "stepped to" in reason
            out.append(
                (
                    f"The player got only as far as {here}, and is standing there "
                    "now. They did NOT reach the place they set out for, and did "
                    "not go inside it."
                    if arrived
                    else f"The player did NOT travel anywhere. They are still in {here}."
                )
                + " Anything you said about arriving somewhere else, or about what"
                " was inside it, is not true. From here they can reach only:"
                f" {exits}."
            )
        elif reason.startswith("add_items: unknown item"):
            item = reason.split("'")[1] if "'" in reason else "that object"
            out.append(
                f"There is no such thing as '{item}' in this world. The player "
                "does not have one and never did. Stop referring to it."
            )
        elif reason.startswith("remove_items:"):
            item = reason.split("'")[1] if "'" in reason else "that object"
            out.append(f"The player still has '{item}'. They did not lose or give it away.")
    return out


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

    if not narration.strip():
        # An empty completion is a failure, not a silent turn. Recording it
        # would poison the transcript with a blank DM reply and hand the
        # extractor nothing to work from.
        log.error("narrator returned no content - see the preceding warning for why")
        return TurnResult(state, "", [], failed=True)

    # Extraction runs on the *complete* narration — extracting from a partial
    # stream silently drops whatever the last sentence established.
    delta = extract(client, world, state, player_input, narration)
    rejected: list[str] = []
    if delta is not None:
        state, rejected = apply_delta(state, delta, world)
        for reason in rejected:
            log.info("rejected - %s", reason)  # ASCII: this log gets read on Windows

    # Replace, never accumulate: a correction is owed for exactly one turn.
    state.pending_corrections = corrections_from(rejected, state, world)
    if state.pending_corrections:
        log.info("correcting narrator: %s", state.pending_corrections)

    state.turn_count += 1
    transcript.append(player_input, narration)
    maybe_compress(client, transcript)
    return TurnResult(state, narration, rejected, extraction_failed=delta is None)
