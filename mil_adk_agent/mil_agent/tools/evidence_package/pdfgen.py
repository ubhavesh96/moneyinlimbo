"""Regulator-ready evidence file (PDF) with a tamper-evident fingerprint of the facts."""

from __future__ import annotations

import hashlib
import json

from fpdf import FPDF

from mil_agent.models import Case


def _t(s: str) -> str:
    """Core PDF fonts are latin-1 only."""
    return (s.replace("₹", "Rs ").replace("→", "->").replace("–", "-").replace("—", "-")
            .encode("latin-1", "replace").decode("latin-1"))


def facts_hash(case: Case) -> str:
    facts = {
        "utr": case.utr,
        "timeline": [e.model_dump() for e in case.timeline],
        "diagnosis": case.diagnosis.model_dump() if case.diagnosis else None,
        "rights": case.rights.model_dump() if case.rights else None,
        "referral": case.referral.model_dump() if case.referral else None,
    }
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def build_pdf(case: Case, path, disclaimer: str) -> str:
    sha = facts_hash(case)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def h(txt):
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _t(txt), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9.5)

    def p(txt, style=""):
        pdf.set_font("Helvetica", style, 9.5)
        pdf.multi_cell(0, 5, _t(txt), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _t(f"Evidence file: complaint {case.ref}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _t(f"{case.bank or 'Regulated entity'} | Grievance Redressal Cell | trace {case.trace_id} | "
                      f"as of {case.today}"), new_x="LMARGIN", new_y="NEXT")
    p("SYNTHETIC DEMO DATA. Prepared by the Money in Limbo investigation agent for officer review.", "I")

    h("1. Complaint")
    p(f"Customer {case.customer_name} ({case.customer_ref}); received {case.received} via {case.channel}.")
    amt = f"Rs {case.amount_inr:,.2f}" if case.amount_inr else "n/a"
    p(f"Rail {case.rail}; amount {amt}; reference {case.utr or 'n/a'}; transaction date {case.txn_date or 'n/a'}; "
      f"beneficiary {case.beneficiary or 'n/a'}.")

    h("2. Payment trail (each line cites its source)")
    names = {d.id: d.name for d in case.documents}
    for e in case.timeline:
        p(f"{e.id}  {e.date} {e.time or '     '}  [{e.source}] {e.text}  <{names.get(e.doc_id, '-')}>")
        if e.snippet:
            p(f"      source line: {e.snippet[:200]}", "I")

    d = case.diagnosis
    if d:
        h("3. Diagnosis (AI-proposed, officer to confirm)")
        p(f"Failure point: {d.effective_point}   Confidence: {d.confidence:.0%}   Type: {d.failure_type}")
        if d.override:
            p(f"Officer override: {d.override.failure_point} by {d.override.by} ({d.override.reason})", "B")
        p(d.summary)
        for r in d.reasons:
            p(f"- {r}")

    r = case.rights
    if r:
        h("4. Turnaround and compensation (computed by the rules engine, not by AI)")
        p(f"Rule {r.rule_id}: {r.rule_title}. Source: {r.rule_source}."
          + ("" if r.rule_verified else " RULE PENDING VERIFICATION."))
        p(f"T = {r.txn_date}; turnaround T+{r.tat_days} ({r.tat_basis}); deadline {r.deadline}; "
          f"as of {r.as_of}: {r.days_overdue} day(s) overdue.")
        p(f"Compensation: {r.arithmetic}. Reversal posted: {'yes' if r.reversal_done else 'no'}. "
          f"Principal to credit Rs {r.principal_to_credit_inr:,.2f}; total to credit Rs {r.total_to_credit_inr:,.2f}.")

    if case.referral:
        h("5. Internal Ombudsman and RBI Ombudsman")
        ref = case.referral
        p(f"Proposed outcome: {ref.proposed_outcome}. Internal Ombudsman referral required: "
          f"{'YES' if ref.internal_ombudsman_required else 'no'}. {ref.reason}")
        p(f"Customer may approach the RBI Ombudsman from {ref.rbi_eligible_from}; last date to file {ref.rbi_file_by}.")

    reply = case.drafts.get("customer_reply")
    if reply and reply.citations:
        h("6. Citations used in the reply")
        for c in reply.citations:
            p(f"[{c.n}] {c.label} - {c.source}")

    h("7. Approval record")
    approved = [x for x in case.decisions if x.action == "approved"]
    if approved:
        for x in approved:
            p(f"{x.kind} approved by {x.actor} ({x.role}) at {x.at}.")
    else:
        p("Not yet approved. Nothing has been sent to the customer.")

    h("Source documents")
    for doc in case.documents:
        p(f"- {doc.id} {doc.name} ({doc.kind}, {'customer' if doc.origin == 'customer' else 'bank records'})")
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.multi_cell(0, 4, _t(disclaimer), new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 4, _t(f"Fingerprint (SHA-256 of the facts in sections 2-5): {sha}"), new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))
    return sha
