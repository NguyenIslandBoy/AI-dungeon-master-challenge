"""Prompt assembly. Rebuilt from scratch every turn — never accumulated.

Order is deliberate: stable content first (cache-friendly), volatile content last
(recency). The conversation history is never the source of truth for anything
mechanical; it is flavour, and GAME STATE is told to outrank it.
"""

from __future__ import annotations

from .llm import prompts
from .memory.transcript import VERBATIM_TURNS, Transcript
from .state.models import GameState
from .world.loader import World

BUDGET_TOKENS = 6000
NONE = "(none)"


def _tokens(text: str) -> int:
    """Coarse estimate. The cap is a safety valve, not an accounting system —
    not worth a tokenizer dependency or the wrong-tokenizer-per-model problem."""
    return len(text) // 4


def _join(values, empty: str = NONE) -> str:
    return ", ".join(values) if values else empty


def _sentences(values, empty: str = NONE) -> str:
    """Join hand-authored sentences without running full stops into commas."""
    cleaned = [v.strip().rstrip(".") for v in values if v.strip()]
    return "; ".join(cleaned) if cleaned else empty


def render_scene(world: World, state: GameState) -> str:
    """Only the current location and what is in it. Injecting the whole world is
    both wasteful and a consistency hazard — the model will name-drop a character
    the player has never met."""
    scene = world.scene(state.current_location)
    held = set(state.inventory)

    npc_notes = "\n".join(
        prompts.NPC_NOTE.format(
            name=npc.name,
            role=npc.role,
            faction=f", {world.factions[npc.faction].name}" if npc.faction else "",
            wants=npc.wants.strip(),
            knows=_sentences(npc.knows),
            hides=_sentences(npc.hides),
        )
        for npc in scene.npcs.values()
    )

    return prompts.SCENE_BLOCK.format(
        location_name=scene.location.name,
        description=scene.location.description.strip(),
        exits=_join([f"{name} [{lid}]" for lid, name in scene.exits.items()]),
        npcs=_join([n.name for n in scene.npcs.values()]),
        items=_join([i.name for iid, i in scene.items.items() if iid not in held]),
        secrets="\n".join(f"- {s.strip()}" for s in scene.location.secrets) or f"- {NONE}",
        npc_notes=f"\n{npc_notes}" if npc_notes else "",
    )


def render_state(world: World, state: GameState) -> str:
    """Compact prose-ish lines, never a raw JSON dump — models read prose better
    and the result is legible in the log."""
    relationships = [
        f"{world.npcs[nid].name}: {rel.disposition:+d}"
        + (f" ({'; '.join(rel.notes)})" if rel.notes else "")
        for nid, rel in state.relationships.items()
        if nid in world.npcs
    ]
    quests = [
        f"{world.quests[qid].name}: {world.quests[qid].stages.get(stage, stage)}"
        for qid, stage in state.quest_flags.items()
        if qid in world.quests
    ]
    return prompts.STATE_BLOCK.format(
        location=world.locations[state.current_location].name,
        inventory=_join([world.items[i].name for i in state.inventory if i in world.items]),
        visited=_join([world.locations[v].name for v in state.visited if v in world.locations]),
        relationships=_join(relationships),
        quests=_join(quests),
        traits=_join(state.player_traits),
        facts=_join(state.established_facts),
        turn=state.turn_count,
    )


def build_system(world: World, state: GameState) -> str:
    history = "\n".join(f"- {h.strip()}" for h in world.history)
    sections = [
        prompts.DM_SYSTEM.format(
            world_name=world.meta.name,
            tone=world.meta.tone.strip(),
            world_section=prompts.WORLD_SECTION.format(history=history),
        ),
        render_scene(world, state),
        render_state(world, state),
    ]
    return "\n\n".join(sections)


def build(
    state: GameState,
    world: World,
    transcript: Transcript,
    player_input: str,
    *,
    budget_tokens: int = BUDGET_TOKENS,
) -> tuple[str, list[dict]]:
    """Assemble one turn's prompt.

    Truncation priority when over budget: drop the oldest verbatim turns first,
    then trim the summary, and never touch the scene or state blocks. Those two
    are the correctness guarantee; narrative memory is lossy on purpose, so it is
    the right thing to spend first.
    """
    system = build_system(world, state)
    keep = VERBATIM_TURNS
    summary = transcript.summary

    while True:
        story = prompts.STORY_SO_FAR.format(summary=summary) if summary else ""
        full_system = f"{system}\n\n{story}" if story else system
        messages = [
            *transcript.as_messages(keep),
            {"role": "user", "content": player_input},
        ]
        total = _tokens(full_system) + sum(_tokens(m["content"]) for m in messages)

        if total <= budget_tokens:
            return full_system, messages
        if keep > 2:
            keep -= 2
        elif summary:
            summary = summary[: len(summary) // 2]
        else:
            return full_system, messages  # scene + state alone; nothing left to cut
