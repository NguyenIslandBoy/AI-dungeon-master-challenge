# Execution Plan

Derived from `requirements/AI_dungeon_master_challenge.md`, `CLAUDE.md`,
`ARCHITECTURE.md`, `PLAN.md`, `README.md`, and the two flow sketches.

`PLAN.md` says *what* to build and in what phase order. This document is the
*execution* layer on top of it: the state of the repo today, the contradictions
between the docs that need resolving before code is written, a schedule that
actually fits the budget, the module interfaces to code against, and the gates
where the build can stall.

---

## 0. Build status

Phases R through 6 are **implemented**. 68 tests pass with no network access.

What remains is gated on Novita reachability, not on code:

| Gate | State |
|---|---|
| G0 — model ids resolved against the live catalog | **Cleared.** Base URL corrected to `https://api.novita.ai/openai`; both roles default to `zai-org/glm-4.7-flash` |
| G1 — narration reflects state | **Cleared** on `meta-llama/llama-3.3-70b-instruct`. Two bugs found by doing it: reasoning-model starvation, and item canon never being injected |
| G2 — extractor JSON ≥ 8/10 | **Cleared** on `meta-llama/llama-3.3-70b-instruct`. Reasoning models starve here too and are not viable for either role |
| README sample transcript | **Done** — real captured session, including both adversarial probes |

Everything else in this document is the record of how it was built and what the
open decisions were.

---

## 1. Where the repo stood at the start

Docs only. No `pyproject.toml`, no `dungeon_master/` package, no `tests/`, no
`.env.example`. Every checkbox in `PLAN.md` unticked, and accurately so.

Toolchain confirmed present: Python 3.11.15, `uv`. **`NOVITA_API_KEY` not set** —
see Gate G0.

The design work was done and it was good. The risk was never "what should it look
like"; it was time, and one external dependency.

---

## 2. Reconcile the docs before writing code (~15 min, do first)

Six inconsistencies across the docs. Each is small, but each will cost more later
— either as a broken reviewer experience or as a wrong decision baked into code.

| # | Issue | Where | Fix |
|---|---|---|---|
| R1 | `README.md` links to `docs/ARCHITECTURE.md` and `docs/PLAN.md`; `CLAUDE.md` names `docs/` too. The files are at repo root and `docs/` does not exist — **both README links are dead** | README, CLAUDE.md | `mkdir docs && git mv ARCHITECTURE.md PLAN.md EXECUTION_PLAN.md docs/`. Cheapest fix, matches the documented layout |
| R2 | ARCHITECTURE §2 diagram labels the models **"sonnet"** and **"haiku"** — residue from an Anthropic-targeted draft. Contradicts §7 and CLAUDE.md's "use the `openai` SDK, not `anthropic`" | ARCHITECTURE §2 | Relabel to `Narrator (NARRATOR_MODEL)` / `Extractor (EXTRACTOR_MODEL)`. A reviewer who spots this reads it as inattention |
| R3 | `DECISIONS.md` is referenced by CLAUDE.md ("note it in `docs/DECISIONS.md`") and the README pulls from it. It does not exist | CLAUDE.md | Create `docs/DECISIONS.md` in Phase 0 with a header row. Append one line per trade-off *as they happen*, not retroactively at hour 4 |
| R4 | PLAN Phase 6 §8 cites "the honest list from ARCHITECTURE §9". Limitations are **§10**; §9 is testability | PLAN | One-character fix |
| R5 | ARCHITECTURE §4 justifies two-pass extraction with "latency is hidden behind reading time", which **requires streaming** — but streaming is cut-list item 5 | ARCHITECTURE §6, PLAN cut list | If streaming is cut, the two-pass justification narrows to "separation of concerns" only. Move streaming *below* `/save`/`/load` in the cut order; it is load-bearing for the argument, not polish |
| R6 | CLAUDE.md non-goals: "Streaming **and** multi-model routing **and** async extraction — pick simple." The design ships streaming + two models | CLAUDE.md vs ARCHITECTURE §7 | Not a real conflict, but say so explicitly in the README: two fixed roles is not *routing*, and async extraction stays cut. Pre-empt the reviewer's question |

Also missing from every doc and needed at Phase 0: `.gitignore`, `.env.example`,
`pyproject.toml`, `LICENSE` (optional).

---

## 3. Budget reality check

`PLAN.md` declares a **4-hour hard stop**, then allocates 15 + 30 + 45 + 60 + 45
+ 30 + 30 = **255 min = 4h15m**. The plan is over budget before anything goes
wrong, with zero contingency, and the challenge brief asks for 3–4 hours.

