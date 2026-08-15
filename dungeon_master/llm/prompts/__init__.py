"""Every prompt in the application lives in this folder, one markdown file each.

Prompts are content, not code. Keeping them as `.md` means they can be read and
edited without touching Python, they diff cleanly when a wording change is the
whole point of a commit, and nothing has to be escaped to satisfy a string
literal.

Placeholders use `$name` / `${name}` (`string.Template`), **not** `{name}`.
That is not a style choice: `extractor_system.md` is largely a JSON schema and a
worked JSON example, and `str.format` would try to read every one of those braces
as a field. Template only touches `$`, so JSON passes through untouched.

Loaded once at import, so a missing file or a typo'd placeholder fails at
startup rather than twelve turns into someone's game.
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).parent
PLACEHOLDER = re.compile(r"\$\{?([a-zA-Z_][a-zA-Z0-9_]*)\}?")


class PromptError(Exception):
    """A prompt file is missing, or was rendered with the wrong fields."""


class Prompt:
    """One markdown prompt, with its placeholders."""

    def __init__(self, name: str, text: str) -> None:
        self.name = name
        self.text = text
        self.fields = frozenset(PLACEHOLDER.findall(text))
        self._template = Template(text)

    def render(self, **values: object) -> str:
        missing = self.fields - values.keys()
        if missing:
            raise PromptError(f"{self.name}.md is missing {sorted(missing)}")
        return self._template.substitute(**values)

    def __str__(self) -> str:  # so a promptless prompt can be used directly
        return self.text

    def __repr__(self) -> str:
        return f"Prompt({self.name!r}, fields={sorted(self.fields)})"


def load(name: str) -> Prompt:
    path = PROMPT_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"missing prompt file: {path}")
    # Trailing newlines are an artefact of the file ending, not of the prompt —
    # they matter for one-line templates joined into lists.
    return Prompt(name, path.read_text(encoding="utf-8").rstrip("\n"))


# Narrator
DM_SYSTEM = load("dm_system")
WORLD_SECTION = load("world_section")
SCENE_BLOCK = load("scene_block")
ITEM_DETAIL = load("item_detail")
NPC_NOTE = load("npc_note")
STATE_BLOCK = load("state_block")
STORY_SO_FAR = load("story_so_far")
CORRECTION_BLOCK = load("correction_block")

# Summariser
SUMMARY_PROMPT = load("summary")

# Extractor
EXTRACTOR_SYSTEM = load("extractor_system")
EXTRACTOR_USER = load("extractor_user")
RETRY_SUFFIX = load("retry_suffix")

ALL: dict[str, Prompt] = {
    name: value
    for name, value in list(globals().items())
    if isinstance(value, Prompt)
}
