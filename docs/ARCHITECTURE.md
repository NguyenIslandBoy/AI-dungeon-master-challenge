# Architecture

Read this before touching `context.py`, `state/`, or `llm/`.

---

## 1. The core problem

A naive DM appends every turn to a message list and tells the model "stay
consistent." This works for ~10 turns and then degrades in predictable ways:

- Items the player never picked up appear in their inventory.
- Dead NPCs come back.
- The player is described as being in a location they left three turns ago.
- Early declarations ("I don't trust wizards") are forgotten.

The cause is the same in every case: **state was stored as prose inside a growing
context window**, so recall is probabilistic and degrades with distance.

The fix is a hard split:

- **Structured state** — inventory, location, relationships, quest flags. Owned by
  code, mutated by explicit deltas, injected in full every turn. Exact.
- **Narrative memory** — mood, texture, what things looked like. Lossy, compressed,
  approximate. Nothing mechanically important lives here.

Nothing that affects what the player *can do* is allowed to live only in prose.

---

## 2. Component diagram

```
                    ┌──────────────────────────────┐
   player input ───►│      Game Loop (cli.py)      │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │   Context Builder            │
                    │   (context.py)               │
                    └──────────────┬───────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
┌───────▼────────┐      ┌──────────▼─────────┐     ┌──────────▼─────────┐
│  World Bible   │      │    Game State      │     │  Narrative Memory  │
│    STATIC      │      │    STRUCTURED      │     │     EPISODIC       │
│                │      │                    │     │                    │
│ locations      │      │ current_location   │     │ rolling summary    │
│ NPCs           │      │ inventory[]        │     │ last N turns       │
│ factions       │      │ visited[]          │     │   (verbatim)       │
│ items          │      │ relationships{}    │     │                    │
│ history/lore   │      │ quest_flags{}      │     │                    │
│                │      │ established_facts[]│     │                    │
│ world.yaml     │      │ turn_count         │     │                    │
│ never mutated  │      │ save.json          │     │ lossy, compressed  │
└───────┬────────┘      └──────────▲─────────┘     └──────────▲─────────┘
        │                          │                          │
   keyed lookup:              apply_delta()              append + compress
   current loc + exits             │                     every N turns
   + NPCs present                  │                          │
        │                          │                          │
        └──────────────────────────┼──────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  Narrator (NARRATOR_MODEL)   │──► prose to player
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  Extractor (EXTRACTOR_MODEL) │──► StateDelta (JSON)
                    │   state + input + narration  │
                    └──────────────────────────────┘
```

---

## 3. Memory tiers

### Tier 1 — World Bible (static canon)

`world/world.yaml`. Hand-authored. **Never mutated at runtime.**