Rebalanced, with the reconciliation work absorbed and a real reserve:

| Phase | `PLAN.md` | Here | Delta and why |
|---|---|---|---|
| R — Doc reconciliation | — | 15 | New. Section 2 above |
| 0 — Scaffold + Gate G0 | 15 | 20 | Model-id probe is a hard gate; do not rush it |
| 1 — World bible | 30 | 30 | Unchanged. This is where the "enjoyed building it" points live |
| 2 — State layer + tests | 45 | 35 | Pure functions with a spec this precise; 35 is realistic |
| 3 — Context + narrator | 60 | 60 | **Protected.** The crown jewel and the interview topic |
| 4 — Extractor + loop | 45 | 45 | Unchanged. Highest technical-risk phase |
| 5 — CLI polish | 30 | 20 | `rich` panels + `/state` + autosave only. Trim first |
| 6 — README | 30 | 30 | **Protected.** Weighted heavily by the brief |
| Reserve | 0 | 25 | Absorbs the phase that overruns — one always does |
| **Total** | **255** | **280** | Of which 25 is reserve → **255 committed** |

If the reserve is untouched at Phase 6, spend it on the README transcript and
the eval-harness paragraph, not on features.

---

## 4. Critical path and gates

```
R ──► P0 ──[G0]──► P1 ──► P2 ──► P3 ──[G1]──► P4 ──[G2]──► P5 ──► P6
                    │       │       │
                    └───────┴───────┴── no API key needed (stub client)
```

**Gate G0 — credentials and model ids (blocks everything downstream of P0).**
No `NOVITA_API_KEY` is present in this environment. Before building on any model
id, resolve the catalog at runtime — display names on novita.ai are not API ids:

```bash
curl https://api.novita.ai/openai/models \
  -H "Authorization: Bearer $NOVITA_API_KEY" | jq -r '.data[].id' | sort
```

**Resolved.** The catalog was listed against a live key and both originally
guessed ids (`deepseek/deepseek-v3.2`, `zai-org/glm-4.7-flash`) turned out to be
served — the stale value was not a model id but the **base URL**: it is
`https://api.novita.ai/openai`, not `.../openai/v1` as the design docs had it.
That would have 404'd every reviewer on the first turn, which is exactly the
class of failure this gate exists to catch.

Shipped defaults are now `zai-org/glm-4.7-flash` for both roles. The first
choice, `deepseek/deepseek-v4-flash-0731`, was served and answered — but is a
reasoning model, and spent its entire token budget in `reasoning_content`
without emitting a word of prose. Gate G1 caught that on the first real turn,
which is precisely what it is for.

*If the key is delayed:* Phases 1, 2, and most of 3 need no network. Write a
`StubClient` in `tests/` that returns canned prose and canned delta JSON, and
keep building. Scope it to tests only — do **not** add an `--offline` CLI flag
(CLAUDE.md: prefer deleting code over adding config toggles).

**Gate G1 — narration reflects state.** Hand-construct a `GameState` with two
inventory items and a location, call `narrate`, read the prose. If it names an
item that isn't there, the fault is in `context.py`, not the model. Fix before
Phase 4 — debugging the extractor on top of a broken context builder is a hole.

**Gate G2 — extractor emits parseable JSON ≥ 8 times in 10.** Measured, not
eyeballed. If a cheap model can't clear it after the one-shot example and the
retry path are both in, set `EXTRACTOR_MODEL=$NARRATOR_MODEL` and move on. That
is a `.env` change with zero code impact — which is itself the architecture's
point, and worth one line in `DECISIONS.md`.

---

## 5. Work breakdown

Target file count ≈ 15. Each module stays under ~150 lines (CLAUDE.md).

### Phase 0 — Scaffold (20 min)

```
pyproject.toml   .gitignore   .env.example   docs/DECISIONS.md
dungeon_master/__init__.py    llm/client.py
```

Deps: `openai`, `pydantic`, `pyyaml`, `rich`, `python-dotenv`, `pytest`.

```python
class LLMClient:
    def complete(self, system: str, messages: list[dict], *, model: str,
                 max_tokens: int = 600, stream: bool = False,
                 response_format: dict | None = None) -> str | Iterator[str]: ...
    def list_models(self) -> list[str]: ...
    def supports_json_object(self, model: str) -> bool: ...   # probed once, cached
```

Two-attempt backoff, explicit timeout, no business logic. `--models` reads
through `list_models()`.

