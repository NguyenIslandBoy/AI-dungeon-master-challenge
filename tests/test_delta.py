"""apply_delta is the one thing that gets real unit tests: it is pure, it is the
containment boundary, and every rule in it exists because a model got it wrong."""

from __future__ import annotations

import pytest

from dungeon_master.state.models import RelChange, StateDelta
from dungeon_master.state.store import apply_delta


def test_empty_delta_is_idempotent(state, world):
    new, rejected = apply_delta(state, StateDelta(), world)
    assert new == state
    assert rejected == []


def test_legal_move_applies_and_records_visit(state, world):
    new, rejected = apply_delta(state, StateDelta(move_to="yard"), world)
    assert new.current_location == "yard"
    assert "yard" in new.visited
    assert rejected == []


def test_a_distant_move_walks_one_room_instead_of_being_refused(state, world):
    """The tower is two hops up. The intent is legitimate — the player simply
    cannot teleport — so they get as far as the stair.

    Refusing outright was the original behaviour and it stranded the story: the
    narrator went on describing a tower climb while state sat in the entrance."""
    new, rejected = apply_delta(state, StateDelta(move_to="tower"), world)
    assert new.current_location == "stair"
    assert new.visited == ["hall", "stair"]
    assert any("stepped to 'stair'" in r for r in rejected)


def test_a_genuinely_unreachable_move_is_still_refused(state, world):
    """The cellar exists and nothing leads to it. Stepping toward it is not a
    smaller version of going there — there is no first hop to take."""
    new, rejected = apply_delta(state, StateDelta(move_to="cellar"), world)
    assert new.current_location == state.current_location
    assert any("not reachable" in r for r in rejected)


def test_the_step_is_the_shortest_one(world):
    assert world.step_toward("hall", "tower") == "stair"  # hall -> stair -> tower
    assert world.step_toward("tower", "yard") == "stair"  # back down and across
    assert world.step_toward("hall", "yard") == "yard"  # already adjacent
    assert world.step_toward("hall", "cellar") is None  # nothing leads there
    assert world.step_toward("hall", "hall") is None


def test_unknown_location_is_rejected(state, world):
    new, rejected = apply_delta(state, StateDelta(move_to="atlantis"), world)
    assert new.current_location == state.current_location
    assert any("unknown location" in r for r in rejected)


def test_hallucinated_item_never_enters_inventory(state, world):
    """The classic failure mode: the narrator invents loot."""
    new, rejected = apply_delta(state, StateDelta(add_items=["greatsword"]), world)
    assert new.inventory == []
    assert any("unknown item" in r for r in rejected)


def test_known_item_is_added_once(state, world):
    once, _ = apply_delta(state, StateDelta(add_items=["lamp"]), world)
    twice, rejected = apply_delta(once, StateDelta(add_items=["lamp"]), world)
    assert twice.inventory == ["lamp"]
    assert any("already held" in r for r in rejected)


def test_out_of_scene_item_is_allowed_but_logged(state, world):
    """Decision 3: bible membership is the gate, scene presence is a warning —
    otherwise NPCs could never hand the player anything."""
    new, rejected = apply_delta(state, StateDelta(add_items=["journal"]), world)
    assert "journal" in new.inventory
    assert any("was not in scene" in r for r in rejected)


def test_removing_an_unheld_item_is_rejected(state, world):
    new, rejected = apply_delta(state, StateDelta(remove_items=["lamp"]), world)
    assert new.inventory == []
    assert any("not held" in r for r in rejected)


def test_disposition_clamps_at_both_ends(state, world):
    up = StateDelta(relationship_changes=[RelChange(npc_id="ghost", delta=10_000)])
    high, _ = apply_delta(state, up, world)
    assert high.relationships["ghost"].disposition == 100

    down = StateDelta(relationship_changes=[RelChange(npc_id="ghost", delta=-10_000)])
    low, _ = apply_delta(high, down, world)
    assert low.relationships["ghost"].disposition == -100


def test_relationship_seeds_from_world_default(state, world):
    delta = StateDelta(relationship_changes=[RelChange(npc_id="warden", delta=5)])
    new, _ = apply_delta(state, delta, world)
    # The warden starts at 20 in the bible, so one +5 lands at 25, not 5.
    assert new.relationships["warden"].disposition == 25


def test_unknown_npc_relationship_is_rejected(state, world):
    delta = StateDelta(relationship_changes=[RelChange(npc_id="gandalf", delta=5)])
    new, rejected = apply_delta(state, delta, world)
    assert new.relationships == {}
    assert any("unknown npc" in r for r in rejected)


def test_unknown_quest_stage_is_rejected(state, world):
    delta = StateDelta(quest_updates={"q_light": "victory_parade"})
    new, rejected = apply_delta(state, delta, world)
    assert new.quest_flags["q_light"] == "unaware"
    assert any("unknown stage" in r for r in rejected)


def test_valid_quest_stage_applies(state, world):
    delta = StateDelta(quest_updates={"q_light": "seen"})
    new, rejected = apply_delta(state, delta, world)
    assert new.quest_flags["q_light"] == "seen"
    assert rejected == []


def test_traits_and_facts_deduplicate(state, world):
    delta = StateDelta(new_traits=["distrusts wizards"], new_facts=["the stove is cold"])
    once, _ = apply_delta(state, delta, world)
    twice, _ = apply_delta(once, StateDelta(new_traits=["Distrusts Wizards"]), world)
    assert twice.player_traits == ["distrusts wizards"]
    assert twice.established_facts == ["the stove is cold"]


def test_rephrased_facts_are_recognised_as_duplicates(state, world):
    """These three came out of one real 2-turn session. The first and third are
    the same claim, and the ledger is injected in full every turn."""
    observed = [
        "the beacon has turned every night for eleven years without being lit",
        "the hall has not had a fire in 11 years",
        "the beacon above has turned steadily for 11 years",
    ]
    new, _ = apply_delta(state, StateDelta(new_facts=observed), world)
    assert len(new.established_facts) == 2
    assert "the beacon above has turned steadily for 11 years" not in new.established_facts


def test_distinct_facts_are_both_kept(state, world):
    delta = StateDelta(
        new_facts=[
            "the cellar door has been forced open",
            "the warden agreed to meet the player at dusk",
        ]
    )
    new, _ = apply_delta(state, delta, world)
    assert len(new.established_facts) == 2


def test_traits_survive_rewording_without_stacking(state, world):
    once, _ = apply_delta(state, StateDelta(new_traits=["distrusts wizards"]), world)
    twice, _ = apply_delta(once, StateDelta(new_traits=["Distrusts Wizards."]), world)
    assert twice.player_traits == ["distrusts wizards"]


def test_facts_are_capped(state, world):
    delta = StateDelta(new_facts=[f"fact {i}" for i in range(50)])
    new, _ = apply_delta(state, delta, world)
    assert len(new.established_facts) == 20
    assert new.established_facts[-1] == "fact 49"  # most recent survive


def test_delta_does_not_mutate_the_input_state(state, world):
    before = state.model_copy(deep=True)
    apply_delta(state, StateDelta(move_to="yard", add_items=["lamp"]), world)
    assert state == before
