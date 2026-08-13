"""Rolling compression of the episodic tier.

Deliberately lossy, and explicitly told not to duplicate anything the structured
state already owns — two versions of the same fact can disagree, and then the
prose version is wrong.
"""

from __future__ import annotations

import logging
import os

from ..llm import prompts
from ..llm.client import LLMClient, LLMError
from .transcript import VERBATIM_TURNS, Transcript

log = logging.getLogger(__name__)


def maybe_compress(
    client: LLMClient, transcript: Transcript, *, keep: int = VERBATIM_TURNS
) -> bool:
    """Fold turns that have aged out of the verbatim window into the digest.

    Returns True if the summary was regenerated. Failure is non-fatal: an
    un-compressed transcript is merely more expensive, not incorrect.
    """
    pending = transcript.pending_compression(keep)
    if not pending:
        return False

    joined = "\n\n".join(f"Player: {t.player}\nDM: {t.dm}" for t in pending)
    prompt = prompts.SUMMARY_PROMPT.format(
        previous=transcript.summary or "(nothing yet)", turns=joined
    )

    try:
        summary = client.complete(
            prompt,
            [{"role": "user", "content": "Write the digest."}],
            model=os.environ.get("EXTRACTOR_MODEL", "zai-org/glm-4.7-flash"),
            max_tokens=300,
            temperature=0.3,
        )
    except LLMError as exc:
        log.warning("summariser failed, keeping previous digest: %s", exc)
        return False

    assert isinstance(summary, str)
    transcript.summary = summary.strip()
    transcript.compressed_through = len(transcript.turns) - keep
    log.info("summary regenerated through turn %s", transcript.compressed_through)
    return True
