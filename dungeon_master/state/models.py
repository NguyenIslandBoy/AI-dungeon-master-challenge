"""The structured half of the split: exact, mutable, owned by code.

Nothing that affects what the player *can do* is allowed to live only in prose.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_FACTS = 20
MAX_TRAITS = 10
MAX_NOTES_PER_NPC = 5


class Relationship(BaseModel):
    npc_id: str
    disposition: int = 0  # -100..100
    notes: list[str] = Field(default_factory=list)


class GameState(BaseModel):
    current_location: str
    visited: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)  # item ids, validated against the bible
    relationships: dict[str, Relationship] = Field(default_factory=dict)
    quest_flags: dict[str, str] = Field(default_factory=dict)  # quest_id -> stage id
    established_facts: list[str] = Field(default_factory=list)  # DM assertions it must honour
    player_traits: list[str] = Field(default_factory=list)  # "distrusts wizards"
    turn_count: int = 0
    # Corrections owed to the narrator because last turn's prose described
    # something the validator refused. Injected once, then replaced.
    pending_corrections: list[str] = Field(default_factory=list)


class RelChange(BaseModel):
    npc_id: str
    delta: int = 0
    note: str = ""


class StateDelta(BaseModel):
    """What the extractor proposes. Every field is a proposal, not a command —
    `apply_delta` decides what survives."""

    move_to: str | None = None
    add_items: list[str] = Field(default_factory=list)
    remove_items: list[str] = Field(default_factory=list)
    relationship_changes: list[RelChange] = Field(default_factory=list)
    quest_updates: dict[str, str] = Field(default_factory=dict)
    new_facts: list[str] = Field(default_factory=list)
    new_traits: list[str] = Field(default_factory=list)
    reasoning: str = ""  # one line, for the debug log
