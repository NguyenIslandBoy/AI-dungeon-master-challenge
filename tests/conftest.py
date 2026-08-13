from __future__ import annotations

import pytest

from dungeon_master.state.store import new_game
from dungeon_master.world.loader import load_world


@pytest.fixture(scope="session")
def world():
    return load_world()


@pytest.fixture
def state(world):
    return new_game(world)
