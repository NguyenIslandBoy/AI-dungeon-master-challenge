# Implementation Plan

Time budget: **4 hours hard stop.** Phases are ordered so that stopping at the end
of any phase still leaves something demonstrable.

Tick boxes as you go. If a phase overruns by >15 min, take from the cut list
(bottom) rather than from Phase 6.

---

## Phase 0 — Scaffold (15 min)

- [ ] `uv init`, add deps: `openai`, `pydantic`, `pyyaml`, `rich`, `python-dotenv`, `pytest`
- [ ] Package skeleton per `CLAUDE.md` layout, all modules empty but importable
- [ ] `.gitignore` (`.env`, `save.json`, `*.log`, `__pycache__`)
- [ ] `.env.example`:

      ```
      NOVITA_API_KEY=
      NOVITA_BASE_URL=https://api.novita.ai/openai/v1
      NARRATOR_MODEL=deepseek/deepseek-v3.2
      EXTRACTOR_MODEL=zai-org/glm-4.7-flash
      ```

- [ ] **Verify the model ids before building anything on them.** Display names on
      novita.ai are not API ids:

      ```bash
      curl https://api.novita.ai/openai/v1/models \
        -H "Authorization: Bearer $NOVITA_API_KEY" | jq -r '.data[].id'
      ```

      Correct `.env.example` to match. Ten minutes here saves an hour of confusing
      404s later.
- [ ] `llm/client.py`: `OpenAI(api_key=..., base_url=...)` wrapper —
      `complete(system, messages, model, max_tokens, stream=False)` with 2-attempt
      backoff, timeout, and a `--models` helper that lists available ids.
      No business logic in here.
- [ ] Probe once at startup whether the extractor model accepts
      `response_format={"type": "json_object"}`; cache the result. If not,
      fall back to prompt-enforced JSON.

**Done when:** `uv run python -c "import dungeon_master"` succeeds and a smoke
call returns text from Novita.

---

## Phase 1 — World bible (30 min)

Hand-write it. Do not generate a sprawling world.

- [ ] `world/world.yaml` — 6 locations, 6 NPCs, 8 items, 2 factions, 2 quests,
      4 history facts, `opening_scene`
- [ ] `world/loader.py` — parse into pydantic models, **validate all cross-references**
      (every exit, npc, item id resolves) and raise loudly on failure
- [ ] Every location has `secrets`; every NPC has `wants` / `knows` / `hides`

### Seed (replace if you have something better — you probably do)

**The Keeper's Reach.** A storm-locked coast. The lighthouse keeper has been
tending the light for eleven years and does not know he drowned in the first year;
the light he tends is real, but he cannot leave the tower and cannot say why.
Two factions want it: **House Valen**, who need the light dark for one night to
land something, and the **Tide-Wardens**, sworn to keep it burning, who have
forgotten the original reason.