**Done when:** `uv run python -c "import dungeon_master"` succeeds and a smoke
call returns text from Novita.

### Phase 1 — World bible (30 min)

```
dungeon_master/world/world.yaml    world/loader.py
```

Budget is a **ceiling, not a target**: 6 locations, 6 NPCs, 8 items, 2 factions,
2 quests, 4 history facts, `opening_scene`. Every location gets `secrets`; every
NPC gets `wants` / `knows` / `hides` — these do most of the "feels alive" work
for near-zero cost.

Take the Keeper's Reach seed from `PLAN.md` §Phase 1. The
*cannot-state-a-falsehood-but-excellent-at-omission* faction rule is one line in
an NPC prompt block and buys disproportionate dialogue texture — keep it.

```python
def load_world(path: Path = WORLD_PATH) -> World: ...
class World(BaseModel):
    meta: Meta; locations: dict[str, Location]; npcs: dict[str, NPC]
    items: dict[str, Item]; factions: dict[str, Faction]
    history: list[str]; quests: dict[str, Quest]
    def scene(self, location_id: str) -> Scene: ...   # loc + exits + npcs + items present
```

Validation collects **every** bad reference and raises once with the full list —
not first-fail. Fixing six broken ids one reload at a time is the slow path.

**Done when:** loader validates cleanly, and the boot sketch's "validate every
reference / fail loudly, before play" is literally true.

### Phase 2 — State layer (35 min)

```
dungeon_master/state/models.py    state/store.py    tests/test_delta.py
```

Shapes exactly as ARCHITECTURE §3 and §6. `apply_delta` is **pure** — no I/O, no
LLM calls:

```python
def apply_delta(state: GameState, delta: StateDelta,
                world: World) -> tuple[GameState, list[str]]:   # new state, rejections
```

Validation rules, all of which *drop and log* rather than raise:

- `move_to` must be a known location **and** adjacent to `current_location` (or equal)
- item ids must exist in the bible; inventory de-duplicated
- `remove_items` not currently held → dropped
- disposition clamped to `[-100, 100]`
- quest id and stage must both exist in the bible
- `new_facts` / `new_traits` de-duplicated and capped (~20 / ~10) to bound context growth
- empty delta is a no-op — the state object is unchanged

`turn_count` increments in the game loop, not via the delta.

> **Open decision for this phase** (record in `DECISIONS.md`): must an added item
> be present in the *current scene*, or only exist in the bible? Strict scene
> checking blocks legitimate NPC gifts; bible-only checking lets the narrator
> conjure a known item from the wrong room. **Recommendation:** bible-only
> validation, log a warning when the item wasn't in scene. Keeps the containment
> boundary meaningful without fighting plausible fiction.

Tests: illegal move, unknown item, unknown quest stage, disposition clamp both
ends, remove-not-held, empty-delta idempotence.

**Done when:** `uv run pytest -q` is green with zero network calls.

### Phase 3 — Context builder + narrator (60 min) — protected

```
memory/transcript.py    llm/prompts.py    context.py    llm/narrator.py
```

All prompt strings live in `llm/prompts.py`. No exceptions — these are the
artefact reviewers read most closely.

```python
def build(state: GameState, world: World, transcript: Transcript,
          player_input: str, *, budget_tokens: int = 6000) -> tuple[str, list[dict]]:
```

Assembly order per ARCHITECTURE §5: stable content first (cache-friendly),
volatile last (recency). State renders as compact prose-ish lines, **never** a
raw JSON dump — the model reads prose better, and the diff is legible in the log.

Token budget uses a `len(text) // 4` heuristic; no tokenizer dependency for a
hard cap this coarse. **Truncation priority when over cap:** drop oldest verbatim
turns first → then trim the rolling summary → *never* drop the scene block or the
state block. Those two are the correctness guarantee.

**Done when:** Gate G1 passes.

### Phase 4 — Extractor + loop closure (45 min) — highest risk

```
llm/extractor.py    memory/summarizer.py    cli.py (loop skeleton)    game.log
```

Never `json.loads()` a raw completion. The pipeline is:
**fence-strip → parse → pydantic validate → `apply_delta` validate.**
One retry with the parse error appended, then skip the delta and log it. A
dropped state update is recoverable; a crash mid-adventure is not.

Include a **worked one-shot example** in `EXTRACTOR_SYSTEM`. Open-weight models
comply far better with one example than with a bare schema description — this is
the single highest-leverage line in the phase.

Streaming ordering trap: accumulate the **full** narration string before calling
the extractor. Extracting from a partial stream produces deltas that silently
drop the last sentence's events.

