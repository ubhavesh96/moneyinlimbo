"""FallbackLlm: use Gemini when it works, switch to the offline ScriptedLlm when it does not.

Free-tier Gemini keys have tiny quotas (for example 20 requests a day per model). When Gemini
fails after its retries (quota, outage, no network) the case keeps moving on the scripted helper
instead of dying, and Gemini is not retried for a cooldown period so the user is not kept waiting.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm, Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from mil_agent import settings
from mil_agent.agents.scripted_llm import ScriptedLlm

log = logging.getLogger("mil.llm")

COOLDOWN_SECONDS = 15 * 60


class _State:
    degraded_until: float = 0.0
    reason: str = ""


state = _State()


def is_degraded() -> bool:
    return time.time() < state.degraded_until


def reset() -> None:
    state.degraded_until, state.reason = 0.0, ""


def _gemini() -> Gemini:
    return Gemini(model=settings.LLM_MODEL, retry_options=types.HttpRetryOptions(
        attempts=4, initial_delay=4.0, max_delay=30.0, exp_base=2.0, http_status_codes=[429, 500, 503]))


def _short(exc: Exception) -> str:
    text = str(exc)
    if "PerDay" in text:
        return "Gemini free daily quota used up"
    if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in text or "429" in text:
        return "Gemini rate limit reached"
    code = getattr(exc, "code", None)
    return f"Gemini unavailable ({code or type(exc).__name__})"


class FallbackLlm(BaseLlm):
    role: str = "orchestrator"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if not is_degraded():
            # ADK stamps the request with this agent's model name ("fallback-<role>"); Gemini needs the real one.
            llm_request.model = settings.LLM_MODEL
            try:
                async for resp in _gemini().generate_content_async(llm_request, stream=stream):
                    yield resp
                return
            except Exception as exc:  # fall back for any Gemini failure, not just quota
                state.degraded_until = time.time() + COOLDOWN_SECONDS
                state.reason = _short(exc)
                log.warning("%s. Using the offline helper for the next %d minutes.",
                            state.reason, COOLDOWN_SECONDS // 60)
        scripted = ScriptedLlm(model=f"scripted-{self.role}", role=self.role)
        async for resp in scripted.generate_content_async(llm_request, stream=stream):
            yield resp
