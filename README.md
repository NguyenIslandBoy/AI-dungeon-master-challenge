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
uv run pytest -q                               # 84 tests, no network required
```

### In-game commands

| Command | Effect |
|---|---|
| `/state` | Dump current game state — inventory, relationships, quests, traits |
| `/save` `/load` | Manual save slot (autosaves every turn regardless) |
| — | Relaunching resumes `save.json` automatically; delete it to start again |
| `/quit` | Exit |

---

## A sample session

Real transcript, trimmed for length. Both roles on
`meta-llama/llama-3.3-70b-instruct`.

```
> I read the papers in my coat. I've no love for the Commission, never have.

The papers are damp at the corners, but the seal is intact. Commission
letterhead, your name, and a paragraph of instruction that seems to be trying
to convey a sense of gravity without actually saying anything. The words
"record the objection" and "harbour works" are underlined, as if someone
thought that would make them more important.
```

That is not improvised. It is the `notes` field of `passage_papers` in
`world.yaml` — *"they appoint the bearer to record Ordell's objection to the
harbour works, not to rule on it"* — injected because the item is in the scene.
Before item canon was wired into the context builder, the narrator invented what
documents said rather than reading them.

The next turn is the one worth reading closely. The Long Hall is **two hops** from
the landing, through the net lofts:

```
> I head straight up to the long hall.

You set out toward the Net Lofts, but as you walk, you notice that the path
doesn't quite lead you to a long hall. Instead, the buildings seem to be a
collection of smaller, more rustic structures... The woman with the salt-white
hair looks up as you approach, and nods at you, but doesn't seem to expect you
to go inside.
```

State moved to the net lofts, and `rejected` was **empty** — the extractor
proposed the adjacent step itself rather than the destination the player named.
That is the fix working at the cheaper end: `apply_delta`'s path-finder is still
the backstop, but it did not have to fire. When the prose *does* run ahead of the
state, the validator's rejection returns to the narrator the following turn as a
`CORRECTIONS` block:

```
CORRECTIONS — your last reply described something that did not happen...
- The player got only as far as The Net Lofts, and is standing there now.
  They did NOT reach the place they set out for, and did not go inside it.
  From here they can reach only: The Drift, The Long Hall.
- There is no such thing as 'greatsword' in this world. The player does not
  have one and never did. Stop referring to it.
```

`apply_delta` was already computing exactly this information and throwing it
away. Feeding it back makes the validator a control signal rather than a
bystander, and closes the loop between "the code decides" and "the model
narrates." Corrections are owed for exactly one turn, and only rejections the
player would have *seen* qualify — bookkeeping ones stay in the log.

```
> I ask the net-mender what she's working on.

"Just a net," she says, her voice gentle. "It's a complicated one, but it's
nothing special."... you notice that the net seems to be... unfinished. There
are threads hanging loose, and some of the knots seem to be coming undone.

