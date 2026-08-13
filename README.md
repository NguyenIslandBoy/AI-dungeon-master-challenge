# AI Dungeon Master

A CLI text adventure where a language model narrates a small fantasy world, and
**the application owns the game state**.

The core idea: the model never *holds* state. It narrates *given* state, and
*proposes* changes to it. Every turn the prompt is rebuilt from a structured
`GameState` rather than trusting the conversation history to have remembered
anything. Inventory, location, relationships, and quest progress are exact —
not recalled.

---

## Running it

```bash
git clone <repo> && cd dungeon-master
cp .env.example .env          # paste your Novita API key
uv sync
uv run python -m dungeon_master.cli
```

Get a key at [novita.ai](https://novita.ai). The app uses Novita's
OpenAI-compatible endpoint, so any OpenAI-compatible provider works by changing
`NOVITA_BASE_URL`.

If a default model id has been retired, list what's currently available:

```bash
uv run python -m dungeon_master.cli --models
```

### In-game commands

| Command | Effect |
|---|---|
| `/state` | Dump current game state (inventory, relationships, quests) |
| `/save` `/load` | Manual save slot (autosaves every turn regardless) |
| `/quit` | Exit |

---

## Architecture in one paragraph

Three memory tiers. A **world bible** (`world.yaml`) holds static canon and is
never mutated; only the current scene is injected. **Game state** is structured,
mutable, and small enough to inject in full every turn — this is what makes
progress exact. **Narrative memory** keeps the last few turns verbatim plus a
rolling summary of everything older, and is deliberately lossy: nothing
mechanically important lives there.

Each turn runs two model calls. The narrator streams prose; a second, cheaper
call converts `(state, input, narration)` into a `StateDelta`. That delta is
validated against the world bible before being applied — unknown items and
illegal moves are rejected and logged, never surfaced. The model proposes; the
code decides.

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Layout

```
dungeon_master/
  world/       static canon + loader with reference validation
  state/       GameState, StateDelta, pure apply_delta()
  memory/      turn buffer, rolling summarizer
  llm/         client, prompts, narrator, extractor
  context.py   prompt assembly
  cli.py       game loop
```

---

## Status

Work in progress. See [`docs/PLAN.md`](docs/PLAN.md).

- [ ] World bible
- [ ] State layer + delta validation
- [ ] Context builder + narrator
- [ ] Extractor + loop closure
- [ ] CLI polish
- [ ] Full write-up: trade-offs, limitations, next steps

<!-- TODO before submission:
     - sample transcript showing memory working
     - architecture diagram
     - what I deliberately did not build, and why
     - known limitations
     - what I would do with another day
-->
