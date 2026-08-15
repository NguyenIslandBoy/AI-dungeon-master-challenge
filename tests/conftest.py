from __future__ import annotations

from pathlib import Path

import pytest

from dungeon_master.state.store import new_game
from dungeon_master.world.loader import load_world

FIXTURE_WORLD = Path(__file__).parent / "fixtures" / "world.yaml"


@pytest.fixture(scope="session")
def world():
    """The fixture world, not the shipped one.

    `dungeon_master/world/world.yaml` is content — it gets rewritten as the
    fiction improves, and tests that quote its ids break every time. The rules
    are tested against ids chosen to stay still; the shipped world is checked
    separately for the properties any world must have.
    """
    return load_world(FIXTURE_WORLD)


@pytest.fixture
def state(world):
    return new_game(world)
