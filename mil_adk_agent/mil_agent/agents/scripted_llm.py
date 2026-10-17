"""ScriptedLlm: offline stand-in for Gemini.

Used when GOOGLE_API_KEY is unset (and as the fallback when Gemini fails). It speaks the same
function-calling protocol as Gemini, so the ADK runtime, AgentTool delegation, sessions, callbacks
and tools are all real. Only the choice of the next step is scripted: the orchestrator follows the
same RouteDecision that get_case gives Gemini.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import AsyncGenerator

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from mil_agent.services import case_service

SPECIALISTS = {"timeline_reconstructor", "failure_diagnoser", "policy_rights", "escalation",
               "evidence_complaint", "case_tracker"}


def _turn(contents: list[types.Content]) -> tuple[str, list[types.Part]]:
    """User text that started this turn + the function responses produced since."""
    start = 0
    for i, c in enumerate(contents):
        parts = c.parts or []
        if c.role == "user" and any(p.text for p in parts) and not any(p.function_response for p in parts):
            start = i
    text = " ".join(p.text or "" for p in (contents[start].parts or [])) if contents else ""
    responses = [p for c in contents[start + 1:] for p in (c.parts or []) if p.function_response]
    return text, responses


def _call(name: str, **args) -> LlmResponse:
    return LlmResponse(content=types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]))


def _say(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _field(text: str, key: str) -> str | None:
    m = re.search(rf"{key}=([\w.-]+)", text)
    return m.group(1) if m else None


def _response(part: types.Part) -> dict:
    return part.function_response.response or {}


def _result_text(part: types.Part) -> str:
    r = _response(part)
    return str(r.get("result") or r.get("summary") or r.get("error") or "")


def _last(responses: list[types.Part], name: str) -> types.Part | None:
    hits = [p for p in responses if p.function_response.name == name]
    return hits[-1] if hits else None


class ScriptedLlm(BaseLlm):
    role: str = "orchestrator"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        text, responses = _turn(llm_request.contents)
        done = Counter(p.function_response.name for p in responses)
        if self.role == "orchestrator":
            yield self._orchestrator(text, responses, done)
        else:
            yield self._specialist(text, responses, done)

    # ---- root agent -------------------------------------------------
    def _orchestrator(self, text: str, responses, done: Counter) -> LlmResponse:
        from mil_agent.tools.tracker import route  # local import: tools import agents' services

        case_id = _field(text, "case_id") or ""
        m = re.search(r"ACTION:(\w+)", text)
        action = m.group(1) if m else "chat"
        req = lambda extra="": {"request": f"case_id={case_id} {extra}".strip()}

        if action == "analyze":
            case = case_service.get(case_id)
            nxt = route(case)
            if nxt.next_agent and nxt.next_agent != "case_tracker" and not done[nxt.next_agent]:
                return _call(nxt.next_agent, **req())
            if case.awaiting_documents:
                return _say(f"Investigation paused: I need {case.awaiting_documents[0].lower()} to place the "
                            "failure with confidence. Request it, then run the investigation again.")
            if case.state == "complaint_ready":
                ap = case.approval
                return _say("Investigation complete. " + (f"Waiting for your approval: {ap.title}." if ap else
                                                          "The reply is drafted."))
            return _say(f"Stopped at state {case.state}: {nxt.reason}")

        if action == "redraft":
            if not done["evidence_complaint"]:
                return _call("evidence_complaint", **req("redraft"))
            return _say("The reply has been redrafted to reflect your override.")

        if action in ("approve", "event"):
            if not done["case_tracker"]:
                kind = _field(text, "kind")
                return _call("case_tracker", **req(f"submit kind={kind}" if kind else "check"))
            last = _last(responses, "case_tracker")
            lvl = _field(_result_text(last), "escalation_level") if last else None
            if lvl and lvl != "none" and not done["escalation"]:
                return _call("escalation", **req(f"level={lvl}"))
            case = case_service.get(case_id)
            return _say({"resolved": "The case is resolved.", "escalated": "The case is escalated; see the next step.",
                         }.get(case.state, "Done. The Case Tracker is watching the clocks."))

        # chat: answer the officer from the case facts only
        if not done["get_case"]:
            return _call("get_case", case_id=case_id)
        return _say(_chat_answer(text, _response(_last(responses, "get_case"))))

    # ---- specialists -------------------------------------------------
    def _specialist(self, text: str, responses, done: Counter) -> LlmResponse:
        case_id = _field(text, "case_id") or ""
        role = self.role
        plan: list[tuple[str, dict]] = []
        if role == "timeline_reconstructor":
            plan = [("parse_document", {"case_id": case_id}), ("normalize_events", {"case_id": case_id})]
        elif role == "failure_diagnoser":
            plan = [("lookup_known_outages", {"case_id": case_id}), ("predict_failure_point", {"case_id": case_id})]
        elif role == "policy_rights":
            rail = case_service.get(case_id).rail.replace("_", " ").lower()
            plan = [("search_policies", {"query": f"{rail} debited not credited reversal compensation"}),
                    ("compute_deadline", {"case_id": case_id}), ("compute_compensation", {"case_id": case_id})]
        elif role == "escalation":
            level = _field(text, "level")
            if level:
                plan = [("draft_escalation", {"case_id": case_id, "level": level})]
            else:
                plan = [("select_ombudsman_route", {"case_id": case_id})]
                route_resp = _last(responses, "select_ombudsman_route")
                if route_resp and _response(route_resp).get("escalation_level") == "internal_ombudsman":
                    plan.append(("draft_escalation", {"case_id": case_id, "level": "internal_ombudsman"}))
        elif role == "evidence_complaint":
            plan = ([] if "redraft" in text else [("choose_recipient", {"case_id": case_id})]) + [
                ("build_evidence_pdf", {"case_id": case_id}), ("draft_complaint", {"case_id": case_id})]
        elif role == "case_tracker":
            kind = _field(text, "kind")
            plan = ([("on_event", {"case_id": case_id, "event": "approved", "kind": kind})] if kind
                    else [("on_event", {"case_id": case_id, "event": "bus"})]) + [("check_sla", {"case_id": case_id})]
        for name, args in plan:
            if not done[name]:
                return _call(name, **args)
        lines = [_result_text(p) for p in responses if p.function_response.name != "search_policies"]
        out = " ".join(line for line in lines if line)
        if role == "case_tracker":
            sla = _last(responses, "check_sla")
            ev = _last(responses, "on_event")
            lvl = (_response(sla).get("escalation_level") if sla else None) or (
                (_response(ev).get("CaseUpdate") or {}).get("escalation_level") if ev else None)
            out += f" escalation_level={lvl or 'none'}"
        return _say(out or "Done.")


def _chat_answer(question: str, facts: dict) -> str:
    q = question.lower()
    d, r, ref = facts.get("diagnosis"), facts.get("rights"), facts.get("referral")
    if not d:
        return "The investigation has not run yet. Press 'Run investigation' first."
    if any(w in q for w in ("compensation", "owe", "how much", "amount", "pay")) and r:
        return (f"Rule {r['rule_id']}: deadline {r['deadline']} (T+{r['tat_days']}). Compensation {r['arithmetic']}. "
                f"Total to credit Rs {r['total_to_credit_inr']:,.0f}. Computed by the rules engine as of {r['as_of']}.")
    if any(w in q for w in ("deadline", "tat", "breach", "late", "overdue")) and r:
        return (f"Reversal was due by {r['deadline']}; as of {r['as_of']} it is "
                f"{r['days_overdue']} day(s) overdue." if r["breached"] else f"Reversal is due by {r['deadline']}; not breached yet.")
    if any(w in q for w in ("ombudsman", "referral", "refer", "escalat")) and ref:
        return (ref["reason"] + f" The customer may approach the RBI Ombudsman from {ref['rbi_eligible_from']} "
                f"(file by {ref['rbi_file_by']}).")
    if any(w in q for w in ("cluster", "outage", "others", "root cause")):
        return (f"This case belongs to outage cluster {d['cluster_id']}; see Insights for every affected transaction."
                if d.get("cluster_id") else "No outage cluster was found around this transaction.")
    if any(w in q for w in ("next", "now", "what should", "todo", "to do")):
        nxt = facts.get("RouteDecision", {})
        return facts.get("awaiting_approval") and f"Waiting for your approval: {facts['awaiting_approval']}." or nxt.get("reason", "")
    if any(w in q for w in ("why", "what happened", "where", "fail", "stuck", "evidence")):
        return f"{d['failure_point']} ({d['confidence']:.0%}). {d['summary']} " + " ".join(d["reasons"][:3])
    return f"{d['failure_point']} ({d['confidence']:.0%}). {d['summary']}"
