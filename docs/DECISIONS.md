# Decisions

One line each: the choice, the alternative, why. The README pulls from this file.

| # | Choice | Alternative | Why |
|---|---|---|---|
| 1 | Two-pass: narrate, then extract a delta with a cheaper model | Single call returning `{narration, delta}`; tool-calling narrator | Mixing creative and analytical work degrades both on open-weight models, and a single call can't stream cleanly. Tool calling is the more agentic answer and is listed as next-day work |
| 2 | `apply_delta()` validates against the world bible and *drops* bad fields | Raise on invalid delta | A dropped state update is recoverable; a crash mid-adventure is not. Rejections are logged, never surfaced to the player |
| 3 | `add_items` requires the item id to exist in the bible, but **not** to be present in the current scene | Strict scene-presence check | Strict checking blocks legitimate NPC gifts and rewards. Bible-only keeps the containment boundary meaningful without fighting plausible fiction; out-of-scene adds are logged as warnings |
| 4 | Context truncation drops oldest verbatim turns first, then trims the summary, and never drops the scene or state blocks | Proportional trim across all sections | Scene and state are the correctness guarantee. Narrative memory is lossy by design, so it is the right thing to spend first |
| 5 | Token budget estimated as `len(text) // 4` | Real tokenizer (`tiktoken`) | The cap is a coarse safety valve, not an accounting system. Not worth a dependency or the wrong-tokenizer-for-the-model problem |
| 6 | Relationship notes and established facts are capped and de-duplicated in `apply_delta` | Unbounded lists | State is injected in full every turn, so unbounded growth is a context leak. Caps keep the "always inject everything" guarantee affordable |
| 7 | The opening scene is printed verbatim from `world.yaml` with no model call | Have the narrator generate turn 1 | Turn 1 is deterministic, instant, and free, and it anchors the world's voice before the model ever speaks |
| 8 | Extractor JSON is requested via `response_format={"type":"json_object"}` when the model supports it, probed once at startup | Assume support; or always prompt-enforce | Structured-output support is per-model on Novita. Probing once costs one cheap call; the fence-stripping fallback is needed either way |
| 9 | Both roles default to `zai-org/glm-4.7-flash`, kept as two separate settings | One `MODEL` setting; or a deliberately cheaper extractor | Verified served, instruct-tuned, and cheap. The roles want different things — prose quality vs. valid JSON — so keeping two names costs nothing and lets either move independently (see 11) |
| 10 | Base URL is `https://api.novita.ai/openai` | `.../openai/v1`, as the design docs originally had it | Verified against the live endpoint. The `/v1` form was wrong and would have 404'd every reviewer on turn one — the reason Gate G0 exists |
| 11 | Narrator must be an instruct-tuned model, not a reasoning model | Raise `max_tokens` until a reasoning model finishes thinking | Verified live: `deepseek-v4-flash` spent all 500 tokens in `reasoning_content` and emitted no prose. Paying for invisible deliberation before every sentence is the wrong trade for a narrator, and it makes latency unpredictable. The client now warns explicitly when a stream is reasoning-only |