Turn lifecycle per ARCHITECTURE §4 and the turn-loop sketch: input → commands →
`context.build` → narrate (stream) → extract → `apply_delta` → append memory,
maybe compress → autosave.

`game.log` records every delta, every rejection, every retry. No `print()`
outside `cli.py`.

**Done when:** a 12-turn playthrough keeps inventory and location correct, and
`game.log` shows the deltas and at least one rejection.

### Phase 5 — CLI polish (20 min)

`rich` panels, a "the DM considers…" spinner, streamed output, graceful `Ctrl+C`
with no traceback ever reaching the player.

`/state` is **not** optional. It is the fastest way for a reviewer to see the
architecture is real, and it is the live demo.

### Phase 6 — README (30 min) — protected, never cut

Follow the nine-section structure in `PLAN.md` Phase 6 verbatim. Two additions:

- Section 2's transcript comes from the **demo script in §8 below** — capture a
  real one, don't write one by hand.
- Add the R6 note: two fixed model roles is not multi-model routing, and async
  extraction was deliberately not built.

---

## 6. Test plan

| Target | Type | Priority |
|---|---|---|
| `apply_delta()` — 6 cases | Unit, pure | **Never cut** |
| `world.loader` reference validation | Unit, fixture with a deliberate bad ref | High |
| `context.build()` — contains inventory, excludes absent NPCs | Snapshot | Cut third |
| Narration quality | **Not tested.** Name the right instrument in the README (eval harness replaying a fixed transcript, asserting final state) and list it as future work rather than faking it with brittle assertions | — |

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| No API key at Gate G0 | **Present now** | Blocks P0 smoke, G1, G2 | Phases 1–3 proceed against a `StubClient` in `tests/` |
| Default model ids retired | Medium | Startup 404 | Resolve at runtime, fail at startup with the `--models` hint — never mid-game |
| `response_format` unsupported on the extractor model | Medium | Malformed JSON | Probe once at startup, cache; fall back to prompt-enforced JSON + fence-stripping. The retry path is needed either way |
| Cheap extractor fails Gate G2 | Medium | Broken state updates | `EXTRACTOR_MODEL=$NARRATOR_MODEL` — a `.env` change, no code |
| Phase 3 overruns | High | Squeezes Phase 4 | 25-min reserve, then the cut list |
| World bible sprawl | Medium | Context bloat, lost time | Ceilings in §Phase 1 are hard; depth over breadth |
| Narrator breaks the word limit / slips person | **Expected** | Cosmetic only | By design: state stays correct regardless. This *is* the architecture's thesis — say so in the README rather than fighting it |

---

## 8. Demo script (drives the README transcript and any recording)

Run this once at the end, capture the output verbatim. It exercises every claim
the README makes, in order:

1. Boot → opening scene prints **verbatim, with no model call** (per the boot sketch)
2. `I pick up the letter` → item enters inventory
3. `I don't trust wizards` → trait recorded — the brief's own worked example
4. Move two locations away, then back
5. `/state` → inventory, location, trait, relationships all exact
6. Meet the mage NPC → narration visibly reflects the trait from step 3
7. `I draw my greatsword` (no such item) → narration is redirected, and
   `game.log` shows the rejected delta

Step 7 is the money shot: it demonstrates the containment boundary rather than
asserting it. Steps 3 and 6 together are the brief's Player Progress requirement,
proven end-to-end.

---

## 9. Cut order

Revised from `PLAN.md` per R5 — streaming moves down, because the two-pass
latency argument depends on it:

1. Rolling summary compression → truncate to last 12 turns, note it in the README
2. `/save` `/load` → autosave only
3. Snapshot test of `context.build()`
4. `rich` styling → plain `print` in `cli.py`
5. Streaming → blocking call with a spinner *(and amend the ARCHITECTURE §6 rationale if this is taken)*

**Never cut:** `apply_delta()` validation · `/state` · the README.

---

## 10. Definition of done

- [ ] Fresh clone + `uv sync` + API key → playable in under 2 minutes
- [ ] 15-turn playthrough, zero contradictions in inventory or location
- [ ] An early stated preference visibly influences a later scene
- [ ] `uv run pytest -q` green
- [ ] `game.log` contains at least one logged rejection from a real session
- [ ] README covers all nine sections, with a real transcript
- [ ] `docs/DECISIONS.md` has ≥ 4 entries written *during* the build
- [ ] Total files ≈ 15. If it's 40, something went wrong
