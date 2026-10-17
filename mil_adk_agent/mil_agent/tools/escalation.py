"""Escalation tools: select_ombudsman_route, draft_escalation.

Two routes, both drafted for the officer's approval:
- Internal Ombudsman: required before the entity tells a customer it rejects the complaint
  (wholly or partly). RBI asked entities in July 2026 to refer these without exception.
- RBI Ombudsman: when the customer escalates (no reply within 30 days, or not satisfied), the
  entity files its written response with the evidence.
"""

from __future__ import annotations

from datetime import date

from google.adk.tools import ToolContext

from mil_agent.models import Approval, Case, EscalationDraft, ReferralCheck
from mil_agent.services import case_service
from mil_agent.tools.common import agent_name, done, fail, load, money
from mil_agent.tools.evidence import citations_for_facts, nice_date
from mil_agent.tools.policy import settings_days
from mil_agent.tools.policy_package import rules

AGENT = "escalation"


def referral_check(case: Case) -> ReferralCheck:
    wait, within = settings_days()
    eligible, last = rules.rbi_window(date.fromisoformat(case.received), wait, within)
    reject = case.diagnosis.failure_type == "credited_successfully"
    reason = ("Our records show the payment completed, so the proposed outcome is rejection. A complaint the entity "
              "proposes to reject must be referred to the Internal Ombudsman before the customer is told."
              if reject else
              "The complaint is upheld in full (amount and compensation), so no Internal Ombudsman referral is needed.")
    return ReferralCheck(
        proposed_outcome="reject" if reject else "uphold", internal_ombudsman_required=reject, reason=reason,
        rbi_eligible_from=eligible.isoformat(), rbi_file_by=last.isoformat(),
        rule_ids=["RBI-IO-REFERRAL-01", "RBI-IOS-2026-01"])


def select_ombudsman_route(case_id: str, tool_context: ToolContext = None) -> dict:
    """Check whether the case must go to the Internal Ombudsman before the reply, and from when the
    customer may approach the RBI Ombudsman.

    Args:
        case_id: The case. Needs a diagnosis and rights.

    Returns:
        The referral check and escalation_level ('internal_ombudsman' or null).
    """
    case = load(case_id)
    if not (case.diagnosis and case.rights):
        return fail("Diagnose the case and compute rights before the referral check.")
    case.referral = referral_check(case)
    level = ("internal_ombudsman" if case.referral.internal_ombudsman_required
             and "internal_ombudsman" not in case.sent else None)
    return done(case, agent_name(tool_context, AGENT), "select_ombudsman_route",
                ("Internal Ombudsman referral REQUIRED before replying. " if level else "No referral needed. ")
                + f"RBI Ombudsman open to the customer from {case.referral.rbi_eligible_from}.",
                output=case.referral, escalation_level=level)


def io_memo(case: Case) -> tuple[str, list[str], list]:
    c, m = citations_for_facts(case)
    d = case.diagnosis
    grounds = [
        f"The disputed debit of {money(case.amount_inr)} on {nice_date(case.txn_date)} is confirmed {m['debit']}{m['ledger']}.",
        f"The payment completed: {case.beneficiary or 'the beneficiary bank'} credited the payee {m['beneficiary']}.",
        "No timeout, decline or pending status appears in the switch or core-banking records, so no turnaround "
        "time applies and no compensation is due.",
    ]
    text = "\n".join([
        f"To: Internal Ombudsman, {case.bank or 'the Bank'}",
        f"From: {case.assigned_officer}, Grievance Redressal Officer",
        f"Subject: Referral before rejection: complaint {case.ref} ({case.customer_ref})",
        "",
        f"The customer complains that {money(case.amount_inr)} sent on {nice_date(case.txn_date)} did not reach "
        f"the payee (reference {case.utr}). We propose to reject the complaint, and refer it to you as required "
        f"{m.get('io', '')} before the final reply is sent.",
        "",
        "Grounds:",
        *[f"{i}. {g}" for i, g in enumerate(grounds, 1)],
        "",
        f"Diagnosis confidence: {d.confidence:.0%}. The evidence file and the draft reply are attached to the case. "
        "Please confirm or overturn the proposed decision.",
    ])
    text, cites = c.finalize(text)
    return text, _renumbered(grounds, text), cites


