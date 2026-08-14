"""The game loop. The only module allowed to print."""

from __future__ import annotations

import logging
import sys
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from . import context
from .game import run_turn
from .llm.client import LLMClient, LLMError
from .llm.extractor import extractor_model
from .llm.narrator import narrator_model
from .memory.transcript import Transcript
from .state.store import SAVE_PATH, load, new_game, save
from .world.loader import WorldValidationError, load_world

console = Console()
log = logging.getLogger("dungeon_master")

HELP = "[dim]/state  /save  /load  /quit[/dim]"


def _setup_logging() -> None:
    logging.basicConfig(
        filename="game.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def _show_state(world, state) -> None:
    console.print(
        Panel(
            context.render_state(world, state),
            title="game state",
            border_style="cyan",
            expand=False,
        )
    )


def _list_models() -> int:
    try:
        for model_id in LLMClient().list_models():
            console.print(model_id)
    except LLMError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    return 0


def _handle_command(command, world, state, transcript):
    """Returns the (state, transcript) to carry on with, or None to quit."""
    if command in ("/quit", "/exit"):
        save(state, transcript)
        console.print("[dim]Saved. The light goes on turning without you.[/dim]")
        return None

    if command == "/state":
        _show_state(world, state)
    elif command == "/save":
        save(state, transcript)
        console.print(f"[dim]saved to {SAVE_PATH}[/dim]")
    elif command == "/load":
        if SAVE_PATH.exists():
            state, transcript = load()
            console.print(f"[dim]loaded from {SAVE_PATH}[/dim]")
            _show_state(world, state)
        else:
            console.print("[dim]no save file yet[/dim]")
    else:
        console.print(HELP)
    return state, transcript


def _print_stream(stream) -> str:
    """Hold the spinner until the first token, then stream to the screen.

    Streaming is what hides the extractor's second call behind reading time.
    """
    console.print()
    with console.status("[dim]the DM considers…[/dim]", spinner="dots"):
        first = next(stream, "")
    pieces = [first]
    console.print(first, end="", highlight=False)
    for piece in stream:
        console.print(piece, end="", highlight=False)
        pieces.append(piece)
    console.print("\n")
    return "".join(pieces)


def play() -> int:
    load_dotenv()
    _setup_logging()

    try:
        world = load_world()
    except WorldValidationError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    try:
        client = LLMClient()
    except LLMError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    state, transcript = new_game(world), Transcript()

    console.print(Rule(f"[bold]{world.meta.name}[/bold]"))
    console.print(world.meta.opening_scene.strip())
    console.print(Rule(style="dim"))
    # Show the models actually in effect. .env is gitignored, so what a reviewer
    # is running is not necessarily what .env.example says.
    console.print(
        f"[dim]narrator: {narrator_model()} · extractor: {extractor_model()}[/dim]"
    )
    console.print(HELP)

    while True:
        try:
            raw = console.input("\n[bold green]>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]The light goes on turning without you.[/dim]")
            return 0

        if not raw:
            continue

        # -- slash commands short-circuit the whole pipeline -----------------
        if raw.startswith("/"):
            outcome = _handle_command(raw.lower(), world, state, transcript)
            if outcome is None:
                return 0
            state, transcript = outcome
            continue

        # -- the turn --------------------------------------------------------
        result = run_turn(client, world, state, transcript, raw, consume=_print_stream)
        if result.failed:
            console.print(
                "[dim]The storm swallows the moment. Nothing has changed. "
                "Try again.[/dim]\n[dim](if this repeats, the reason is in "
                "game.log)[/dim]"
            )
            continue

        if result.extraction_failed:
            # Silently tracking nothing is worse than an ugly line on screen.
            console.print(
                "[yellow dim]⚠ state was not updated this turn — the extractor "
                "returned nothing usable. Check EXTRACTOR_MODEL (reasoning models "
                "often starve here) and see game.log.[/yellow dim]"
            )

        state = result.state
        save(state, transcript)


def main() -> int:
    if "--models" in sys.argv:
        load_dotenv()
        return _list_models()
    try:
        return play()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 - never show a traceback to the player
        logging.getLogger("dungeon_master").exception("fatal")
        console.print(f"[red]The Reach closes over the story. ({exc})[/red]")
        console.print("[dim]Details in game.log[/dim]")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