Injected *selectively*: only the current location, its exits, and the entities
present. Not the whole world — that's both wasteful and a consistency hazard
(the model will name-drop a character the player hasn't met).

Rough shape:

```yaml
meta:
  name: ...
  tone: ...            # two lines the narrator uses to set voice
  opening_scene: ...   # verbatim first message, so turn 1 is deterministic

locations:
  lighthouse_landing:
    name: "Lighthouse Landing"
    description: "..."          # sensory, 2–3 sentences
    exits: [stair_ascent, shore_path]
    npcs: [keeper]
    items: [rusty_key, sealed_letter]
    secrets: ["..."]            # DM-only, never narrated directly

npcs:
  keeper:
    name: "The Keeper"
    role: "..."
    wants: "..."                 # drives behaviour
    knows: ["..."]               # what they can truthfully reveal
    hides: ["..."]               # what they will deflect
    faction: house_valen
    default_disposition: 0

items: {...}
factions: {...}
history: [...]                   # 3–5 world-level facts
quests: {...}                    # id, name, stages[], completion condition
```

`secrets` / `hides` are the levers that make the DM feel like it knows more than
it says. This is cheap to author and does most of the "feels alive" work.

### Tier 2 — Game State (structured, mutable, exact)

A few hundred tokens. **Always injected in full.** This is the answer to the
brief's "Player Progress" requirement, and it's exact rather than probabilistic.

```python
class Relationship(BaseModel):
    npc_id: str
    disposition: int          # -100..100
    notes: list[str] = []     # "player refused their offer of aid"

class GameState(BaseModel):
    current_location: str
    visited: list[str] = []
    inventory: list[str] = []          # item ids, validated against bible
    relationships: dict[str, Relationship] = {}
    quest_flags: dict[str, str] = {}   # quest_id -> stage id
    established_facts: list[str] = []  # things the DM asserted and must honour
    player_traits: list[str] = []      # "distrusts wizards" — the brief's example
    turn_count: int = 0
```

`player_traits` deserves special mention: it is exactly the brief's worked example
("I don't trust wizards" → the village mage notices your hesitation). Keeping it
structured rather than hoping the summariser preserved it is the difference
between the feature working reliably and working sometimes.

`established_facts` is the anti-contradiction ledger. When the DM invents
something not in the bible ("the well has been dry since the siege"), it gets
written here and injected forever after.

### Tier 3 — Narrative Memory (episodic, lossy)

- Last **8 turns** verbatim.
- Everything older → a rolling summary, regenerated every **8 turns** from
  (previous summary + the turns about to fall out of the buffer).

Summary prompt is explicitly instructed to preserve *causal and emotional*
continuity and to **omit** anything already captured in structured state. No
duplication between tiers.

---

## 4. Turn lifecycle

```
1. Read player input
2. Handle slash commands (/state, /save, /load, /quit) → short-circuit
3. context.build(state, world, memory, player_input) → messages[]
4. narrator.narrate(messages) → prose            [stream to player]
5. extractor.extract(state, input, prose) → StateDelta
6. store.apply_delta(state, delta)               [pure, validated]
7. memory.append(input, prose); maybe compress
8. autosave
```

Extraction (step 5) runs *after* the player already has prose on screen, so its
latency is hidden behind reading time. This is the main reason to stream.

---

## 5. Prompt assembly (`context.py`)

Assembled fresh every turn. Order matters — stable content first for cache
friendliness, volatile content last for recency:

```
[system]
  1. Role + tone + hard rules for the DM
  2. World meta (name, tone)
  3. CURRENT SCENE   — location, description, exits, NPCs present, items present
  4. DM-ONLY NOTES   — secrets available here, NPC wants/hides
  5. GAME STATE      — inventory, relationships, quest stages, player traits,
                       established facts   (rendered compactly, not raw JSON)
  6. STORY SO FAR    — rolling summary
[messages]
  7. Last 8 turns verbatim (user/assistant pairs)
  8. Current player input
```

### Hard rules given to the DM

Non-negotiable, and worth quoting in the README:

1. Never invent entities not in the provided scene or state. If the player goes
   somewhere undefined, describe it as impassable/unremarkable and redirect.
2. Never grant, remove, or reference items not in the provided inventory or scene.
3. End every response with an implicit or explicit opening for player action.
4. Never speak or decide for the player.
5. 120–200 words. Second person, present tense.
6. Never reveal DM-only notes directly; use them to inform behaviour.

Rule 1+2 are what stop the classic hallucinated-loot failure mode.

---

## 6. State extraction

**Chosen approach: two-pass** — narrate first, then a separate cheap call
converts `(state, player_input, narration)` into a `StateDelta`.

```python
class StateDelta(BaseModel):
    move_to: str | None = None
    add_items: list[str] = []
    remove_items: list[str] = []
    relationship_changes: list[RelChange] = []
    quest_updates: dict[str, str] = {}
    new_facts: list[str] = []
    new_traits: list[str] = []
    reasoning: str = ""          # one line, for the debug log
```

### Alternatives considered

| Option | Pro | Con | Verdict |
|---|---|---|---|
| **A. Single call, `{narration, delta}`** | 1 round trip, cheapest | Can't stream cleanly; mixing creative + analytical work degrades both | Rejected |
| **B. Tool calling** on the narrator | Idiomatic "agent" design | Open-weight models silently skip calls for subtle changes (disposition shifts); needs a validation pass anyway | Viable, on-theme |
| **C. Two-pass** | Reliable, clean separation, cheap model for pass 2, latency hidden by streaming | Extra call per turn | **Chosen** |

Two-pass gets *stronger* on Novita than it would on a frontier provider. Asking a
mid-size open-weight model to write good prose **and** emit valid structured JSON
in one generation degrades both noticeably. Splitting the jobs lets each model do
one thing, and lets the extractor run on a model that costs ~$0.07/M input.

Note in the README that B is the more "agentic" answer and would be the first
thing to try given more time — as a *supplement* to C, not a replacement.

### Validation

`apply_delta()` rejects unknown item ids, unknown location ids, and moves to
non-adjacent locations. Rejections are logged, not raised. The model proposes;
the code decides. This is the single most defensible line in the whole design.

---

## 7. Provider: Novita AI

Novita is an inference cloud serving open-weight models behind an **OpenAI-compatible
API**. <cite index="9-1">Set the base URL to `api.novita.ai/openai`, supply an API key,
and change the model name — existing OpenAI ChatCompletion code otherwise works
unchanged</cite>. <cite index="4-1">With the OpenAI SDKs specifically, set the SDK base
URL to `https://api.novita.ai/openai`.</cite> <cite index="8-1">Streaming and function
calling are supported.</cite>

### Model roles

| Role | Default | Rationale |
|---|---|---|
| **Narrator** | `moonshotai/kimi-k2-instruct` | Best prose of the instruct models tried. Two earlier picks were reasoning models and starved (see DECISIONS 11) |
| **Extractor** | `meta-llama/llama-3.3-70b-instruct` | Cheaper, reliable JSON, and never has to write a sentence anyone reads |

Alternatives worth a swap if narration feels flat: `moonshotai/kimi-k2.5` (strong
creative writing, pricier) or `zai-org/glm-4.7`. For the extractor, `qwen3-coder-30b-a3b`
or a Ling flash model are comparable and cheap.

**Model ids are configuration, never constants.** Novita's catalog rotates
frequently and the website's display names are not API ids. Resolve them at
runtime via `GET /openai/models` and read defaults from `.env`. The `--models`
CLI flag exists so a reviewer can fix a stale default in ten seconds instead of
filing it as a broken submission.

### What changes because these are open-weight models

This is a real design consequence, not a config detail — say so in the README.

1. **Instruction adherence is weaker.** The DM's six hard rules will be violated
   more often than they would on a frontier model. The narrator *will* occasionally
   invent an item or over-run the word limit.
2. **Therefore `apply_delta()` validation is load-bearing, not decorative.** Even
   if the narration hallucinates a sword, it never enters inventory unless the
   extractor proposes a delta *and* that delta references a real item id from the
   bible. The state layer is the containment boundary.
3. **Structured output support is per-model.** Do not assume `response_format`
   works. Try `{"type": "json_object"}`; if the chosen model rejects it, fall back
   to prompt-enforced JSON plus fence-stripping. The retry path is needed either way.
4. **Cost drops ~10–20x** versus a frontier provider, which makes the two-pass
   design cheap enough to be obviously correct rather than a luxury.

Point 2 is the strongest thing you can say in the interview: the architecture was
chosen so that *model quality is not a correctness dependency*. Swapping to a
weaker, cheaper model degrades prose. It does not corrupt the game.

---

## 8. Failure modes and handling

| Failure | Handling |
|---|---|
| Extractor wraps JSON in ``` fences | Strip fences before parsing — expect this, don't treat it as an error |
| Extractor returns non-JSON | Retry once with parse error appended → then skip delta, log |
| Model rejects `response_format` | Fall back to prompt-enforced JSON; detect once at startup, cache the answer |
| Delta references unknown entity | Drop that field, apply the rest, log |
| API timeout / 5xx | Retry with backoff (2 attempts), then graceful in-loop message |
| Model id no longer served (404) | Fail at startup with the `--models` hint, not mid-game |
| Context growth | Hard token cap; summary regeneration is the pressure valve |
| Rate limit (429) | Backoff; surface a "the DM pauses to think…" message |

The game loop never dies from an LLM failure. That's the robustness bar.

---

## 9. What is testable

Deterministic, therefore tested:

- `apply_delta()` — add/remove items, illegal moves rejected, disposition clamped
  to [-100, 100], idempotent on empty delta.
- `world.loader` — bad references in `world.yaml` fail loudly at load time.
- `context.build()` — snapshot: given a fixed state, the assembled prompt contains
  the inventory and excludes non-present NPCs.

Not tested: narration quality. Note in the README that the right instrument for
that is an eval harness replaying a fixed transcript and asserting on final
state — listed as future work rather than faked with brittle assertions.

---

## 10. Known limitations (put these in the README honestly)

- The extractor can miss subtle relationship shifts that a human DM would register.
- The summariser is lossy by design; a detail that mattered emotionally but wasn't
  captured as a fact can be lost.
- The DM can still narrate *around* an entity it shouldn't (implying a person
  upstairs who isn't defined). Rule 1 mitigates but doesn't eliminate this.
- No concurrency, single player, single save slot. Deliberate.
- Open-weight narrators break the word limit and occasionally slip out of second
  person. Contained, not eliminated.
- Model defaults may go stale as Novita rotates its catalog; `--models` is the
  escape hatch.
