"""The retry budget, which had no test and therefore drifted.

Observed live: Novita answered `429 server overload` on roughly a quarter of
calls in one session, and every one of them cost a whole turn. The budget looked
like two attempts. It was really six requests — the OpenAI SDK retries twice
inside each of ours — and none of that was legible from the code.
"""

from __future__ import annotations

import pytest
from openai import APIStatusError, RateLimitError

from dungeon_master.llm.client import ATTEMPTS, MAX_BACKOFF, LLMClient, LLMError


class _Response:
    """Duck-types the bit of the response the SDK's error classes read. The real
    type lives in a vendored `httpx2`, which is not worth importing by name."""

    def __init__(self, status: int) -> None:
        self.status_code = status
        self.request = object()
        self.headers: dict[str, str] = {}


def _error(status: int) -> APIStatusError:
    kind = RateLimitError if status == 429 else APIStatusError
    return kind("boom", response=_Response(status), body=None)


class _Endpoint:
    """Fails with `status` for the first `failures` calls, then succeeds."""

    def __init__(self, status: int, failures: int) -> None:
        self.status, self.failures, self.calls = status, failures, 0

    def create(self, **_):
        self.calls += 1
        if self.calls <= self.failures:
            raise _error(self.status)
        return type(
            "Response",
            (),
            {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})()})()]},
        )()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("dungeon_master.llm.client.time.sleep", lambda _: None)
    return LLMClient(api_key="test-key")


def _wire(client, endpoint) -> None:
    client._client.chat.completions.create = endpoint.create


def test_the_sdk_does_not_retry_underneath_us(client):
    """One retry layer, not two. If the SDK is also retrying, the number in the
    code is a third of the requests actually issued."""
    assert client._client.max_retries == 0


def test_an_overload_burst_is_ridden_out_rather_than_costing_the_turn(client):
    endpoint = _Endpoint(429, failures=ATTEMPTS - 1)
    _wire(client, endpoint)

    result = client.complete("sys", [{"role": "user", "content": "hi"}], model="m")

    assert result == "ok"
    assert endpoint.calls == ATTEMPTS


def test_a_long_enough_outage_still_gives_up_rather_than_hanging(client):
    endpoint = _Endpoint(429, failures=ATTEMPTS + 5)
    _wire(client, endpoint)

    with pytest.raises(LLMError):
        client.complete("sys", [{"role": "user", "content": "hi"}], model="m")

    assert endpoint.calls == ATTEMPTS  # bounded, not infinite


def test_backoff_is_capped_so_the_wait_stays_inside_a_players_patience(monkeypatch):
    """Doubling forever would put a 60s+ sleep in front of a blocking turn."""
    waits: list[float] = []
    monkeypatch.setattr("dungeon_master.llm.client.time.sleep", waits.append)
    client = LLMClient(api_key="test-key")
    endpoint = _Endpoint(429, failures=ATTEMPTS + 5)
    _wire(client, endpoint)

    with pytest.raises(LLMError):
        client.complete("sys", [{"role": "user", "content": "hi"}], model="m")

    assert waits == [2, 4, 8, 8]
    assert max(waits) == MAX_BACKOFF
    assert sum(waits) <= 25, "a turn must not stall longer than a spinner can carry"


def test_both_roles_fall_back_to_the_same_documented_default(monkeypatch):
    """DECISIONS 9: two settings, one default. When the narrator's default moved
    off a reasoning model (DECISIONS 26) the extractor's was left behind, so the
    code claimed one thing and the README another. The extractor's failure is the
    quieter of the two — it returns empty content, the delta is dropped, and the
    prose still reads fine — so it is the one worth pinning."""
    from dungeon_master.llm.extractor import DEFAULT_MODEL as EXTRACTOR_DEFAULT
    from dungeon_master.llm.extractor import extractor_model
    from dungeon_master.llm.narrator import DEFAULT_MODEL as NARRATOR_DEFAULT
    from dungeon_master.llm.narrator import narrator_model

    assert NARRATOR_DEFAULT == EXTRACTOR_DEFAULT

    monkeypatch.delenv("NARRATOR_MODEL", raising=False)
    monkeypatch.delenv("EXTRACTOR_MODEL", raising=False)
    assert narrator_model() == extractor_model() == NARRATOR_DEFAULT


def test_a_400_still_breaks_out_immediately(client):
    """Decision 21: the json-mode probe 400s on models that lack support, and it
    will be just as wrong the fifth time. Widening the budget must not make
    startup five times slower."""
    endpoint = _Endpoint(400, failures=99)
    _wire(client, endpoint)

    with pytest.raises(LLMError):
        client.complete("sys", [{"role": "user", "content": "hi"}], model="m")

    assert endpoint.calls == 1
