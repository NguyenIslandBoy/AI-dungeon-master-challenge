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
