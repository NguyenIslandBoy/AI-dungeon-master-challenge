"""Every LLM output is untrusted input. These are the shapes models actually emit."""

from __future__ import annotations

import pytest

from dungeon_master.llm.extractor import extract, parse_delta
from dungeon_master.state.store import apply_delta
from tests.stubs import StubClient

VALID = '{"add_items": ["lamp"], "new_traits": ["distrusts wizards"]}'


@pytest.mark.parametrize(
    "raw",
    [
        VALID,
        f"```json\n{VALID}\n```",
        f"```\n{VALID}\n```",
        f"Here is the delta:\n```json\n{VALID}\n```\nHope that helps!",
        f"  \n {VALID}  \n",
    ],
)
def test_fences_and_chatter_are_stripped(raw):
    delta = parse_delta(raw)
    assert delta.add_items == ["lamp"]
    assert delta.new_traits == ["distrusts wizards"]


def test_unparseable_output_raises_a_feedable_error():
    with pytest.raises(ValueError):
        parse_delta("I'm afraid I can't do that, Dave.")


def test_empty_delta_is_valid():
    assert parse_delta("{}").model_dump(exclude_defaults=True) == {}


def test_extract_returns_a_delta(world, state):
    client = StubClient(f"```json\n{VALID}\n```")
    delta = extract(client, world, state, "I take the key", "The key is cold.")
    assert delta is not None
    assert delta.add_items == ["lamp"]


def test_extract_retries_once_then_succeeds(world, state):
    client = StubClient("not json at all", VALID)
    delta = extract(client, world, state, "I take the key", "The key is cold.")
    assert delta is not None and delta.add_items == ["lamp"]
    assert len(client.calls) == 2
    assert "could not be parsed" in client.calls[1]["messages"][-1]["content"]


def test_extract_gives_up_gracefully_rather_than_crashing(world, state):
    client = StubClient("garbage", "still garbage")
    assert extract(client, world, state, "I take the key", "The key is cold.") is None


def test_extractor_is_told_only_the_reachable_exits(world, state):
    client = StubClient(VALID)
    extract(client, world, state, "I go up", "You climb.")
    user = client.calls[0]["messages"][0]["content"]
    assert "reachable from here: stair, yard" in user
    assert "tower" not in user.split("reachable from here:")[1].split("\n")[0]


def test_hallucinated_delta_survives_parsing_but_dies_at_apply(world, state):
    """The two validation layers do different jobs: pydantic checks shape,
    apply_delta checks canon. This is the containment boundary end to end."""
    delta = parse_delta('{"add_items": ["excalibur"], "move_to": "mount_doom"}')
    assert delta.add_items == ["excalibur"]  # shape is fine

    new, rejected = apply_delta(state, delta, world)
    assert new.inventory == []
    assert new.current_location == state.current_location
    assert len(rejected) == 2
