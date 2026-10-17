"""Case Tracker tools: on_event, check_sla, schedule_followup. Plus get_case for the orchestrator.

The Case Tracker is the only agent that moves a case between states (see state_machine.py). It
sends an item only after the officer approved it; the approval guard callback checks that too.
"""

from __future__ import annotations

from datetime import date, timedelta

from google.adk.tools import ToolContext

from mil_agent.models import Approval, Case, CaseUpdate, FollowUp, RouteDecision, TimelineEvent
from mil_agent.services import case_service
from mil_agent.tools.common import agent_name, done, fail, load, money
from mil_agent.tools.evidence import IO_PENDING
from mil_agent.tools.policy import refresh_rights
from mil_agent.tools.tracker_package import simulators, state_machine

AGENT = "case_tracker"
SEND_TO = {"customer_reply": "the customer", "internal_ombudsman": "the Internal Ombudsman",
           "rbi_ombudsman": "the RBI Ombudsman"}


def _add_event(case: Case, **kw) -> None:
    case.timeline.append(TimelineEvent(id=f"ev-{len(case.timeline) + 1}", date=case.today, **kw))


def _send(case: Case, kind: str) -> str:
    ap = case.approval
    if not ap or ap.kind != kind or ap.status != "approved":
        raise PermissionError(f"The officer has not approved the {kind.replace('_', ' ')}. Nothing was sent.")
    ref = simulators.acknowledgement(case, kind)
    case.sent[kind] = {"date": case.today, "reference": ref, "to": SEND_TO[kind], "by": ap.approved_by}
    ap.status = "sent"
    case.approval = None
    _add_event(case, source="Officer", kind=f"sent_{kind}", ref=ref,
               text=f"{case.drafts[kind].title} sent to {SEND_TO[kind]} after approval by {ap.approved_by}. Reference {ref}.")
    if kind == "customer_reply":
        state_machine.advance(case, "awaiting_party", f"reply sent ({ref}); waiting for the credit to post")
        r = case.rights
        due = (date.fromisoformat(case.today) + timedelta(days=1)).isoformat()
        if r and r.total_to_credit_inr:
            case.followups.append(FollowUp(due=due, what=f"Confirm {money(r.total_to_credit_inr)} credited to the customer"))
    elif kind == "internal_ombudsman":
        state_machine.advance(case, "escalated", f"referred to the Internal Ombudsman ({ref})")
        due = (date.fromisoformat(case.today) + timedelta(days=7)).isoformat()
        case.followups.append(FollowUp(due=due, what="Internal Ombudsman decision expected"))
    else:
        state_machine.advance(case, "awaiting_party", f"written response filed with the RBI Ombudsman ({ref})")
    return ref


def _process_bus(case: Case) -> tuple[list[str], bool]:
    """Apply queued events (local stand-in for Pub/Sub). Returns notes and whether to redraft."""
    notes, rbi = [], False
    for ev in case.events:
        if ev.processed:
            continue
        ev.processed = True
        if ev.topic == "reversal_posted" and case.state in ("awaiting_party", "escalated"):
            r = case.rights
            principal, comp = (r.principal_to_credit_inr, r.compensation_inr) if r else (case.amount_inr or 0, 0)
            if principal:
                _add_event(case, source="Remitter CBS", kind="reversal", amount_inr=principal, ref=case.utr,
                           text=f"Remitter CBS: reversal of {money(principal)} credited to the customer.")
            if comp:
                _add_event(case, source="Remitter CBS", kind="compensation_paid", amount_inr=comp, ref=case.utr,
                           text=f"Remitter CBS: TAT compensation of {money(comp)} credited.")
            for f in case.followups:
                f.done = f.done or f.what.startswith("Confirm")
            refresh_rights(case)
            state_machine.advance(case, "resolved", f"credit of {money(principal + comp)} posted")
            notes.append(f"Credit of {money(principal + comp)} posted; case resolved.")
        elif ev.topic == "rbi_complaint":
            _add_event(case, source="System", kind="rbi_complaint",
                       text="The customer has filed a complaint with the RBI Ombudsman (cms.rbi.org.in).")
            rbi = True
            notes.append("Customer escalated to the RBI Ombudsman.")
        elif ev.topic == "io_decision":
            ref = ev.payload.get("reference", "IO-REF")
            _add_event(case, source="System", kind="io_decision", ref=ref,
                       text=f"Internal Ombudsman concurred with the proposed rejection (reference {ref}).")
            reply = case.drafts.get("customer_reply")
            if reply:
                reply.text = reply.text.replace(IO_PENDING, ref)
                reply.original_text = reply.original_text.replace(IO_PENDING, ref)
                reply.locked_reason = None
                case.approval = Approval(kind="customer_reply", title="Approve and send the reply to the customer")
            for f in case.followups:
                f.done = f.done or f.what.startswith("Internal Ombudsman")
            notes.append("Internal Ombudsman concurred; the reply is unlocked for approval.")
    return notes, rbi


