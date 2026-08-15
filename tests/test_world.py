"""The bible must fail loudly at load time, before play — per the boot sketch."""

from __future__ import annotations

import textwrap

import pytest
import yaml

from dungeon_master.world.loader import WorldValidationError, load_world

MINIMAL = """
meta:
  name: Test
  start_location: hall
  tone: terse
  opening_scene: You are here.
locations:
  hall:
    name: Hall
    description: A hall.
    exits: [cellar]
    npcs: [ghost]
    items: [lamp]
  cellar:
    name: Cellar
    description: A cellar.
    exits: [hall]
npcs:
  ghost:
    name: Ghost
    role: haunts
    faction: dead
items:
  lamp:
    name: a lamp
    description: it glows
factions:
  dead:
    name: The Dead
quests:
  q1:
    name: Q
    summary: s
    stages: {open: o, shut: c}
    start: open
"""


def _write(tmp_path, mutate=None):
    data = yaml.safe_load(MINIMAL)
    if mutate:
        mutate(data)
    path = tmp_path / "world.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_shipped_world_loads_and_validates():
    world = load_world()
    assert world.meta.start_location in world.locations
    assert world.locations and world.npcs and world.items and world.quests


def test_shipped_world_stays_within_budget():
    """CLAUDE.md caps the world at roughly 6 locations / 6 NPCs / 8 items /
    2 factions / 2 quests. Depth beats breadth, and the context builder only
    stays small if the world does."""
    world = load_world()
    assert len(world.locations) <= 6
    assert len(world.npcs) <= 6
    assert len(world.items) <= 9
    assert len(world.factions) <= 2
    assert len(world.quests) <= 2


def test_shipped_world_is_authored_for_the_prompt_blocks():
    """Empty `secrets` or `hides` are silently allowed by the schema, and a
    location or character with none contributes nothing to DM-ONLY NOTES — the
    fields that do most of the work of making the DM feel like it knows more
    than it says."""
    world = load_world()
    for loc_id, loc in world.locations.items():
        assert loc.secrets, f"{loc_id} has no secrets"
    for npc_id, npc in world.npcs.items():
        assert npc.wants, f"{npc_id} has no wants"
        assert npc.knows, f"{npc_id} has no knows"
        assert npc.hides, f"{npc_id} has no hides"


def test_every_shipped_location_is_reachable_from_the_start():
    """A room nothing leads to can never be played. The loader validates that
    exits resolve, which does not catch an island."""
    world = load_world()
    start = world.meta.start_location
    seen, queue = {start}, [start]
    while queue:
        for nxt in world.locations[queue.pop()].exits:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    assert seen == set(world.locations), f"unreachable: {set(world.locations) - seen}"


def test_minimal_world_is_valid(tmp_path):
    assert load_world(_write(tmp_path)).meta.name == "Test"


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda d: d["locations"]["hall"]["exits"].append("void"), "unknown location 'void'"),
        (lambda d: d["locations"]["hall"]["npcs"].append("nobody"), "unknown npc 'nobody'"),
        (lambda d: d["locations"]["hall"]["items"].append("sword"), "unknown item 'sword'"),
        (lambda d: d["npcs"]["ghost"].update(faction="cult"), "unknown faction 'cult'"),
        (lambda d: d["quests"]["q1"].update(start="ajar"), "unknown stage 'ajar'"),
        (lambda d: d["meta"].update(start_location="mars"), "unknown location 'mars'"),
    ],
)
def test_dangling_references_raise(tmp_path, mutate, expected):
    with pytest.raises(WorldValidationError, match=expected):
        load_world(_write(tmp_path, mutate))


def test_every_bad_reference_is_reported_at_once(tmp_path):
    def mutate(d):
        d["locations"]["hall"]["exits"].append("void")
        d["locations"]["hall"]["npcs"].append("nobody")
        d["locations"]["hall"]["items"].append("sword")

    with pytest.raises(WorldValidationError) as excinfo:
        load_world(_write(tmp_path, mutate))
    # Fixing six broken ids one reload at a time is the slow path.
    assert str(excinfo.value).count("- ") >= 3


def test_scene_returns_only_what_is_present(tmp_path):
    world = load_world(_write(tmp_path))
    scene = world.scene("hall")
    assert set(scene.npcs) == {"ghost"}
    assert set(scene.items) == {"lamp"}
    assert scene.exits == {"cellar": "Cellar"}


def test_adjacency(tmp_path):
    world = load_world(_write(tmp_path))
    assert world.is_adjacent("hall", "cellar")
    assert not world.is_adjacent("cellar", "mars")
