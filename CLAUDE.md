# CLAUDE.md

AI Dungeon Master — a CLI text adventure where an LLM narrates a fantasy world
while **the application** owns game state.

This is a take-home for an AI Agent Engineering role. It is graded on reasoning
and structure, **not** feature count. Budget: 3–4 hours.

---

## Prime directive

**Code owns state. The LLM owns prose.**

The model never *holds* game state — it narrates *given* state, and *proposes*
changes to it. Every turn we rebuild the prompt from `GameState` rather than
trusting the model to have remembered anything.

If a change would make the conversation history the source of truth for
inventory, location, relationships, or quest flags — it is wrong. Stop and say so.

---

## Non-goals (do not build these)

| Not building | Why |
|---|---|
| Vector DB / RAG | ~25 world entities. Keyed dict lookup is exact, instant, debuggable. |
| LangChain / agent frameworks | They hide context assembly — the exact thing being graded. |
| Web UI | Brief says frontend is not the focus. CLI only. |
| Combat / dice / stats / XP | Rabbit hole. Nothing in the brief asks for it. |
| Streaming *and* multi-model routing *and* async extraction | Pick simple. Ship. |

If you think one of these is needed, **ask first**. Don't add it silently.

---

## Docs

Read on demand, not by default:

- `docs/ARCHITECTURE.md` — data models, turn lifecycle, memory tiers, trade-offs.
  **Read this before writing any code in `context.py`, `state/`, or `llm/`.**
- `docs/PLAN.md` — phased implementation checklist with time budget and cut list.
  **Update the checkboxes as you go.**
- `README.md` — the graded deliverable. Written last, weighted heavily.

---

## Layout

```
dungeon_master/
  world/       world.yaml (static canon), loader.py
  state/       models.py (GameState, StateDelta), store.py (apply/save/load)
  memory/      transcript.py (turn buffer), summarizer.py (rolling compression)
  llm/         client.py, narrator.py, extractor.py
  llm/prompts/ one .md per prompt + a loader (__init__.py)
  context.py   prompt assembly — the crown jewel, keep it readable
  cli.py       game loop
tests/         test_delta.py — deterministic parts only
docs/
```

---

## Stack

Python 3.11+ · `uv` · pydantic v2 · **`openai` SDK pointed at Novita** · `rich` (CLI) · `pytest` · `pyyaml`

Novita is OpenAI-compatible. Use the `openai` package, not `anthropic`:

```python
from openai import OpenAI
client = OpenAI(
    api_key=os.environ["NOVITA_API_KEY"],
    base_url="https://api.novita.ai/openai",
)
```

**Two roles, two models** (both overridable via `.env`):

| Role | Default | Why |
|---|---|---|
| Narrator | `zai-org/glm-4.7-flash` | Cheap, long context, solid prose |
| Extractor | `zai-org/glm-4.7-flash` | Same model by default; separate setting so it can be swapped |

**Never hardcode a model ID.** Novita's catalog changes often and display names on
the website are not API ids. Confirm ids at runtime:

```bash
curl https://api.novita.ai/openai/models -H "Authorization: Bearer $NOVITA_API_KEY"
```

Config via `.env` → `NOVITA_API_KEY`, `NOVITA_BASE_URL`, `NARRATOR_MODEL`,
`EXTRACTOR_MODEL`. Never hardcode keys. Ship `.env.example`.

## Commands

```bash
cp .env.example .env                       # then paste your NOVITA_API_KEY
uv sync
uv run python -m dungeon_master.cli        # play
uv run python -m dungeon_master.cli --models   # list available Novita model ids
uv run pytest -q                           # tests
```

In-game: `/state` (dump state — debug + demo), `/save`, `/load`, `/quit`

---

## Conventions

- **All prompts live in `llm/prompts/`, one markdown file each.** Never inline a
  prompt string anywhere else. They're the artefact reviewers will read most
  closely, and they are content rather than code — a wording change should be a
  clean diff of prose, not of Python string literals.
- **Placeholders are `${name}`, never `{name}`.** Prompts are rendered with
  `string.Template`, because `extractor_system.md` is mostly a JSON schema and
  `str.format` would read every brace in it as a field.
- **`apply_delta()` is a pure function.** No I/O, no LLM calls. It is the one thing
  that gets real unit tests.
- Pydantic models everywhere state crosses a boundary. Validate extractor output.
- Type hints on public functions. Docstrings only where the *why* isn't obvious.
- Keep modules under ~150 lines. If one grows past that, the boundary is wrong.
- No `print()` outside `cli.py`. Use `logging` (file handler — never pollute the
  game screen).

## Failure handling

Open-weight models follow instructions less reliably than frontier closed models.
Assume every LLM output is untrusted input.

- Extractor returns malformed JSON → strip markdown fences → one retry with the
  parse error appended → then skip the delta and log it. A dropped state update
  is recoverable; a crash mid-adventure is not.
- Never `json.loads()` a raw completion. Always fence-strip → parse → pydantic
  validate → `apply_delta` validate.
- Narrator ignoring word limits or breaking character is expected occasionally;
  the state layer must stay correct regardless. That is the whole point of the
  architecture.
- API timeout → friendly in-character-ish message, keep the loop alive, never
  show a traceback to the player.
- Hard-cap assembled context size. A long session must not blow the window.

---

## Working style for this repo

- Follow `docs/PLAN.md` phase order. Don't jump ahead.
- Prefer deleting code over adding config toggles.
- When you hit a genuine trade-off, note it in `docs/DECISIONS.md` (one line:
  choice, alternative, why). The README pulls from that file.
- Do not expand `world.yaml` beyond ~6 locations / ~6 NPCs / ~8 items /
  2 factions / 2 quests. Depth beats breadth and the context builder must stay small.