def on_event(case_id: str, event: str, kind: str = "", tool_context: ToolContext = None) -> dict:
    """React to something that happened on the case.

    event='approved' sends the item the officer approved (kind = customer_reply | internal_ombudsman |
    rbi_ombudsman); it is refused unless the officer approved exactly that item.
    event='bus' applies queued bank, customer, Internal Ombudsman and RBI events.

    Args:
        case_id: The case.
        event: approved | bus
        kind: For event='approved', which item was approved.

    Returns:
        The typed CaseUpdate.
    """
    case = load(case_id)
    prev = case.state
    rbi = False
    try:
        if event == "approved":
            ref = _send(case, kind)
            msg = f"Sent to {SEND_TO[kind]}. Reference {ref}."
        elif event == "bus":
            notes, rbi = _process_bus(case)
            msg = " ".join(notes) or "No new events."
        else:
            return fail("event must be 'approved' or 'bus'.")
    except PermissionError as e:
        return fail(str(e))
    upd = CaseUpdate(state=case.state, previous_state=prev, as_of=case.today, message=msg,  # type: ignore[arg-type]
                     escalation_level="rbi_ombudsman" if rbi and "rbi_ombudsman" not in case.sent else None)
    return done(case, agent_name(tool_context, AGENT), "on_event", msg,
                inputs={"case_id": case_id, "event": event, "kind": kind}, output=upd)


def check_sla(case_id: str, tool_context: ToolContext = None) -> dict:
    """Re-check the clocks as of the case date: turnaround breach and compensation growth, overdue
    follow-ups, and whether an escalation must be drafted.

    Args:
        case_id: The case.

    Returns:
        The typed CaseUpdate, with escalation_level 'rbi_ombudsman', 'internal_ombudsman' or null.
    """
    case = load(case_id)
    prev = case.state
    if case.state not in ("resolved", "closed"):
        refresh_rights(case)
    today = case.today
    overdue = [f for f in case.followups if not f.done and f.due < today]
    notes: list[str] = []
    r = case.rights
    if r and r.breached and case.state not in ("resolved", "closed"):
        notes.append(f"TAT breached by {r.days_overdue} day(s); compensation now {money(r.compensation_inr)}.")
    level = None
    rbi_filed = any(e.kind == "rbi_complaint" for e in case.timeline)
    if rbi_filed and "rbi_ombudsman" not in case.sent and case.state not in ("resolved", "closed"):
        if case.state == "awaiting_party":
            state_machine.advance(case, "escalated", "customer filed with the RBI Ombudsman")
        if not (case.approval and case.approval.kind == "rbi_ombudsman"):
            level = "rbi_ombudsman"
    elif (case.referral and case.referral.internal_ombudsman_required and "internal_ombudsman" not in case.sent
          and not case.drafts.get("internal_ombudsman")):
        level = "internal_ombudsman"
    if overdue and case.state == "awaiting_party":
        state_machine.advance(case, "escalated", f"follow-up missed: {overdue[0].what} (due {overdue[0].due})")
        notes.append(f"Missed follow-up: {overdue[0].what}.")
    if case.referral and today >= case.referral.rbi_eligible_from and case.state not in ("resolved", "closed"):
        notes.append(f"The customer may now approach the RBI Ombudsman (file by {case.referral.rbi_file_by}).")
    case_service.save(case)
    upd = CaseUpdate(state=case.state, previous_state=prev, as_of=today,  # type: ignore[arg-type]
                     message=" ".join(notes) or "All clocks within limits.", escalation_level=level,  # type: ignore[arg-type]
                     followups_due=[f"{f.what} (due {f.due})" for f in overdue])
    return done(case, agent_name(tool_context, AGENT), "check_sla", upd.message, output=upd,
                escalation_level=level)


