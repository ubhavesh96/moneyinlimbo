"""Run one ADK agent on its own through the real Runner and report what it did."""

from __future__ import annotations

from dataclasses import dataclass, field

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


@dataclass
class Run:
    final: str = ""
    calls: list[str] = field(default_factory=list)  # tool-call trajectory, in order


async def run_agent(agent, text: str) -> Run:
    svc = InMemorySessionService()
    runner = Runner(app_name="mil_test", agent=agent, session_service=svc)
    await svc.create_session(app_name="mil_test", user_id="u", session_id="s")
    out = Run()
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for ev in runner.run_async(user_id="u", session_id="s", new_message=msg):
        out.calls += [c.name for c in ev.get_function_calls()]
        if ev.is_final_response() and ev.content and ev.content.parts:
            out.final = " ".join(p.text for p in ev.content.parts if p.text)
    return out
