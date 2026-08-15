"""The context builder is where the architecture is either real or decorative."""

from __future__ import annotations

from dungeon_master import context
from dungeon_master.memory.transcript import Transcript
from dungeon_master.state.models import RelChange, StateDelta
from dungeon_master.state.store import apply_delta


def test_scene_injects_only_the_current_location(world, state):
    system, _ = context.build(state, world, Transcript(), "look around")
    assert "The Hall" in system
    assert "Characters present: The Ghost" in system
    # Absent NPCs must not be name-dropped, and their secrets must not leak.
    assert "The Warden" not in system
    assert "never once been lit" not in system  # a `hides` belonging to the Warden
    assert "The Tower" not in system  # a location two hops away


def test_present_npcs_bring_their_dm_only_notes(world, state):
    system, _ = context.build(state, world, Transcript(), "look")
    assert "The Ghost" in system
    assert "will deflect:" in system
    assert "moved the table itself" in system  # a `hides` entry


def test_inventory_and_traits_reach_the_prompt(world, state):
    delta = StateDelta(add_items=["lamp"], new_traits=["distrusts wizards"])
    new, _ = apply_delta(state, delta, world)
    system, _ = context.build(new, world, Transcript(), "go on")
    assert "a lamp" in system
    assert "distrusts wizards" in system


def test_taken_items_stop_being_listed_as_lying_around(world, state):
    system, _ = context.build(state, world, Transcript(), "look")
    assert "Items here (not yet taken): a lamp" in system

    taken, _ = apply_delta(state, StateDelta(add_items=["lamp"]), world)
    system, _ = context.build(taken, world, Transcript(), "look")
    assert "a lamp" not in system.split("Items here (not yet taken):")[1].split("\n")[0]


def test_the_narrator_is_never_shown_an_internal_id(world, state):
    """Observed live: the narrator ended its reply with
    `Exits: The Stair [stair], ...` — copying the scene block's
    scaffolding, ids and all, straight to the player. It never needed ids: it
    does not propose moves, the extractor does."""
    system, _ = context.build(state, world, Transcript(), "look")
    for location_id in world.locations:
        assert f"[{location_id}]" not in system
    assert "Exits: The Stair, The Yard" in system  # names, sorted, no ids


def test_the_extractor_still_gets_ids(world, state):
    """The ids moved, they did not disappear — the extractor's whole job is to
    return them."""
    from tests.stubs import StubClient

    from dungeon_master.llm.extractor import extract

    client = StubClient("{}")
    extract(client, world, state, "I go up", "You climb.")
    user = client.calls[0]["messages"][0]["content"]
    assert "stair" in user and "yard" in user


def test_item_canon_reaches_the_prompt(world, state):
    """Without this the narrator invents what a letter says — observed live."""
    system, _ = context.build(state, world, Transcript(), "I read the letter")
    assert "Folded twice, sealed with grey wax" in system  # description
    assert "Do not go up" in system  # notes — the actual contents


def test_carried_items_keep_their_canon_after_pickup(world, state):
    """A letter the player pocketed must still say the same thing later, even
    though it has left the scene's item list."""
    taken, _ = apply_delta(state, StateDelta(add_items=["letter"]), world)
    moved, _ = apply_delta(taken, StateDelta(move_to="yard"), world)

    system, _ = context.build(moved, world, Transcript(), "I reread the letter")
    assert "(carried)" in system
    assert "Do not go up" in system


def test_item_notes_stay_in_the_dm_only_section(world, state):
    system, _ = context.build(state, world, Transcript(), "look")
    # The phrase also appears in hard rule 6, so take the last segment.
    dm_only = system.split("DM-ONLY NOTES")[-1]
    # The lamp's one-night limit is a DM lever, not something to announce.
    assert "burns for exactly one night" in dm_only


def test_absent_items_bring_no_canon(world, state):
    system, _ = context.build(state, world, Transcript(), "look")
    assert "never once been lit" not in system  # the beacon, two rooms away


def test_relationship_renders_with_sign_and_note(world, state):
    delta = StateDelta(
        relationship_changes=[RelChange(npc_id="ghost", delta=15, note="listened to him")]
    )
    new, _ = apply_delta(state, delta, world)
    system, _ = context.build(new, world, Transcript(), "go on")
    assert "The Ghost: +25" in system  # 10 default + 15
    assert "listened to him" in system


def test_state_block_is_told_to_outrank_the_conversation(world, state):
    system, _ = context.build(state, world, Transcript(), "hi")
    assert "authoritative, overrides anything in the conversation" in system


def test_history_is_verbatim_and_summary_appears_when_present(world, state):
    transcript = Transcript(summary="The player argued with a Warden.")
    transcript.append("I go north", "You go north.")
    system, messages = context.build(state, world, transcript, "and then?")
    assert "STORY SO FAR" in system
    assert "argued with a Warden" in system
    assert messages == [
        {"role": "user", "content": "I go north"},
        {"role": "assistant", "content": "You go north."},
        {"role": "user", "content": "and then?"},
    ]


def test_player_input_is_always_last(world, state):
    transcript = Transcript()
    for i in range(20):
        transcript.append(f"turn {i}", "the sea continues")
    _, messages = context.build(state, world, transcript, "the newest thing")
    assert messages[-1] == {"role": "user", "content": "the newest thing"}


def test_budget_sheds_history_but_never_scene_or_state(world, state):
    held, _ = apply_delta(state, StateDelta(add_items=["lamp"]), world)
    transcript = Transcript(summary="x" * 4000)
    for i in range(30):
        transcript.append(f"player says something long {i} " * 40, "dm replies at length " * 60)

    system, messages = context.build(
        held, world, transcript, "what now?", budget_tokens=2500
    )
    # Narrative memory is lossy on purpose, so it is what gets spent first.
    assert len(messages) < 20
    # The correctness guarantee survives regardless.
    assert "CURRENT SCENE" in system
    assert "GAME STATE" in system
    assert "a lamp" in system


def test_build_is_pure_with_respect_to_state(world, state):
    before = state.model_copy(deep=True)
    context.build(state, world, Transcript(), "poke about")
    assert state == before
