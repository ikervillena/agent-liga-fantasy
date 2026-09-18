"""The judgment layer: one call to Claude, answered in a validated schema.

Deliberately a single structured call rather than an agentic tool loop, and the
reason is worth recording because the tool loop is the fashionable choice.

A loop earns its cost when the model has to explore a space too large to hand
over — hundreds of players, arbitrary follow-up questions. That is not this
problem. `analysis/candidates.py` has already reduced the competition's seven
hundred players to the handful of operations that are legal, affordable and
relevant, and the evidence for judging them is a few dozen lines. Handing that
over in one turn is cheaper, faster, reproducible, and testable against a
recorded fixture — none of which is true of a loop that decides its own path.

What the model is for is the part that is genuinely judgment: which of these is
worth doing, given a squad with particular holes, and whether there is anything
worth saying at all. It selects and explains. It never computes what something
costs and never decides what is legal.

The system prompt and the schema are stable across every call, so they sit in
the cached prefix and the volatile briefing goes last.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic
from anthropic.types import OutputConfigParam

from fantasy.agent.schemas import Judgment

Effort = Literal["low", "medium", "high", "xhigh", "max"]

PROMPT_FILE = Path(__file__).parent / "prompts" / "system.md"

#: Judgment about money gets the strong model; there are a handful of these a
#: day and the difference between a good and a mediocre signing dwarfs the cost.
MODEL = "claude-opus-5"

#: Triage — "is there anything here worth saying?" — runs far more often and
#: does not need the same depth.
TRIAGE_MODEL = "claude-sonnet-5"


class AdvisorError(RuntimeError):
    pass


def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


class Advisor:
    """Wraps the one call. Injectable so tests never reach the network."""

    def __init__(
        self,
        client: Anthropic | None = None,
        *,
        model: str = MODEL,
        effort: Effort = "high",
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort

    @property
    def available(self) -> bool:
        return bool(self._client or os.environ.get("ANTHROPIC_API_KEY"))

    def judge(self, briefing: str) -> Judgment:
        """Ask for a judgment on one briefing.

        A refusal, a malformed answer or a network failure all raise. The caller
        decides what to do about it, and in every current caller the answer is
        "stay quiet this run" — a silent agent is a nuisance, but one that
        invents a signing because a parse failed is a liability.
        """
        client = self._client or Anthropic()
        try:
            response = client.messages.parse(
                model=self._model,
                max_tokens=8000,
                thinking={"type": "adaptive"},
                output_config=OutputConfigParam(effort=self._effort),
                system=[
                    {
                        "type": "text",
                        "text": system_prompt(),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": briefing}],
                output_format=Judgment,
            )
        except Exception as exc:
            raise AdvisorError(f"the advisor call failed: {exc}") from exc

        if getattr(response, "stop_reason", None) == "refusal":
            raise AdvisorError("the model declined to answer")
        return _extract(response)


def _extract(response: Any) -> Judgment:
    """Pull the validated judgment out of the response.

    The SDK attaches it to the text block rather than the message, so the
    blocks are walked. Thinking blocks come first and carry no parsed output.
    """
    for block in getattr(response, "content", []) or []:
        parsed = getattr(block, "parsed_output", None)
        if isinstance(parsed, Judgment):
            return parsed
    raise AdvisorError("the answer carried no judgment")


__all__ = ["MODEL", "TRIAGE_MODEL", "Advisor", "AdvisorError", "system_prompt"]
