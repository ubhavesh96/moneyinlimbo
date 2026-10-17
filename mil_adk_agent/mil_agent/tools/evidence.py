"""Evidence and Complaint tools: choose_recipient, build_evidence_pdf, draft_complaint, revise_complaint.

The draft is the entity's reply to the customer. Every factual sentence carries a footnote to the
document, bank record or rule it rests on. Nothing is sent: the officer approves first.
"""

from __future__ import annotations

import re
from datetime import date

from google.adk.tools import ToolContext

from mil_agent.models import Approval, Case, Citation, ComplaintDraft
from mil_agent.services import case_service
from mil_agent.tools.common import agent_name, done, fail, load, money
from mil_agent.tools.evidence_package import pdfgen
from mil_agent.tools.policy import policies, rule_by_id, settings_days
from mil_agent.tools.policy_package import rules
from mil_agent.tools.tracker_package import state_machine

AGENT = "evidence_complaint"
IO_PENDING = "[Internal Ombudsman review reference]"


def nice_date(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d %b %Y") if iso else "n/a"


class Cites:
    """Footnote registry: the same source always gets the same number."""

    def __init__(self):
        self.items: list[Citation] = []

    def __call__(self, label: str, source: str, ref: str = "", url: str | None = None) -> str:
        for c in self.items:
            if c.ref == ref and c.label == label:
                return f"[{c.n}]"
        c = Citation(n=len(self.items) + 1, label=label, source=source, ref=ref, url=url)
        self.items.append(c)
        return f"[{c.n}]"

    def event(self, case: Case, kind: str, source: str | None = None) -> str:
        e = next((e for e in case.timeline if e.kind == kind and (source is None or e.source == source)), None)
        if not e:
            return ""
        doc = next((d for d in case.documents if d.id == e.doc_id), None)
        return self(f"{e.source}, {nice_date(e.date)}{' ' + e.time if e.time else ''}",
                    doc.name if doc else e.source, ref=e.doc_id or e.id)

    def rule(self, rule_id: str) -> str:
        r = rule_by_id(rule_id)
        return self(f"{r['id']}: {r['title']}", r["source"], ref=r["id"], url=r.get("url"))

    def finalize(self, text: str) -> tuple[str, list[Citation]]:
        """Keep only the footnotes the text uses, renumbered in reading order."""
        order: list[int] = []
        for n in re.findall(r"\[(\d+)\]", text):
            if int(n) not in order:
                order.append(int(n))
        remap = {old: new for new, old in enumerate(order, 1)}
        text = re.sub(r"\[(\d+)\]", lambda m: f"[{remap.get(int(m.group(1)), m.group(1))}]", text)
        by_n = {c.n: c for c in self.items}
        return text, [by_n[old].model_copy(update={"n": new}) for old, new in remap.items() if old in by_n]


def days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


def citations_for_facts(case: Case) -> tuple[Cites, dict[str, str]]:
    """Footnotes for the facts every draft relies on, numbered in reading order."""
    c = Cites()
    marks = {
        "debit": c.event(case, "debit", "Bank statement") or c.event(case, "debit_posted"),
        "ledger": c.event(case, "debit_posted", "Remitter CBS") or c.event(case, "debit_sms"),
        "failure": (c.event(case, "credit_failed", "NPCI switch") or c.event(case, "atm_failed")
                    or c.event(case, "confirmation_missing") or c.event(case, "credit_failed")),
        "beneficiary": c.event(case, "beneficiary_credited") or c.event(case, "credit_failed", "Beneficiary CBS"),
        "merchant": c.event(case, "merchant_not_paid"),
        "no_reversal": c.event(case, "reversal_missing"),
        "reversal": c.event(case, "reversal"),
    }
    if case.rights:
        marks["rule"] = c.rule(case.rights.rule_id)
    marks["scheme"] = c.rule("RBI-IOS-2026-01")
    if case.referral and case.referral.internal_ombudsman_required:
        marks["io"] = c.rule("RBI-IO-REFERRAL-01")
    return c, marks


def _rbi_line(case: Case, mark: str) -> str:
    wait, within = settings_days()
    eligible, last = rules.rbi_window(date.fromisoformat(case.received), wait, within)
    return (f"If you are not satisfied with this reply, you may complain to the RBI Ombudsman at cms.rbi.org.in, "
            f"free of charge, from {eligible:%d %b %Y} if the matter is still unresolved, and no later than "
            f"{last:%d %b %Y} {mark}. Helpline 14448.")


def reply_text(case: Case, officer: str) -> tuple[str, list[Citation]]:
    c, m = citations_for_facts(case)
    d, r = case.diagnosis, case.rights
    amt, when = money(case.amount_inr), nice_date(case.txn_date)
    utr_label = "UTR" if case.rail in ("UPI", "UPI_MERCHANT", "IMPS") else "RRN"
    head = [
        f"To: {case.customer_name or 'Customer'} ({case.customer_ref})",
        f"From: Grievance Redressal Cell, {case.bank or 'the Bank'}",
        f"Subject: Your complaint {case.ref}: {amt} on {when} ({utr_label} {case.utr or 'n/a'})",
        "",
        f"Dear {case.customer_name or 'Customer'},",
        "",
        f"Thank you for your complaint received on {nice_date(case.received)}. We have investigated it using "
        "your documents and our own payment records.",
        "",
    ]
    body: list[str] = []
    if d.failure_type == "credited_successfully":
        body += [
            f"What we found: {amt} was debited from your account on {when} {m['debit']}{m['ledger']}. Our records "
            f"show that the payment completed and {case.beneficiary or 'the beneficiary bank'} credited the payee's "
            f"account {m['beneficiary']}. The money is not held by us or stuck in the payment system.",
            "",
            "Our decision: we are unable to reverse this transaction. Please ask the payee to check their account "
            f"statement for {utr_label} {case.utr}. This decision has been reviewed by our Internal Ombudsman "
            f"{m.get('io', '')} (reference {IO_PENDING}).",
        ]
    else:
        failed = {
            "Beneficiary bank": f"the payee's bank, {case.beneficiary}, did not complete the credit",
            "NPCI switch": "the payment network timed out before the credit could complete",
            "Gateway": f"the payment gateway did not confirm your payment to {case.beneficiary}",
            "Acquiring bank": ("the ATM did not dispense cash" if case.rail == "ATM"
                               else f"the merchant's bank did not confirm the charge at {case.beneficiary}"),
            "Remitter bank": "our own system did not complete the payment",
        }.get(d.effective_point, "the payment did not complete")
        evidence = m["failure"] or m["merchant"]
        body.append(f"What happened: {amt} was debited from your account on {when} {m['debit']}{m['ledger']}. "
                    f"However, {failed} {evidence}"
                    + (f" and no automatic reversal followed {m['no_reversal']}." if m["no_reversal"] else "."))
        body.append("")
        rule_line = (f"Under the RBI rules for failed transactions, this amount had to be returned by "
                     f"{nice_date(r.deadline)} (T+{r.tat_days}) {m['rule']}.")
        if r.reversal_done:
            act = (f"The amount was returned to your account {m['reversal']}. "
                   + (f"Because it was returned {days(r.days_overdue)} late, we are crediting compensation of "
                      f"{money(r.compensation_inr)} ({r.arithmetic}) {m['rule']}." if r.compensation_inr else
                      "It was returned on time, so no compensation is due."))
        elif r.breached:
            act = (f"We are crediting {money(r.principal_to_credit_inr)} to your account, together with compensation "
                   f"of {money(r.compensation_inr)} for {days(r.days_overdue)} of delay ({r.arithmetic}) "
                   f"{m['rule']}. Total: {money(r.total_to_credit_inr)}.")
        else:
            act = (f"We are crediting {money(r.principal_to_credit_inr)} to your account now, within that deadline, "
                   f"so no compensation is due.")
        body += ["What we will do: " + rule_line + " " + act]
    tail = ["", _rbi_line(case, m["scheme"]), "", "Yours sincerely,", officer,
            f"Grievance Redressal Officer, {case.bank or 'the Bank'}"]
    return c.finalize("\n".join(head + body + tail))


def choose_recipient(case_id: str, tool_context: ToolContext = None) -> dict:
    """Decide who the reply goes to and in what order: the customer, and first the Internal
    Ombudsman when the entity proposes to reject the complaint.

    Args:
        case_id: The case.
    """
    case = load(case_id)
    if not case.referral:
        return fail("Run the referral check (select_ombudsman_route) first.")
    seq = (["internal_ombudsman", "customer"] if case.referral.internal_ombudsman_required else ["customer"])
    why = ("The complaint is proposed for rejection, so the Internal Ombudsman must review it before the customer "
           "is told." if len(seq) == 2 else "The complaint is upheld; the reply goes straight to the customer.")
    return done(case, agent_name(tool_context, AGENT), "choose_recipient", why,
                recipient="customer", sequence=seq)


def build_evidence_pdf(case_id: str, tool_context: ToolContext = None) -> dict:
    """Build the regulator-ready evidence file (timeline with sources, diagnosis, rule maths,
    referral check, citations) as a PDF with a SHA-256 fingerprint of the facts.

    Args:
        case_id: The case. Needs diagnosis and rights.
    """
    case = load(case_id)
    if not (case.diagnosis and case.rights):
        return fail("Diagnosis and rights must be completed before building the evidence file.")
    path = case_service.case_dir(case.id) / "evidence.pdf"
    case.evidence_sha256 = pdfgen.build_pdf(case, path, policies()["disclaimer"])
    return done(case, agent_name(tool_context, AGENT), "build_evidence_pdf",
                f"Evidence file ready: {len(case.timeline)} events, {len(case.documents)} sources, "
                f"fingerprint {case.evidence_sha256[:12]}.", sha256=case.evidence_sha256)


def draft_complaint(case_id: str, tool_context: ToolContext = None) -> dict:
    """Draft the entity's cited reply to the customer and queue it for the officer's approval.
    Nothing is sent.

    Args:
        case_id: The case. Needs diagnosis, rights and the referral check.

    Returns:
        The typed ComplaintDraft.
    """
    case = load(case_id)
    if not (case.diagnosis and case.rights and case.referral):
        return fail("Diagnosis, rights and the referral check must be done before drafting the reply.")
    text, cites = reply_text(case, case.assigned_officer)
    locked = ("Waiting for the Internal Ombudsman's review" if case.referral.internal_ombudsman_required
              and "internal_ombudsman" not in case.sent else None)
    draft = ComplaintDraft(title="Reply to the customer", to=f"{case.customer_name} ({case.customer_ref})",
                           text=text, original_text=text, citations=cites, locked_reason=locked)
    case.drafts["customer_reply"] = draft
    if not locked:
        case.approval = Approval(kind="customer_reply", title="Approve and send the reply to the customer")
    case_service.save(case)
    if case.state == "rights_computed":
        state_machine.advance(case, "complaint_ready", "reply and evidence file drafted")
    return done(case, agent_name(tool_context, AGENT), "draft_complaint",
                "Reply drafted with %d citation(s). %s" % (
                    len(cites), "Locked until the Internal Ombudsman has reviewed it." if locked
                    else "Waiting for the officer's approval; nothing has been sent."),
                output=draft)


_FACT_RE = re.compile(r"\[\d+\]|Rs [\d,]+(?:\.\d+)?|\d{12}|\d{2} [A-Z][a-z]{2} \d{4}|T\+\d")


def revise_complaint(case_id: str, text: str, tool_context: ToolContext = None) -> dict:
    """Replace the reply's wording with a clearer version. Every figure, date, reference and
    citation marker must stay exactly as it is; the change is refused otherwise.

    Args:
        case_id: The case.
        text: The full improved reply.
    """
    case = load(case_id)
    draft = case.drafts.get("customer_reply")
    if not draft:
        return fail("There is no reply draft to revise yet.")
    missing = sorted(set(_FACT_RE.findall(draft.text)) - set(_FACT_RE.findall(text)))
    if missing:
        return fail(f"Revision refused: it drops or changes facts {missing[:5]}. Keep every figure and citation.")
    draft.text = draft.original_text = text
    return done(case, agent_name(tool_context, AGENT), "revise_complaint", "Reply wording polished; facts unchanged.")
