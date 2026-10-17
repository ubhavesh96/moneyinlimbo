"""Runs the ADK root agent for a case. One ADK session per case, one lock per case."""

from __future__ import annotations

import asyncio
import logging

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from mil_agent import settings
from mil_agent.agents.routers import root_agent
from mil_agent.services import case_service

log = logging.getLogger("mil.runner")
_sessions = InMemorySessionService()
_runner = Runner(app_name=settings.APP_NAME, agent=root_agent, session_service=_sessions)
_locks: dict[str, asyncio.Lock] = {}

STEP_LABELS = {
    "timeline_reconstructor": (1, "Reconstructing the payment trail"),
    "failure_diagnoser": (2, "Diagnosing the failure point"),
    "policy_rights": (3, "Checking turnaround and compensation rules"),
    "escalation": (4, "Checking ombudsman referral"),
    "evidence_complaint": (5, "Drafting the reply and evidence file"),
    "case_tracker": (5, "Updating the case"),
}


async def _ensure_session(case_id: str) -> None:
    s = await _sessions.get_session(app_name=settings.APP_NAME, user_id=settings.USER_ID, session_id=case_id)
    if s is None:
        await _sessions.create_session(app_name=settings.APP_NAME, user_id=settings.USER_ID, session_id=case_id)


def _note_step(case_id: str, event) -> None:
    for call in event.get_function_calls():
        if call.name in STEP_LABELS:
            n, label = STEP_LABELS[call.name]
            case = case_service.get(case_id)
            case.step = f"{n}/5 {label}"
            case_service.save(case)


async def ask(case_id: str, message: str) -> str:
    """Send one message to the orchestrator and return its final text."""
    await _ensure_session(case_id)
    final = ""
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async for event in _runner.run_async(user_id=settings.USER_ID, session_id=case_id, new_message=content):
        _note_step(case_id, event)
        if event.is_final_response() and event.content and event.content.parts and event.author == root_agent.name:
            final = " ".join(p.text for p in event.content.parts if p.text) or final
    return final


async def run_action(case_id: str, action: str, extra: str = "") -> str:
    """Run an orchestrator action in the background, flagging the case as running meanwhile."""
    lock = _locks.setdefault(case_id, asyncio.Lock())
    async with lock:
        case = case_service.get(case_id)
        case.running, case.error, case.step = True, None, "0/5 Starting"
        if action == "analyze":
            case.analysis_started_at = case_service.now_iso()
        case_service.save(case)
        try:
            return await ask(case_id, f"[ACTION:{action}] case_id={case_id} {extra}".strip())
        except Exception as exc:  # surface to the UI instead of dying silently
            log.exception("agent run failed")
            case = case_service.get(case_id)
            case.error = f"The agent run failed: {exc}"
            return ""
        finally:
            case = case_service.get(case_id)
            case.running, case.step = False, None
            case_service.save(case)
