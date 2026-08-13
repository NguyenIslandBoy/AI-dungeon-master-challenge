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
git clone <repo> && cd AI-dungeon-master-challenge
cp .env.example .env          # paste your Novita API key
uv sync
uv run python -m dungeon_master.cli
```

Get a key at [novita.ai](https://novita.ai/settings/key-management). The app
uses Novita's OpenAI-compatible endpoint, so any OpenAI-compatible provider works
by changing `NOVITA_BASE_URL`.

Model ids are configuration, never constants — Novita rotates its catalog and
the display names on the website are not API ids. If a default has been retired:

```bash
uv run python -m dungeon_master.cli --models   # list what is actually served
uv run pytest -q                               # 54 tests, no network required
```

### In-game commands

| Command | Effect |
|---|---|
| `/state` | Dump current game state — inventory, relationships, quests, traits |
| `/save` `/load` | Manual save slot (autosaves every turn regardless) |
| `/quit` | Exit |

---

## A sample turn

<!-- ⚠️ PLACEHOLDER — replace with a REAL captured transcript before submitting.
     Do not hand-write one; play it and paste it. Run the demo script in
     docs/EXECUTION_PLAN.md §8, which is designed to show, in order:
       1. an early stated preference being recorded as a trait
       2. that trait visibly shaping a later scene (meet Tallow the hedge-wizard)
       3. /state proving inventory + location + relationships are exact
       4. a hallucinated item being rejected — grep game.log for "rejected —"
     Aim for ~15 lines. Trim the middle, never the /state dump. -->

_To be captured from a real playthrough — see the demo script in
[`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md) §8._

---

## Architecture

```
   player input ───►  Game Loop (cli.py) ───► Context Builder (context.py)
                                                       │
        ┌──────────────────────────────────────────────┼───────────────────────┐
        │                                              │                       │
┌───────▼────────┐                    ┌────────────────▼───┐      ┌────────────▼───────┐
│  World Bible   │                    │    Game State      │      │  Narrative Memory  │
│    STATIC      │                    │    STRUCTURED      │      │     EPISODIC       │
│                │                    │                    │      │                    │
│ locations      │                    │ current_location   │      │ rolling summary    │
│ NPCs, factions │                    │ inventory[]        │      │ last 8 turns       │
│ items, history │                    │ relationships{}    │      │   (verbatim)       │
│ quests, lore   │                    │ quest_flags{}      │      │                    │
│                │                    │ player_traits[]    │      │                    │
│ world.yaml     │                    │ established_facts[]│      │                    │
│ never mutated  │                    │ save.json          │      │ lossy, compressed  │
└───────┬────────┘                    └─────────▲──────────┘      └─────────▲──────────┘
        │                                       │                           │
  keyed lookup:                            apply_delta()              append + compress
  current loc + exits                    validate → reject → apply      every 8 turns
  + entities present                          │                           │
        └───────────────────────────────────────┼───────────────────────────┘
                                                │
                             Narrator ──► prose to player (streamed)
                                                │
                             Extractor ──► StateDelta (JSON) ──┘
```

Three memory tiers. A **world bible** (`world.yaml`) holds static canon and is
never mutated; only the current scene is injected. **Game state** is structured,
mutable, and small enough to inject in full every turn — this is what makes
progress exact. **Narrative memory** keeps the last 8 turns verbatim plus a
rolling summary of everything older, and is deliberately lossy: nothing
mechanically important lives there.

Each turn runs two model calls. The narrator streams prose; a second, cheaper
call converts `(state, input, narration)` into a `StateDelta`. That delta is
validated against the world bible before being applied — unknown items and
illegal moves are rejected and logged, never surfaced. The model proposes; the
code decides.

Full detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Trade-off log in
[`docs/DECISIONS.md`](docs/DECISIONS.md).

---

## The core decision: code owns state, the LLM owns prose

