from mil_agent.agents.subagents import escalation_agent
from mil_agent.services import case_service
from tests.unit.helpers import run_agent


async def test_upheld_complaint_needs_no_referral(case_at):
    c = case_at("A", "rights")
    run = await run_agent(escalation_agent, f"case_id={c.id}")
    assert run.calls == ["select_ombudsman_route"]
    c = case_service.get(c.id)
    assert c.referral.proposed_outcome == "uphold" and not c.referral.internal_ombudsman_required
    assert "internal_ombudsman" not in c.drafts


async def test_proposed_rejection_drafts_internal_ombudsman_referral(case_at):
    c = case_at("G", "rights")
    run = await run_agent(escalation_agent, f"case_id={c.id}")
    assert run.calls == ["select_ombudsman_route", "draft_escalation"]
    c = case_service.get(c.id)
    d = c.drafts["internal_ombudsman"]
    assert c.approval.kind == "internal_ombudsman" and c.approval.status == "pending"
    assert d.level == "internal_ombudsman" and d.grounds and "678901234567" in d.text
    assert "internal_ombudsman" not in c.sent  # a draft is not a send


async def test_rbi_response_quotes_the_computed_figures(case_at):
    c = case_at("A", "complaint")
    await run_agent(escalation_agent, f"case_id={c.id} level=rbi_ombudsman")
    c = case_service.get(c.id)
    text = c.drafts["rbi_ombudsman"].text
    assert "RBI Ombudsman" in text and "6 days x Rs 100 = Rs 600" in text
    assert c.approval.kind == "rbi_ombudsman"