def rbi_response(case: Case) -> tuple[str, list[str], list]:
    c, m = citations_for_facts(case)
    r = case.rights
    sent = case.sent.get("customer_reply", {})
    grounds = [
        f"Debit of {money(case.amount_inr)} on {nice_date(case.txn_date)} {m['debit']}; failure point: "
        f"{case.diagnosis.effective_point} {m['failure'] or m['merchant']}.",
        f"Applicable rule {r.rule_id}: reversal due {nice_date(r.deadline)} {m['rule']}.",
        f"Compensation computed by rule: {r.arithmetic}.",
        (f"Reply sent to the customer on {nice_date(sent.get('date'))} (reference {sent.get('reference')})."
         if sent else "No reply had been sent to the customer."),
    ]
    text = "\n".join([
        "To: Office of the RBI Ombudsman (via cms.rbi.org.in)",
        f"From: Principal Nodal Officer, {case.bank or 'the Bank'}",
        f"Subject: Written response: complaint by {case.customer_name} ({case.customer_ref}), our reference {case.ref}",
        "",
        "Facts established from the customer's documents and our records:",
        *[f"{i}. {g}" for i, g in enumerate(grounds, 1)],
        "",
        f"Action: we will credit {money(r.principal_to_credit_inr)} and compensation of {money(r.compensation_inr)} "
        f"(total {money(r.total_to_credit_inr)}) and will confirm the posting to the Ombudsman's office. "
        "The evidence file and audit trail are enclosed.",
    ])
    text, cites = c.finalize(text)
    return text, _renumbered(grounds, text), cites


def _renumbered(grounds: list[str], text: str) -> list[str]:
    """The grounds as they read in the finalized text (same footnote numbers)."""
    lines = text.splitlines()
    return [next((ln.split(". ", 1)[1] for ln in lines if ln.startswith(f"{i}. ")), g)
            for i, g in enumerate(grounds, 1)]


def draft_escalation(case_id: str, level: str, tool_context: ToolContext = None) -> dict:
    """Draft the escalation document and queue it for the officer's approval. Nothing is sent.

    Args:
        case_id: The case.
        level: internal_ombudsman | rbi_ombudsman

    Returns:
        The typed EscalationDraft.
    """
    case = load(case_id)
    if level not in ("internal_ombudsman", "rbi_ombudsman"):
        return fail("level must be 'internal_ombudsman' or 'rbi_ombudsman'.")
    if level in case.sent:
        return fail(f"The {level.replace('_', ' ')} step has already been sent.")
    if not (case.diagnosis and case.rights):
        return fail("The case must be investigated before escalation.")
    if level == "internal_ombudsman":
        text, grounds, cites = io_memo(case)
        title, to = "Referral to the Internal Ombudsman", f"Internal Ombudsman, {case.bank or 'the Bank'}"
    else:
        text, grounds, cites = rbi_response(case)
        title, to = "Written response to the RBI Ombudsman", "Office of the RBI Ombudsman (cms.rbi.org.in)"
    draft = EscalationDraft(kind=level, level=level, title=title, to=to, text=text, original_text=text,  # type: ignore[arg-type]
                            grounds=grounds, citations=cites)
    case.drafts[level] = draft
    case.approval = Approval(kind=level, title=f"Approve and send: {title.lower()}")  # type: ignore[arg-type]
    case_service.save(case)
    return done(case, agent_name(tool_context, AGENT), "draft_escalation",
                f"{title} drafted with {len(grounds)} grounds. Waiting for the officer's approval.",
                inputs={"case_id": case_id, "level": level}, output=draft)
