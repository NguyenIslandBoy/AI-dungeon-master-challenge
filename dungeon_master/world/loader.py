"""Static world canon. Loaded once, never mutated at runtime."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

WORLD_PATH = Path(__file__).parent / "world.yaml"


class WorldValidationError(Exception):
    """Raised at load time with *every* bad reference, not just the first."""


class Meta(BaseModel):
    name: str
    start_location: str
    tone: str
    opening_scene: str


class Location(BaseModel):
    name: str
    description: str
    exits: list[str] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)


class NPC(BaseModel):
    name: str
    role: str
    faction: str | None = None
    default_disposition: int = 0
    wants: str = ""
    knows: list[str] = Field(default_factory=list)
    hides: list[str] = Field(default_factory=list)


class Item(BaseModel):
    name: str
    description: str
    notes: str = ""


class Faction(BaseModel):
    name: str
    creed: str = ""
    wants: str = ""
    known_for: str = ""


class Quest(BaseModel):
    name: str
    summary: str
    stages: dict[str, str]
    start: str


class Scene(BaseModel):
    """The slice of canon injected for one turn. Never the whole world."""

    location_id: str
    location: Location
    exits: dict[str, str]  # location_id -> display name
    npcs: dict[str, NPC]
    items: dict[str, Item]


class World(BaseModel):
    meta: Meta
    history: list[str] = Field(default_factory=list)
    factions: dict[str, Faction] = Field(default_factory=dict)
    locations: dict[str, Location]
    npcs: dict[str, NPC] = Field(default_factory=dict)
    items: dict[str, Item] = Field(default_factory=dict)
    quests: dict[str, Quest] = Field(default_factory=dict)

    def scene(self, location_id: str) -> Scene:
        loc = self.locations[location_id]
        return Scene(
            location_id=location_id,
            location=loc,
            exits={e: self.locations[e].name for e in loc.exits},
            npcs={n: self.npcs[n] for n in loc.npcs},
            items={i: self.items[i] for i in loc.items},
        )

    def is_adjacent(self, src: str, dst: str) -> bool:
        return dst in self.locations.get(src, Location(name="", description="")).exits


def _check_references(world: World) -> list[str]:
    """Collect every dangling id. Returning all of them beats first-fail —
    fixing six broken references one reload at a time is the slow path."""
    errors: list[str] = []

    if world.meta.start_location not in world.locations:
        errors.append(f"meta.start_location -> unknown location '{world.meta.start_location}'")

    for loc_id, loc in world.locations.items():
        for exit_id in loc.exits:
            if exit_id not in world.locations:
                errors.append(f"locations.{loc_id}.exits -> unknown location '{exit_id}'")
        for npc_id in loc.npcs:
            if npc_id not in world.npcs:
                errors.append(f"locations.{loc_id}.npcs -> unknown npc '{npc_id}'")
        for item_id in loc.items:
            if item_id not in world.items:
                errors.append(f"locations.{loc_id}.items -> unknown item '{item_id}'")

    for npc_id, npc in world.npcs.items():
        if npc.faction is not None and npc.faction not in world.factions:
            errors.append(f"npcs.{npc_id}.faction -> unknown faction '{npc.faction}'")

    for quest_id, quest in world.quests.items():
        if quest.start not in quest.stages:
            errors.append(f"quests.{quest_id}.start -> unknown stage '{quest.start}'")

    return errors


def load_world(path: Path = WORLD_PATH) -> World:
    """Parse and validate the world bible. Fails loudly, before play begins."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    world = World.model_validate(raw)
    if errors := _check_references(world):
        listed = "\n  - ".join(errors)
        raise WorldValidationError(f"{path.name} has broken references:\n  - {listed}")
    return world