A naive DM appends every turn to a message list and tells the model "stay
consistent." That works for about ten turns and then fails in predictable ways:
items the player never picked up appear in inventory, dead NPCs come back, the
player is described in a location they left three turns ago, early declarations
are forgotten.

The cause is always the same — **state was stored as prose inside a growing
context window**, so recall is probabilistic and degrades with distance.

So the split is hard:

- **Structured state** — inventory, location, relationships, quest flags, player
  traits. Owned by code, mutated only by validated deltas, injected in full every
  turn. Exact.
- **Narrative memory** — mood, texture, what things looked like. Lossy,
  compressed, approximate.

Nothing that affects what the player *can do* is allowed to live only in prose.
The state block in every prompt is explicitly labelled *authoritative, overrides
anything in the conversation* — if the story so far contradicts it, the story is
wrong.

### Why this matters more on open-weight models

The narrator runs on an open-weight model via Novita. Those follow instructions
less reliably than frontier models: the DM's six hard rules *will* occasionally
be violated, and the word limit *will* occasionally be overrun.

That is survivable, and by design. Even when the narration invents a sword, it
never enters the inventory — the extractor must propose a delta, and that delta
must reference an item id that exists in the bible. `apply_delta()` is the
containment boundary, and it is load-bearing rather than decorative.

**Model quality is not a correctness dependency here.** Swapping in a weaker,
cheaper model degrades prose. It does not corrupt the game. That property is the
whole reason the architecture is shaped this way, and it is directly testable —
see `tests/test_turn_loop.py::test_a_short_playthrough_keeps_state_exact`, where
the stubbed narrator hallucinates both a greatsword and a shortcut to a
non-adjacent room, and neither survives the turn.

---

## Memory tiering: what lives where, and why nothing is duplicated

| Tier | Contents | Mutability | Injection |
|---|---|---|---|
| World bible | locations, NPCs, items, factions, history, quests | Never mutated | Current scene only — never the whole world |
| Game state | location, inventory, relationships, quest stages, traits, established facts | Validated deltas only | In full, every turn |
| Narrative memory | last 8 turns verbatim + rolling digest | Append + periodic compression | Recent turns as messages; digest in the system prompt |

Two rules keep the tiers from fighting:

1. **The bible is injected selectively.** Only the current location, its exits,
   and the entities actually present. Dumping the whole world is both wasteful
   and a consistency hazard — the model will name-drop a character the player has
   never met.
2. **The summariser is explicitly told to omit anything structured state already
   owns.** No inventory, no location, no quest stages. Two versions of the same
   fact can disagree, and when they do, the prose version is the one that's wrong.

`player_traits` deserves a mention: it is exactly the brief's worked example
("I don't trust wizards" → the village mage notices your hesitation). Keeping it
as a structured field rather than hoping the summariser preserved it is the
difference between that feature working reliably and working sometimes.

`established_facts` is the anti-contradiction ledger — when the DM invents
something not in the bible, it is recorded and injected from then on.

---

## Trade-offs

### State extraction: two-pass, not tool calling

| Option | Pro | Con | Verdict |
|---|---|---|---|
| Single call returning `{narration, delta}` | One round trip, cheapest | Can't stream cleanly; mixing creative and analytical work degrades both | Rejected |
| Tool calling on the narrator | Idiomatic "agent" design | Open-weight models silently skip calls for subtle changes like disposition shifts; still needs a validation pass | Viable, on-theme |
| **Two-pass** | Reliable, clean separation, cheap model for pass two, latency hidden by streaming | One extra call per turn | **Chosen** |

Two-pass gets *stronger* on open-weight models than it would on a frontier
provider. Asking a mid-size model to write good prose **and** emit valid
structured JSON in one generation degrades both noticeably. Splitting the jobs
lets each model do one thing, and lets the extractor run on a model costing
roughly `$0.07/M` input tokens — about a 10–20× saving versus a frontier
provider, which is what makes a second call per turn obviously correct rather
than a luxury.