def schedule_followup(case_id: str, what: str, days: int, tool_context: ToolContext = None) -> dict:
    """Schedule a follow-up against the clock (stand-in for Cloud Scheduler).

    Args:
        case_id: The case.
        what: What must be checked, in a few words.
        days: Days from the case date.
    """
    case = load(case_id)
    if not 0 < days <= 120:
        return fail("days must be between 1 and 120.")
    due = (date.fromisoformat(case.today) + timedelta(days=days)).isoformat()
    case.followups.append(FollowUp(due=due, what=what[:120]))
    return done(case, agent_name(tool_context, AGENT), "schedule_followup", f"Follow-up on {due}: {what[:120]}",
                inputs={"case_id": case_id, "what": what, "days": days})


def route(case: Case) -> RouteDecision:
    """Deterministic next step for the case: what the orchestrator should delegate to."""
    s = case.state
    if s == "intake":
        return RouteDecision(next_agent="timeline_reconstructor", reason="Documents are on file; build the timeline.")
    if s == "reconstructed":
        if case.awaiting_documents:
            return RouteDecision(next_agent=None, blocked_on_officer=True,
                                 reason=f"Waiting for a document: {case.awaiting_documents[0]}.")
        return RouteDecision(next_agent="failure_diagnoser", reason="Timeline ready; diagnose the failure point.")
    if s == "diagnosed":
        return RouteDecision(next_agent="policy_rights", reason="Diagnosis ready; apply the turnaround rule.")
    if s == "rights_computed":
        if not case.referral:
            return RouteDecision(next_agent="escalation", reason="Check whether an Internal Ombudsman referral is required.")
        return RouteDecision(next_agent="evidence_complaint", reason="Rights computed; draft the reply and evidence file.")
    if case.approval and case.approval.status == "pending":
        return RouteDecision(next_agent=None, blocked_on_officer=True,
                             reason=f"Waiting for the officer to approve: {case.approval.title}.")
    if s in ("awaiting_party", "escalated"):
        return RouteDecision(next_agent="case_tracker", reason="Watch the clocks and incoming events.")
    return RouteDecision(next_agent=None, reason=f"Nothing to do in state {s}.")


def get_case(case_id: str, tool_context: ToolContext = None) -> dict:
    """Return the case facts and the suggested next step (RouteDecision). Use it to route the case and
    to answer the officer's questions from facts only.

    Args:
        case_id: The case.
    """
    case = load(case_id)
    d, r = case.diagnosis, case.rights
    return {
        "ok": True, "summary": "Case facts attached.", "ref": case.ref, "state": case.state, "today": case.today,
        "customer": f"{case.customer_name} ({case.customer_ref})", "rail": case.rail, "bank": case.bank,
        "beneficiary": case.beneficiary, "amount_inr": case.amount_inr, "utr": case.utr, "txn_date": case.txn_date,
        "diagnosis": {"failure_point": d.effective_point, "confidence": d.confidence, "summary": d.summary,
                      "reasons": d.reasons, "missing_documents": d.missing_documents,
                      "cluster_id": d.cluster_id} if d else None,
        "rights": r.model_dump() if r else None,
        "referral": case.referral.model_dump() if case.referral else None,
        "sent": case.sent, "awaiting_approval": case.approval.title if case.approval else None,
        "followups": [f.model_dump() for f in case.followups if not f.done],
        "RouteDecision": route(case).model_dump(),
    }