Hook: NPCs of one faction are *physically unable to state a falsehood* — but they
are excellent at omission. That single rule makes dialogue feel authored and costs
nothing to implement (it's one line in their prompt block).

**Done when:** loader validates cleanly and `world.yaml` is genuinely fun to read.
This is 30 minutes that buys most of the "the author enjoyed building it" points.

---

## Phase 2 — State layer (45 min)

- [ ] `state/models.py` — `GameState`, `Relationship`, `StateDelta`, `RelChange`
      (exact shapes in `docs/ARCHITECTURE.md` §3, §6)
- [ ] `state/store.py`:
  - [ ] `apply_delta(state, delta, world) -> tuple[GameState, list[str]]`
        returns new state + list of rejection reasons. **Pure.**
  - [ ] Validation: unknown ids dropped, non-adjacent moves rejected,
        disposition clamped to [-100, 100], no duplicate inventory entries
  - [ ] `save(state, path)` / `load(path)` — plain JSON
- [ ] `tests/test_delta.py` — 5–6 cases incl. illegal move, unknown item,
      clamping, empty-delta idempotence

**Done when:** `uv run pytest -q` is green. No LLM involved yet.

---

## Phase 3 — Context builder + narrator (60 min) ← the crown jewel

Spend the time here. This is what gets discussed in the interview.

- [ ] `memory/transcript.py` — turn buffer, `last_n(8)`
- [ ] `llm/prompts.py` — `DM_SYSTEM` (with the 6 hard rules from ARCHITECTURE §5),
      `SCENE_BLOCK`, `STATE_BLOCK`, `SUMMARY_PROMPT`, `EXTRACTOR_SYSTEM`
- [ ] `context.py` — `build(state, world, memory, player_input) -> (system, messages)`
  - [ ] Injects **only** current location + exits + entities present
  - [ ] Renders state compactly as prose-ish lines, **not** raw JSON dump
  - [ ] Hard token cap with a truncation strategy
- [ ] `llm/narrator.py` — streams; 120–200 words

**Done when:** you can hand-construct a `GameState`, call `narrate`, and get prose
that correctly reflects inventory and location.

---

## Phase 4 — Extractor + loop closure (45 min)

- [ ] `llm/extractor.py` — extractor model, `EXTRACTOR_SYSTEM`, JSON-only output,
      **fence-stripping**, pydantic parse, one retry with the parse error fed back,
      then give up gracefully. Include a worked example in the prompt — open-weight
      models comply far better with one-shot than with a bare schema description.
- [ ] Wire the full turn lifecycle (ARCHITECTURE §4)
- [ ] `memory/summarizer.py` — regenerate rolling summary every 8 turns
- [ ] Logging to `game.log` — every delta, every rejection, every retry

**Done when:** a 12-turn playthrough keeps inventory and location correct, and
`game.log` shows the deltas.

---

## Phase 5 — CLI polish (30 min)

- [ ] `cli.py` — `rich` panels, "the DM considers…" spinner, streamed output
- [ ] `/state` — pretty-print current state. **Do not skip this.** It's the fastest
      way for a reviewer to see the architecture is real, and it's your live demo.
- [ ] `/save`, `/load`, `/quit`, autosave each turn
- [ ] Graceful `Ctrl+C`; never show a traceback to the player

**Done when:** you'd be happy screen-recording 3 minutes of it.

---

## Phase 6 — README (30 min) — PROTECTED, DO NOT CUT

Weighted heavily. Structure:

1. **Run instructions first.** `cp .env.example .env`, paste `NOVITA_API_KEY`
   (link to novita.ai key page), `uv sync`, one command. Note the `--models` flag
   in case a default model id has rotated out. Make it trivially easy — reviewers
   who can't run it don't read the rest.
2. **A 15-line transcript** showing memory working (grab a real one, don't fake it).
3. **Architecture diagram** (lift from ARCHITECTURE.md).
4. **The core decision:** code owns state, LLM owns prose. Why, and what failure
   modes it prevents.
5. **Memory tiering:** what lives where and why nothing is duplicated.
6. **Trade-offs:** the two-pass vs. tool-calling table. Plus the provider point —
   open-weight models on Novita follow instructions less reliably, which is
   *why* validation lives in `apply_delta()` rather than in the prompt. Model
   quality is not a correctness dependency here; a weaker model degrades prose,
   not state. Mention the ~10–20x cost saving that makes two-pass obviously worth it.
7. **What I deliberately did not build:** RAG, frameworks, web UI, combat — with
   reasons. This section is the differentiator; most candidates omit it.
8. **Known limitations:** the honest list from ARCHITECTURE §9.
9. **Next day:** async extraction; canon validator that checks narration only
   references known entities; an eval harness replaying a fixed 30-turn transcript
   and asserting final state; NPC-scoped memory (what *they* witnessed vs. what
   the player did offscreen); tool-calling narrator as a supplement to extraction.

---

## Cut list (in this order, if time runs short)

1. Rolling summary compression → just truncate to last 12 turns, note it in README
2. `/save` `/load` → autosave only
3. Snapshot test of `context.build()`
4. `rich` styling → plain print
5. Streaming → blocking call with a spinner

**Never cut:** `apply_delta` validation, `/state`, the README.

---

## Definition of done

- [ ] Fresh clone + `uv sync` + API key → playable in under 2 minutes
- [ ] 15-turn playthrough with zero contradictions in inventory/location
- [ ] An early stated preference visibly influences a later scene
- [ ] `pytest` green
- [ ] README covers all 9 sections above
- [ ] Total files ≈ 15. If it's 40, something went wrong.