...you get the sense that she's been working on this net for a long time, and
that it's never quite been finished... The grey shawl on the bench beside her
seems to be slipping off, and you notice that it's damp, even though it's
indoors.
```

Nell is the whole design in one turn. *"None of it is finished — every net in the
loft is the same net, unpicked and remade, nineteen years of it"* is a `secrets`
entry on the location. *"Her hair is wet at the roots on those mornings"* is a
`hides` entry on her. Neither is stated. The narrator gives the player the loose
threads and the damp shawl and lets them do the arithmetic, which is what hard
rule 6 and the EVERY TURN section ask for.

```
> /state
╭───────────────────────────── game state ──────────────────────────────╮
│ Location: The Net Lofts                                               │
│ Inventory: your appointment papers                                    │
│ Places visited: The Drift, The Net Lofts                              │
│ Relationships: Sarn Vellacott: +20 (showed curiosity about the        │
│         player; approached and offered information),                  │
│         Nell Ashe: +30 (shared her work and showed a gentle smile)     │
│ Quests: The Arrangement: The player has seen at least one thing that   │
│         does not add up.                                              │
│         What Nell Ashe Is: Nell is a net-mender who is kind to         │
│         strangers.                                                    │
│ Player traits: distrusts the Commission                               │
│ Established facts: Nell's net is unfinished and has been worked on    │
│         for a long time                                               │
│ Turn: 3                                                               │
╰───────────────────────────────────────────────────────────────────────╯
```

Three turns of prose, and the ledger is exact: the papers held, two rooms walked
in the right order rather than the order the story was asked for, both quests
advanced off `unaware`, two relationships opened with the reason recorded, and
`distrusts the Commission` kept as a durable trait. That trait is injected on
every subsequent turn — it does not depend on the summariser having preserved it,
or on the model remembering a sentence from twenty turns ago.

### Pushing on it deliberately

**A weapon that does not exist.** Asked to draw a greatsword, the narrator
obliged — a flat violation of hard rule 2. The extractor proposed no item, so
nothing entered inventory. Prose lied; state did not. That is the design working
as intended rather than the model behaving.

**A guard that fired too widely.** The more interesting failure was one the
architecture caused. Successive rules taught the narrator not to describe
arriving anywhere it had not been shown, and taught the extractor that "at the
threshold of" is not arrival. Both were right individually. Together they froze
the player: asked to walk out onto the shore — *a listed exit* — the narrator
parked them at the door and the extractor dutifully reported no move. Three
turns, and `/state` was still empty. Hard rule 2a now names its two cases
separately, and the extractor's mirror rule cancels only the place the threshold
language is attached to. See DECISIONS 26.

**What is still not fixed.** In the very transcript above, the narrator put Nell
on the loft steps while the player was still down on the shingle — she belongs to
the next room — and had Sarn mention a "Drift Council room" that does not exist
in the bible. Hard rule 1 mitigates this; it does not eliminate it. Nothing
validates the narrator's *assertions* about the world, only its proposed state
changes, and that remains the largest gap.

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
structured JSON in one generation degrades both noticeably — and the failure is
correlated, because the same generation that drifts out of character is the one
that drops a brace. Splitting the jobs lets each call do one thing, at a
per-token cost roughly an order of magnitude below a frontier provider. That is
what makes a second call per turn obviously correct rather than a luxury.

Tool calling is the more "agentic" answer and would be the first thing I tried
with more time — as a *supplement* to extraction, not a replacement.

### Two roles, one model — but still two settings

`NARRATOR_MODEL` and `EXTRACTOR_MODEL` both default to
`meta-llama/llama-3.3-70b-instruct`. They were briefly on different models and
have converged back. They are separate settings regardless, and that is the
point: the roles have genuinely different requirements — one wants
temperature and prose quality, the other wants determinism and valid JSON — so
either can move independently the moment the other stops being a good fit. Today
that is a one-line `.env` change with no code impact.

Choosing that default was the one place measurement beat intuition. **An
`-instruct` suffix predicts nothing about whether a model reasons before it
speaks**, and a narrator that reasons is not merely slower — it spends the same
`max_tokens` budget the prose has to come out of. Measured live, one turn each:

| Model | reasoning | prose | latency | outcome |
|---|---|---|---|---|
| `zai-org/glm-4.7-flash` | 1051 tok | 145 tok | 77 s | truncated mid-scene |
| `moonshotai/kimi-k2-0905` | all 1200 | 0 | — | silent turn; on another, printed its chain of thought to the player |
| `sao10k/l31-70b-euryale-v2.2` | 0 | 167 tok | 3.4 s | best prose; invented a man, a horse and a gate, then put the light out |
| `meta-llama/llama-3.3-70b-instruct` | 0 | 180 tok | 6.0 s | in canon, in budget — **chosen** |

The euryale result is the instructive one. It is a creative-writing finetune and
it wrote the most atmospheric prose of the four — and it invented four entities
that are not in the bible and contradicted the world's founding premise within
three turns. For a DM whose whole job is consistency, fluency is not the metric.

What this is *not* is multi-model routing: no router, no fallback chain, no
per-request selection. Two names in a config file.

### Everything else

The remaining trade-offs are logged one line each in
[`docs/DECISIONS.md`](docs/DECISIONS.md): why bad deltas are dropped rather than
raised, why an added item must exist in the bible but need not be in the current
scene, what gets truncated first when the context budget is hit, and why the
token estimate is `len // 4` rather than a real tokenizer.

