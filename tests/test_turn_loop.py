"""The turn lifecycle end to end, with a stubbed model.

Everything here is the deterministic half of ARCHITECTURE §4: assemble context,
narrate, extract, validate, apply, remember, persist. Only the model's judgement
is faked — the plumbing is real.
"""

from __future__ import annotations

import json

from dungeon_master import context
from dungeon_master.game import run_turn
from dungeon_master.llm.client import LLMError
from dungeon_master.memory.summarizer import maybe_compress
from dungeon_master.memory.transcript import Transcript
from dungeon_master.state.models import StateDelta
from dungeon_master.state.store import apply_delta, load, save

from tests.stubs import StubClient


def test_a_short_playthrough_keeps_state_exact(world, state):
    transcript = Transcript()
    client = StubClient(
        # turn 1 — take the letter and state a preference
        "The wax splits under your thumb.",
        json.dumps({"add_items": ["sealed_letter"], "new_traits": ["distrusts wizards"]}),
        # turn 2 — walk out to the shore
        "Rain takes you sideways the moment you clear the door.",
        json.dumps({"move_to": "shore_path", "quest_updates": {"the_dark_night": "asked"}}),
        # turn 3 — the narrator hallucinates a sword; the state layer refuses it
        "You find a greatsword wedged in the rocks, and a hidden stair to the lamp room.",
        json.dumps({"add_items": ["greatsword"], "move_to": "lamp_room"}),
    )

    state = run_turn(client, world, state, transcript,
                     "I pick up the letter. I don't trust wizards.").state
    assert state.inventory == ["sealed_letter"]
    assert state.player_traits == ["distrusts wizards"]

    state = run_turn(client, world, state, transcript, "I go out to the shore").state
    assert state.current_location == "shore_path"
    assert state.quest_flags["the_dark_night"] == "asked"

    result = run_turn(client, world, state, transcript, "I look around the rocks")
    state, rejected = result.state, result.rejected
    # Prose said sword. State says no sword. State wins.
    assert state.inventory == ["sealed_letter"]
    assert state.current_location == "shore_path"
    assert any("unknown item 'greatsword'" in r for r in rejected)
    assert any("not reachable" in r for r in rejected)

    assert state.turn_count == 3
    assert state.visited == ["lighthouse_landing", "shore_path"]


def test_a_narrator_failure_costs_the_turn_not_the_session(world, state):
    """The game loop never dies from an LLM failure. That is the robustness bar."""

    class FailingClient(StubClient):
        def complete(self, *args, **kwargs):
            raise LLMError("upstream timed out")

    before = state.model_copy(deep=True)
    transcript = Transcript()
    result = run_turn(FailingClient(), world, state, transcript, "I climb the stair")

    assert result.failed is True
    assert result.state == before  # nothing moved, nothing lost
    assert transcript.turns == []  # a failed turn is not remembered as one


def test_a_dropped_delta_is_reported_not_swallowed(world, state):
    """Dropping an unusable delta is correct. Doing it silently is not — the game
    would narrate plausibly for twenty turns while tracking nothing."""
    transcript = Transcript()
    client = StubClient("The rain keeps on.", "not json", "still not json")
    result = run_turn(client, world, state, transcript, "I take the key")

    assert result.failed is False  # the turn itself succeeded
    assert result.extraction_failed is True  # but no state moved
    assert result.state.inventory == []
    assert transcript.turns[0].dm == "The rain keeps on."  # prose still remembered


def test_a_successful_delta_does_not_flag_extraction_failure(world, state):
    client = StubClient("You take it.", json.dumps({"add_items": ["rusty_key"]}))
    result = run_turn(client, world, state, Transcript(), "I take the key")
    assert result.extraction_failed is False
    assert result.state.inventory == ["rusty_key"]


def test_an_empty_completion_is_a_failed_turn_not_a_silent_one(world, state):
    """A blank narration must not reach the transcript — it would poison memory
    with an empty DM reply and give the extractor nothing to read."""
    transcript = Transcript()
    result = run_turn(StubClient(""), world, state, transcript, "I look around")

    assert result.failed is True
    assert transcript.turns == []
    assert result.state.turn_count == 0


def test_an_early_preference_reaches_a_later_prompt(world, state):
    """The brief's worked example: 'I don't trust wizards' must still be shaping
    the prompt many turns later, without depending on the summariser."""
    transcript = Transcript()
    client = StubClient(
        "The Wrecker grunts.",
        json.dumps({"new_traits": ["distrusts wizards"]}),
    )
    state = run_turn(client, world, state, transcript, "wizards give me the creeps").state

    for i in range(20):
        transcript.append(f"filler {i}", "the sea continues")

    system, _ = context.build(state, world, transcript, "I approach the boathouse")
    assert "distrusts wizards" in system


def test_summariser_folds_aged_out_turns_and_is_told_not_to_duplicate_state(world):
    transcript = Transcript()
    for i in range(12):
        transcript.append(f"turn {i}", f"reply {i}")

    client = StubClient("The player wandered the Reach and annoyed a Warden.")
    assert maybe_compress(client, transcript) is True
    assert transcript.summary == "The player wandered the Reach and annoyed a Warden."
    assert transcript.compressed_through == 4

    system_prompt = client.calls[0]["system"]
    assert "OMIT ENTIRELY" in system_prompt
    assert "turn 0" in system_prompt and "turn 3" in system_prompt
    assert "turn 11" not in system_prompt  # still inside the verbatim window

    assert maybe_compress(client, transcript) is False  # nothing new to fold


def test_save_and_load_round_trips_state_and_memory(world, state, tmp_path):
    transcript = Transcript(summary="Something happened.")
    transcript.append("I take the key", "It is cold.")
    delta = StateDelta(add_items=["rusty_key"], new_traits=["distrusts wizards"])
    state, _ = apply_delta(state, delta, world)

    path = tmp_path / "save.json"
    save(state, transcript, path)
    restored_state, restored_transcript = load(path)

    assert restored_state == state
    assert restored_transcript.summary == "Something happened."
    assert restored_transcript.turns[0].player == "I take the key"
    # A reviewer should be able to open a save and see the state layer is real.
    assert "rusty_key" in json.loads(path.read_text())["state"]["inventory"]
