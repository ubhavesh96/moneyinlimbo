import re

from mil_agent.agents.subagents import evidence_complaint
from mil_agent.services import case_service
from mil_agent.tools import evidence
from tests.unit.helpers import run_agent


async def test_builds_file_and_drafts_cited_reply_without_sending(case_at):
    c = case_at("A", "route")
    run = await run_agent(evidence_complaint, f"case_id={c.id}")
    assert run.calls == ["choose_recipient", "build_evidence_pdf", "draft_complaint"]
    c = case_service.get(c.id)
    assert (case_service.case_dir(c.id) / "evidence.pdf").stat().st_size > 1500
    assert len(c.evidence_sha256) == 64
    assert c.state == "complaint_ready" and c.approval.kind == "customer_reply" and c.sent == {}
    d = c.drafts["customer_reply"]
    assert d.recipient == "customer" and "Asha Verma" in d.text and "612345678901" in d.text
    assert "Rs 4,250" in d.text and "Rs 600" in d.text and "Rs 4,850" in d.text


async def test_citations_are_numbered_in_reading_order_and_all_used(case_at):
    c = case_at("A", "complaint")
    d = c.drafts["customer_reply"]
    used = []
    for n in re.findall(r"\[(\d+)\]", d.text):
        if int(n) not in used:
            used.append(int(n))
    assert used == list(range(1, len(d.citations) + 1))
    assert any(x.ref == "RBI-TAT-UPI-01" for x in d.citations)


async def test_rejection_reply_is_locked_until_the_internal_ombudsman_reviews(case_at):
    c = case_at("G", "complaint")
    assert c.referral.internal_ombudsman_required
    assert c.drafts["customer_reply"].locked_reason and c.approval.kind == "internal_ombudsman"


async def test_revision_that_changes_a_figure_is_refused(case_at):
    c = case_at("A", "complaint")
    bad = c.drafts["customer_reply"].text.replace("Rs 600", "Rs 60")
    assert evidence.revise_complaint(c.id, bad)["ok"] is False
    good = c.drafts["customer_reply"].text.replace("Thank you for your complaint", "Thank you for writing to us")
    assert evidence.revise_complaint(c.id, good)["ok"] is True
