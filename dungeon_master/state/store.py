"""apply_delta is the containment boundary. The model proposes; the code decides.

This module is pure apart from `save`/`load`. No LLM calls, no I/O in the hot path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..memory.transcript import Transcript
from ..world.loader import World
from .models import (
    MAX_FACTS,
    MAX_NOTES_PER_NPC,
    MAX_TRAITS,
    GameState,
    Relationship,
    StateDelta,
)

SAVE_PATH = Path("save.json")


def _clamp(value: int, low: int = -100, high: int = 100) -> int:
    return max(low, min(high, value))


STOPWORDS = frozenset(
    "a an the and or but of to in on at for with without is are was were has have "
    "had that this it its as by from not no been being he she they them his her".split()
)
# Deliberately conservative, and calibrated against a real session: "the light
# has burned every night for eleven years" vs "the light above has burned
# steadily for 11 years" scores 0.67. The extractor prompt is the primary defence
# against canon echoes; this is the net under it, and every suppression is logged.
NEAR_DUPLICATE_RATIO = 0.6


def _significant(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    # "11" and "eleven" are the same claim to a reader; normalise small numerals
    # so a rephrased fact is recognised as the fact it already is.
    numerals = {"eleven": "11", "three": "3", "four": "4", "two": "2", "one": "1"}
    return {numerals.get(w, w) for w in words if w not in STOPWORDS}


def _is_near_duplicate(candidate: str, existing: list[str]) -> bool:
    """True if `candidate` mostly restates something already recorded.

    Exact matching is not enough in practice: an extractor will happily record
    "the light has burned for eleven years" and "the light above has burned
    steadily for 11 years" as two separate facts, and the ledger is injected in
    full every turn.
    """
    words = _significant(candidate)
    if not words:
        return True
    return any(
        len(words & _significant(prior)) / len(words) >= NEAR_DUPLICATE_RATIO
        for prior in existing
    )


def _append_capped(
    existing: list[str], new: list[str], cap: int, label: str = ""
) -> tuple[list[str], list[str]]:
    """De-duplicate (including near-duplicates) and keep the most recent `cap`.

    Returns the new list plus a rejection reason for anything suppressed —
    de-duplication is a heuristic, so it reports itself rather than quietly
    dropping something a reader might have wanted.
    """
    out, notes = list(existing), []
    for entry in new:
        entry = entry.strip()
        if not entry:
            continue
        if _is_near_duplicate(entry, out):
            notes.append(f"{label}: '{entry}' restates something already recorded")
        else:
            out.append(entry)
    return out[-cap:], notes


def apply_delta(
    state: GameState, delta: StateDelta, world: World
) -> tuple[GameState, list[str]]:
    """Validate a proposed delta against the world bible and apply what survives.

    Returns the new state and a list of rejection reasons. Rejections are logged
    by the caller, never raised and never surfaced to the player: a dropped state
    update is recoverable, a crash mid-adventure is not.
    """
    new = state.model_copy(deep=True)
    rejected: list[str] = []

    # --- movement -----------------------------------------------------------
    if delta.move_to and delta.move_to != state.current_location:
        if delta.move_to not in world.locations:
            rejected.append(f"move_to: unknown location '{delta.move_to}'")
        elif not world.is_adjacent(state.current_location, delta.move_to):
            rejected.append(
                f"move_to: '{delta.move_to}' is not reachable from "
                f"'{state.current_location}'"
            )
        else:
            new.current_location = delta.move_to

    if new.current_location not in new.visited:
        new.visited.append(new.current_location)

    # --- inventory ----------------------------------------------------------
    for item_id in delta.add_items:
        if item_id not in world.items:
            rejected.append(f"add_items: unknown item '{item_id}'")
        elif item_id in new.inventory:
            rejected.append(f"add_items: '{item_id}' already held")
        else:
            new.inventory.append(item_id)
            # Decision 3: bible membership is the hard gate; scene presence is
            # only a warning, so that NPC gifts and rewards still work.
            if item_id not in world.locations[state.current_location].items:
                rejected.append(
                    f"add_items: '{item_id}' was not in scene "
                    f"'{state.current_location}' (allowed, logged)"
                )

    for item_id in delta.remove_items:
        if item_id in new.inventory:
            new.inventory.remove(item_id)
        else:
            rejected.append(f"remove_items: '{item_id}' not held")

    # --- relationships ------------------------------------------------------
    for change in delta.relationship_changes:
        if change.npc_id not in world.npcs:
            rejected.append(f"relationship_changes: unknown npc '{change.npc_id}'")
            continue
        rel = new.relationships.get(change.npc_id)
        if rel is None:
            rel = Relationship(
                npc_id=change.npc_id,
                disposition=world.npcs[change.npc_id].default_disposition,
            )
        rel.disposition = _clamp(rel.disposition + change.delta)
        if change.note:
            rel.notes, note_dupes = _append_capped(
                rel.notes, [change.note], MAX_NOTES_PER_NPC, f"note[{change.npc_id}]"
            )
            rejected += note_dupes
        new.relationships[change.npc_id] = rel

    # --- quests -------------------------------------------------------------
    for quest_id, stage in delta.quest_updates.items():
        quest = world.quests.get(quest_id)
        if quest is None:
            rejected.append(f"quest_updates: unknown quest '{quest_id}'")
        elif stage not in quest.stages:
            rejected.append(f"quest_updates: unknown stage '{stage}' for '{quest_id}'")
        else:
            new.quest_flags[quest_id] = stage

    # --- narrative ledgers --------------------------------------------------
    new.established_facts, fact_notes = _append_capped(
        new.established_facts, delta.new_facts, MAX_FACTS, "new_facts"
    )
    new.player_traits, trait_notes = _append_capped(
        new.player_traits, delta.new_traits, MAX_TRAITS, "new_traits"
    )
    rejected += fact_notes + trait_notes

    return new, rejected


def new_game(world: World) -> GameState:
    start = world.meta.start_location
    return GameState(
        current_location=start,
        visited=[start],
        quest_flags={qid: q.start for qid, q in world.quests.items()},
    )


def save(state: GameState, transcript: Transcript, path: Path = SAVE_PATH) -> None:
    """One file, plain JSON, human-readable on purpose — a reviewer should be able
    to open a save and see that the state layer is real."""
    blob = {"state": state.model_dump(), "transcript": transcript.model_dump()}
    path.write_text(json.dumps(blob, indent=2), encoding="utf-8")


def load(path: Path = SAVE_PATH) -> tuple[GameState, Transcript]:
    blob = json.loads(path.read_text(encoding="utf-8"))
    return (
        GameState.model_validate(blob["state"]),
        Transcript.model_validate(blob.get("transcript", {})),
    )
