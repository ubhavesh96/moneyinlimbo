import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from mil_agent.agents import fallback_llm
from mil_agent.agents.fallback_llm import FallbackLlm


def _req(text="case_id=abc"):
    return LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text=text)])])


class _Broken:
    calls = 0

    async def generate_content_async(self, req, stream=False):
        _Broken.calls += 1
        raise RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier PerDay")
        yield  # pragma: no cover


class _Working:
    async def generate_content_async(self, req, stream=False):
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="from gemini")]))


@pytest.fixture(autouse=True)
def _clean():
    fallback_llm.reset()
    _Broken.calls = 0
    yield
    fallback_llm.reset()


async def _first(llm):
    return [r async for r in llm.generate_content_async(_req())][0]


async def test_uses_gemini_when_it_works(monkeypatch):
    monkeypatch.setattr(fallback_llm, "_gemini", lambda: _Working())
    r = await _first(FallbackLlm(model="x", role="timeline_reconstructor"))
    assert r.content.parts[0].text == "from gemini" and not fallback_llm.is_degraded()


async def test_request_carries_the_real_gemini_model_name(monkeypatch):
    """ADK stamps requests with the agent's model name ('fallback-<role>'); Gemini 404s on that."""
    seen = {}

    class _Spy(_Working):
        async def generate_content_async(self, req, stream=False):
            seen["model"] = req.model
            async for r in super().generate_content_async(req, stream):
                yield r

    monkeypatch.setattr(fallback_llm, "_gemini", lambda: _Spy())
    req = _req()
    req.model = "fallback-orchestrator"
    [r async for r in FallbackLlm(model="fallback-orchestrator", role="orchestrator").generate_content_async(req)]
    assert seen["model"] == fallback_llm.settings.LLM_MODEL


async def test_falls_back_to_scripted_when_quota_is_gone(monkeypatch):
    monkeypatch.setattr(fallback_llm, "_gemini", lambda: _Broken())
    r = await _first(FallbackLlm(model="x", role="timeline_reconstructor"))
    assert r.content.parts[0].function_call.name == "parse_document"  # scripted helper answered
    assert fallback_llm.is_degraded() and "daily quota" in fallback_llm.state.reason


async def test_does_not_hammer_gemini_during_cooldown(monkeypatch):
    monkeypatch.setattr(fallback_llm, "_gemini", lambda: _Broken())
    llm = FallbackLlm(model="x", role="timeline_reconstructor")
    await _first(llm)
    await _first(llm)
    await _first(llm)
    assert _Broken.calls == 1  # one failure, then straight to the offline helper
