"""Prompts are content in `.md` files, so the loader is what keeps them honest.

A typo in a prompt must fail at import, not twelve turns into someone's game.
"""

from __future__ import annotations

import re

import pytest

from dungeon_master.llm import prompts
from dungeon_master.llm.prompts import Prompt, PromptError, load


def test_every_prompt_file_loaded():
    on_disk = {p.stem for p in prompts.PROMPT_DIR.glob("*.md")}
    loaded = {p.name for p in prompts.ALL.values()}
    assert on_disk == loaded, "a .md file exists that nothing loads, or vice versa"


def test_a_missing_prompt_fails_loudly():
    with pytest.raises(PromptError, match="missing prompt file"):
        load("no_such_prompt")


def test_rendering_without_a_field_fails_loudly():
    with pytest.raises(PromptError, match=r"missing \['summary'\]"):
        prompts.STORY_SO_FAR.render()


def test_render_substitutes_every_field():
    out = prompts.STORY_SO_FAR.render(summary="the sea kept its counsel")
    assert "the sea kept its counsel" in out
    assert "$" not in out


def test_no_prompt_contains_a_stale_brace_placeholder():
    """These were `str.format` templates once. A leftover `{name}` would render
    as literal text and silently omit the value."""
    stale = re.compile(r"(?<!\$)\{[a-z_]+\}")  # not the braces of a ${name}
    for prompt in prompts.ALL.values():
        # extractor_system is a JSON schema; its braces are always followed by a
        # quote or a newline, never a bare lowercase identifier.
        assert not stale.search(prompt.text), f"{prompt.name}.md has a stale placeholder"


def test_json_braces_survive_the_template_engine():
    """The reason for `$name` over `{name}`: extractor_system.md is mostly JSON,
    and `str.format` would read every brace in it as a field."""
    text = prompts.EXTRACTOR_SYSTEM.text
    assert '"move_to"' in text and '{"npc_id"' in text
    assert prompts.EXTRACTOR_SYSTEM.fields == frozenset()


def test_single_line_prompts_do_not_carry_a_trailing_newline():
    """ITEM_DETAIL and NPC_NOTE are joined into lists; a trailing newline from
    the file would open blank lines in the middle of the scene block."""
    for prompt in (prompts.ITEM_DETAIL, prompts.NPC_NOTE):
        assert not prompt.text.endswith("\n")


def test_prompt_str_returns_its_text():
    p = Prompt("x", "hello")
    assert str(p) == "hello"


def test_the_hard_rules_are_all_present():
    """Each of these exists because a model broke it in a real session; a silent
    drop during an edit would be expensive to notice."""
    text = prompts.DM_SYSTEM.text
    for marker in ("1.", "2.", "2a. MOVEMENT", "2b.", "3.", "4.", "5.", "6."):
        assert marker in text, f"hard rule {marker} went missing from dm_system.md"