One is worth pulling out, because the bug was in the *reading* of the code rather
than in it. Novita 429s in bursts, and each one cost a whole turn. The budget
looked like two attempts — but the OpenAI SDK retries twice inside each of ours,
so it was really six requests, and the two seconds of backoff never outlasted a
burst. The fix was to collapse to one retry layer (`max_retries=0` on the SDK) so
the number means what it says, then widen it to five attempts with backoff capped
at 8s. The cap is the interesting half: 2, 4, 8, 8 is 22s of worst-case waiting,
which a spinner can carry, where uncapped doubling would stall a turn for a
minute. A retry budget you cannot read off the code is one you cannot tune.

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
- The correction loop is reactive, not preventive: a bad turn still reaches the
  player, and only the *next* turn is steered back. A canon validator on the
  narration itself would catch it before it is printed — see next steps.
- Nothing validates the narrator's *assertions* about the world, only its
  proposed state changes. It once called the great lamp "dark" — flatly against
  the world's premise — and then repeated it, because its own prose was in the
  verbatim buffer. Hard rules 2a and 2b push back on this; they do not
  guarantee it. This is the single largest remaining gap.
- Open-weight narrators break the word limit and occasionally slip out of second
  person. Contained, not eliminated — and contained is the design goal.
- **A reasoning model set as narrator can print its own deliberation to the
  player.** The client filters `reasoning_content`, which is where most models put
  it — but `kimi-k2-0905` was observed emitting chain of thought through `content`,
  where it is indistinguishable from prose. There is no reliable filter for that,
  so the mitigation is the default and the startup warning, not a detector.
- Single player, single save slot, no concurrency. Deliberate.
- Model defaults may go stale as Novita rotates its catalog; `--models` is the
  escape hatch.
- **Narration quality is not tested.** Asserting on prose with string matching is
  brittle and proves little. The right instrument is an eval harness — see below.
  The cost of not having one is measurable: two prompt rules that were each
  correct in isolation combined to freeze the player in the opening room for a
  whole session, and only a hand-played game surfaced it (DECISIONS 26).

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
   rather than what the player did. Sarn should not know about a conversation
   held in the net lofts.
5. **Richer relationship modelling.** A single disposition integer is coarse;
   trust, fear, and respect are separable and would make Ordell's two factions
   behave more distinctly.

---

## Layout

```
dungeon_master/
  world/       world.yaml (static canon) + loader with reference validation
  state/       models.py (GameState, StateDelta), store.py (pure apply_delta)
  memory/      transcript.py (turn buffer), summarizer.py (rolling digest)
  llm/         client.py, narrator.py, extractor.py
  llm/prompts/ one markdown file per prompt, plus a loader
  context.py   prompt assembly
  game.py      one turn of the lifecycle, no I/O
  cli.py       game loop, the only module that prints
tests/         84 tests, no network required
docs/          ARCHITECTURE.md, DECISIONS.md, PLAN.md, EXECUTION_PLAN.md
```

All prompts live in `llm/prompts/` as markdown, one file each — nothing is
inlined in Python. They are the artefact worth reading most closely, and keeping
them as content means a wording change diffs as prose. Placeholders use
`${name}` via `string.Template`: `extractor_system.md` is largely a JSON schema,
and `str.format` would try to read every brace in it as a field. The loader
reads every file at import, so a missing file or an unfilled placeholder fails
at startup rather than mid-game.
