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
        json.dumps({"add_items": ["letter"], "new_traits": ["distrusts wizards"]}),
        # turn 2 — walk out to the yard
        "Weather takes you sideways the moment you clear the door.",
        json.dumps({"move_to": "yard", "quest_updates": {"q_light": "seen"}}),
        # turn 3 — the narrator hallucinates a sword and a shortcut to the tower
        "You find a greatsword in the mud, and a hidden stair straight to the tower.",
        json.dumps({"add_items": ["greatsword"], "move_to": "tower"}),
    )

    state = run_turn(client, world, state, transcript,
                     "I pick up the letter. I don't trust wizards.").state
    assert state.inventory == ["letter"]
    assert state.player_traits == ["distrusts wizards"]

    state = run_turn(client, world, state, transcript, "I go out to the yard").state
    assert state.current_location == "yard"
    assert state.quest_flags["q_light"] == "seen"

    result = run_turn(client, world, state, transcript, "I look around the mud")
    state, rejected = result.state, result.rejected
    # Prose said sword. State says no sword. State wins.
    assert state.inventory == ["letter"]
    assert any("unknown item 'greatsword'" in r for r in rejected)
    # No hidden stair exists: from the yard the tower is reached via the hall,
    # so the player walks back there rather than teleporting up it.
    assert state.current_location == "hall"
    assert any("stepped to 'hall'" in r for r in rejected)

    assert state.turn_count == 3
    assert state.visited == ["hall", "yard"]


def test_a_rejected_move_corrects_the_narrator_next_turn(world, state):
    """Observed live: the move to a two-hop room was correctly rejected, but the
    prose described the player climbing the stair and arriving anyway. State
    stayed right while the story walked off without it. The validator's
    rejections are the only signal that can pull it back."""
    transcript = Transcript()
    client = StubClient(
        "You climb the stair. The tower waits, full of light.",
        json.dumps({"move_to": "tower"}),
    )
    result = run_turn(client, world, state, transcript, "I take the stair to the tower")

    # One room per turn: they reach the stair, not the room at the top of it.
    assert result.state.current_location == "stair"
    assert result.state.pending_corrections
    correction = result.state.pending_corrections[0]
    assert "got only as far as The Stair" in correction
    assert "did not go inside it" in correction
    # Naming the real exits gives the narrator somewhere legitimate to go, rather
    # than only telling it what it got wrong.
    assert "The Hall" in correction and "The Tower" in correction

    system, _ = context.build(result.state, world, transcript, "what now?")
    assert "CORRECTIONS" in system
    assert "The Stair" in system


def test_a_hallucinated_item_is_disowned_to_the_narrator(world, state):
    client = StubClient("You draw your greatsword.", json.dumps({"add_items": ["greatsword"]}))
    result = run_turn(client, world, state, Transcript(), "I draw my greatsword")

    assert result.state.inventory == []
    assert any("no such thing as 'greatsword'" in c for c in result.state.pending_corrections)


def test_corrections_are_owed_for_exactly_one_turn(world, state):
    transcript = Transcript()
    bad = StubClient("You stride into the tower.", json.dumps({"move_to": "tower"}))
    state = run_turn(bad, world, state, transcript, "up to the tower").state
    assert state.pending_corrections

    good = StubClient("You stay where you are.", json.dumps({}))
    state = run_turn(good, world, state, transcript, "I wait").state
    assert state.pending_corrections == []

    system, _ = context.build(state, world, transcript, "now what?")
    assert "CORRECTIONS" not in system


def test_bookkeeping_rejections_never_reach_the_narrator(world, state):
    """An out-of-scene item is allowed and merely logged; nothing in the story
    needs to change, so the narrator must not be told to retract anything."""
    client = StubClient("She presses a charm into your hand.", json.dumps({"add_items": ["journal"]}))
    result = run_turn(client, world, state, Transcript(), "I accept the charm")

    assert "journal" in result.state.inventory
    assert any("was not in scene" in r for r in result.rejected)  # logged
    assert result.state.pending_corrections == []  # but not a correction


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
    client = StubClient("You take it.", json.dumps({"add_items": ["lamp"]}))
    result = run_turn(client, world, state, Transcript(), "I take the key")
    assert result.extraction_failed is False
    assert result.state.inventory == ["lamp"]


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
        "The Warden grunts.",
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
    delta = StateDelta(add_items=["lamp"], new_traits=["distrusts wizards"])
    state, _ = apply_delta(state, delta, world)

    path = tmp_path / "save.json"
    save(state, transcript, path)
    restored_state, restored_transcript = load(path)

    assert restored_state == state
    assert restored_transcript.summary == "Something happened."
    assert restored_transcript.turns[0].player == "I take the key"
    # A reviewer should be able to open a save and see the state layer is real.
    assert "lamp" in json.loads(path.read_text())["state"]["inventory"]
