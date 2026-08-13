"""Tier 3: episodic memory. Lossy by design — nothing mechanical lives here."""

from __future__ import annotations

from pydantic import BaseModel, Field

VERBATIM_TURNS = 8


class Turn(BaseModel):
    player: str
    dm: str


class Transcript(BaseModel):
    turns: list[Turn] = Field(default_factory=list)
    summary: str = ""
    compressed_through: int = 0  # index of the last turn folded into `summary`

    def append(self, player: str, dm: str) -> None:
        self.turns.append(Turn(player=player, dm=dm))

    def last_n(self, n: int = VERBATIM_TURNS) -> list[Turn]:
        return self.turns[-n:]

    def pending_compression(self, keep: int = VERBATIM_TURNS) -> list[Turn]:
        """Turns old enough to fall out of the verbatim window but not yet summarised."""
        cutoff = max(0, len(self.turns) - keep)
        return self.turns[self.compressed_through : cutoff]

    def as_messages(self, n: int = VERBATIM_TURNS) -> list[dict]:
        messages: list[dict] = []
        for turn in self.last_n(n):
            messages.append({"role": "user", "content": turn.player})
            messages.append({"role": "assistant", "content": turn.dm})
        return messages
