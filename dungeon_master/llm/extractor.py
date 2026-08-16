"""Pass two: turn (state, input, narration) into a proposed StateDelta.

Never `json.loads` a raw completion. The pipeline is always
fence-strip -> parse -> pydantic validate -> (caller) apply_delta validate.
"""

from __future__ import annotations

import json
import logging
import os
import re

from ..state.models import GameState, StateDelta
from ..world.loader import World
from . import prompts
from .client import LLMClient, LLMError

log = logging.getLogger(__name__)

# A reasoning model starves here more quietly than it does in the narrator: it
# spends the budget thinking, returns empty content, the delta is dropped, and
# the prose still looks fine. `summarizer` imports this too. See DECISIONS 28.
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"
FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def extractor_model() -> str:
    return os.environ.get("EXTRACTOR_MODEL", DEFAULT_MODEL)


def strip_fences(raw: str) -> str:
    """Expect markdown fences rather than treating them as an error — open-weight
    models add them constantly, and it is not worth a retry."""
    text = FENCE.sub("", raw).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def parse_delta(raw: str) -> StateDelta:
    """Raises ValueError with a message worth feeding back to the model."""
    try:
        return StateDelta.model_validate(json.loads(strip_fences(raw)))
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def _canon(world: World, state: GameState) -> str:
    """What the narrator is allowed to restate without it counting as invention.

    Without this the extractor cannot tell canon from novelty, and the
    established-facts ledger fills with echoes of the world bible.
    """
    location = world.locations[state.current_location]
    lines = [*world.history, *location.secrets, location.description]
    lines += [world.items[i].notes for i in state.inventory if i in world.items]
    lines += [world.npcs[n].role for n in location.npcs if n in world.npcs]
    return "\n".join(f"- {line.strip()}" for line in lines if line.strip())


def _user_message(world: World, state: GameState, player_input: str, narration: str) -> str:
    stages = {qid: list(q.stages) for qid, q in world.quests.items()}
    return prompts.EXTRACTOR_USER.render(
        canon=_canon(world, state),
        locations=", ".join(world.locations),
        exits=", ".join(world.locations[state.current_location].exits),
        items=", ".join(world.items),
        npcs=", ".join(world.npcs),
        quests=json.dumps(stages),
        location=state.current_location,
        inventory=", ".join(state.inventory) or "(empty)",
        quest_flags=json.dumps(state.quest_flags),
        traits=", ".join(state.player_traits) or "(none)",
        player_input=player_input,
        narration=narration,
    )


def extract(
    client: LLMClient,
    world: World,
    state: GameState,
    player_input: str,
    narration: str,
) -> StateDelta | None:
    """One retry with the parse error fed back, then give up gracefully.

    Returning None means "no state change this turn". A dropped update is
    recoverable; a crash mid-adventure is not.
    """
    model = extractor_model()
    user = _user_message(world, state, player_input, narration)
    messages = [{"role": "user", "content": user}]

    for attempt in (1, 2):
        try:
            raw = client.complete(
                prompts.EXTRACTOR_SYSTEM.text,
                messages,
                model=model,
                # Headroom for reasoning models, which spend budget thinking
                # before they emit the JSON at all.
                max_tokens=900,
                temperature=0.1,
                json_mode=client.supports_json_mode(model),
            )
            assert isinstance(raw, str)
            if not raw.strip():
                raise ValueError(
                    f"{model} returned empty content — if it is a reasoning model "
                    "it may have spent the whole budget thinking"
                )
            delta = parse_delta(raw)
            log.info("delta (attempt %s): %s", attempt, delta.model_dump(exclude_defaults=True))
            return delta
        except ValueError as exc:
            log.warning("extractor parse failure (attempt %s): %s", attempt, exc)
            if attempt == 1:
                messages = [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": prompts.RETRY_SUFFIX.render(error=exc)},
                ]
        except LLMError as exc:
            log.error("extractor transport failure: %s", exc)
            return None

    log.error("extractor gave up; skipping delta for this turn")
    return None
