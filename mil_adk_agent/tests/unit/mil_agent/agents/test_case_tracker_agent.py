from mil_agent.agents.subagents import case_tracker
from mil_agent.services import case_service
from mil_agent.tools.tracker_package import simulators
from tests.unit.helpers import run_agent


async def test_refuses_to_send_without_approval(case_at):
    c = case_at("A", "complaint")
    await run_agent(case_tracker, f"case_id={c.id} submit kind=customer_reply")
    c = case_service.get(c.id)
    assert c.sent == {} and c.approval.status == "pending" and c.state == "complaint_ready"


async def test_sends_after_approval_and_starts_the_clock(approved):
    c = approved("A")
    run = await run_agent(case_tracker, f"case_id={c.id} submit kind=customer_reply")
    assert run.calls == ["on_event", "check_sla"]
    c = case_service.get(c.id)
    assert c.state == "awaiting_party" and c.sent["customer_reply"]["reference"].startswith("RPL-")
    assert c.followups and "escalation_level=none" in run.final


async def test_posting_resolves_the_case_with_compensation(approved):
    c = approved("A")
    await run_agent(case_tracker, f"case_id={c.id} submit kind=customer_reply")
    c = case_service.get(c.id)
    simulators.reversal_posted(c)
    await run_agent(case_tracker, f"case_id={c.id} check")
    c = case_service.get(c.id)
    assert c.state == "resolved"
    assert [e.amount_inr for e in c.timeline if e.kind in ("reversal", "compensation_paid")] == [4250, 600]


async def test_missed_followup_escalates_and_compensation_keeps_growing(approved):
    c = approved("A")
    await run_agent(case_tracker, f"case_id={c.id} submit kind=customer_reply")
    c = case_service.get(c.id)
    simulators.advance_clock(c, 3)
    await run_agent(case_tracker, f"case_id={c.id} check")
    c = case_service.get(c.id)
    assert c.state == "escalated" and c.rights.compensation_inr == 900


async def test_rbi_complaint_asks_for_an_rbi_response(approved):
    c = approved("A")
    await run_agent(case_tracker, f"case_id={c.id} submit kind=customer_reply")
    c = case_service.get(c.id)
    simulators.rbi_complaint(c)
    run = await run_agent(case_tracker, f"case_id={c.id} check")
    assert "escalation_level=rbi_ombudsman" in run.final
