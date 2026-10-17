from mil_agent.agents.routers import root_agent
from mil_agent.services import case_service
from mil_agent.tools.tracker_package import simulators
from tests.unit.helpers import run_agent

ANALYZE_ORDER = ["timeline_reconstructor", "failure_diagnoser", "policy_rights", "escalation", "evidence_complaint"]


async def test_analyze_delegates_in_order_and_traces_one_id(new_case):
    c = new_case("A")
    run = await run_agent(root_agent, f"[ACTION:analyze] case_id={c.id}")
    assert run.calls == ANALYZE_ORDER
    c = case_service.get(c.id)
    assert c.state == "complaint_ready" and c.approval.kind == "customer_reply"
    assert set(ANALYZE_ORDER) <= {a.agent for a in c.audit}
    assert {a.trace_id for a in c.audit} == {c.trace_id}


async def test_stops_and_asks_when_a_document_is_missing(new_case):
    c = new_case("B")
    run = await run_agent(root_agent, f"[ACTION:analyze] case_id={c.id}")
    assert run.calls == ANALYZE_ORDER[:2]
    assert case_service.get(c.id).state == "reconstructed" and "merchant" in run.final.lower()


async def test_rejection_goes_to_the_internal_ombudsman_first(new_case):
    c = new_case("G")
    await run_agent(root_agent, f"[ACTION:analyze] case_id={c.id}")
    c = case_service.get(c.id)
    assert c.approval.kind == "internal_ombudsman" and c.drafts["customer_reply"].locked_reason


async def test_chat_answers_from_case_facts_only(case_at):
    c = case_at("A", "complaint")
    run = await run_agent(root_agent, f"[ACTION:chat] case_id={c.id} Question: how much compensation is owed?")
    assert run.calls == ["get_case"]
    assert "Rs 600" in run.final and "RBI-TAT-UPI-01" in run.final


async def test_approved_reply_is_sent_by_the_case_tracker(approved):
    c = approved("F")
    run = await run_agent(root_agent, f"[ACTION:approve] case_id={c.id} kind=customer_reply")
    assert run.calls == ["case_tracker"]
    assert "customer_reply" in case_service.get(c.id).sent


async def test_rbi_complaint_event_drafts_the_rbi_response(approved):
    c = approved("A")
    await run_agent(root_agent, f"[ACTION:approve] case_id={c.id} kind=customer_reply")
    c = case_service.get(c.id)
    simulators.rbi_complaint(c)
    run = await run_agent(root_agent, f"[ACTION:event] case_id={c.id}")
    assert run.calls == ["case_tracker", "escalation"]
    c = case_service.get(c.id)
    assert c.state == "escalated" and c.approval.kind == "rbi_ombudsman"