Tool calling is the more "agentic" answer and would be the first thing I tried
with more time — as a *supplement* to extraction, not a replacement.

### Two model roles is not multi-model routing

The narrator and extractor are two fixed roles with two `.env` defaults. There is
no router, no fallback chain, no per-request model selection. If the cheap
extractor turns out to emit unreliable JSON, the fix is
`EXTRACTOR_MODEL=$NARRATOR_MODEL` — a config change with zero code impact.

### Everything else

The remaining trade-offs are logged one line each in
[`docs/DECISIONS.md`](docs/DECISIONS.md): why bad deltas are dropped rather than
raised, why an added item must exist in the bible but need not be in the current
scene, what gets truncated first when the context budget is hit, and why the
token estimate is `len // 4` rather than a real tokenizer.

---

## What I deliberately did not build

| Not built | Why |
|---|---|
| Vector DB / RAG | ~25 world entities. A keyed dict lookup is exact, instant, and debuggable. Embedding similarity would be strictly worse at "which NPCs are in this room" |
| LangChain / agent frameworks | They hide context assembly — the exact thing this challenge is about. `context.py` is 140 lines and every one of them is inspectable |
| Web UI | The brief says the frontend is not the focus |
| Combat, dice, stats, XP | A rabbit hole, and nothing in the brief asks for it |
| Async extraction | Streaming already hides the extractor's latency behind reading time. Async would add concurrency bugs to buy something the player cannot perceive |
| Multi-model routing | See above — two fixed roles, no router |

---

## Known limitations

Honest list:

- The extractor can miss subtle relationship shifts a human DM would register.
- The summariser is lossy by design. A detail that mattered emotionally but was
  never captured as a fact or a trait can be lost.
- The DM can still narrate *around* an entity it shouldn't — implying someone
  upstairs who isn't defined. Hard rule 1 mitigates this but does not eliminate it.
- Open-weight narrators break the word limit and occasionally slip out of second
  person. Contained, not eliminated — and contained is the design goal.
- Single player, single save slot, no concurrency. Deliberate.
- Model defaults may go stale as Novita rotates its catalog; `--models` is the
  escape hatch.
- **Narration quality is not tested.** Asserting on prose with string matching is
  brittle and proves little. The right instrument is an eval harness — see below.

---

## What I'd do with another day

1. **An eval harness.** Replay a fixed 30-turn transcript against the real models
   and assert on *final state*, not on prose. That is the honest way to test a DM,
   and it turns "the architecture is robust" from a claim into a measurement.
2. **A canon validator on the narration itself** — a cheap post-hoc check that the
   prose only referenced entities in the injected scene, logged as a per-model
   adherence score. It would make the open-weight trade-off visible as a number.
3. **Tool calling as a supplement to extraction**, so unambiguous actions (take,
   move, give) come back as structured calls and the extractor only handles the
   subtle work like disposition shifts.
4. **NPC-scoped memory** — modelling what each character actually *witnessed*
   rather than what the player did. The Wrecker should not know about a
   conversation held in the lamp room.
5. **Richer relationship modelling.** A single disposition integer is coarse;
   trust, fear, and respect are separable and would make the Reach's factions
   behave more distinctly.

---

## Layout

```
dungeon_master/
  world/       world.yaml (static canon) + loader with reference validation
  state/       models.py (GameState, StateDelta), store.py (pure apply_delta)
  memory/      transcript.py (turn buffer), summarizer.py (rolling digest)
  llm/         client.py, prompts.py, narrator.py, extractor.py
  context.py   prompt assembly
  game.py      one turn of the lifecycle, no I/O
  cli.py       game loop, the only module that prints
tests/         54 tests, no network required
docs/          ARCHITECTURE.md, DECISIONS.md, PLAN.md, EXECUTION_PLAN.md
```

All prompts live in `llm/prompts.py` — nothing is inlined elsewhere. They are the
artefact worth reading most closely.
