from __future__ import annotations


class StubClient:
    """Stands in for LLMClient so the deterministic half of the pipeline can be
    tested without a network call or an API key.

    Replies are returned in the order given, so a test reads as a script of what
    the model says on each call.
    """

    def __init__(self, *replies: str, json_mode: bool = True) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []
        self._json_mode = json_mode

    def complete(self, system, messages, *, model, stream=False, **kwargs):
        self.calls.append({"system": system, "messages": messages, "model": model, **kwargs})
        reply = self.replies.pop(0) if self.replies else ""
        return iter([reply]) if stream else reply

    def supports_json_mode(self, model: str) -> bool:
        return self._json_mode
