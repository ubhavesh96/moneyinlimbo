from mil_agent.agents.subagents import timeline_reconstructor
from mil_agent.services import case_service
from tests.unit.helpers import run_agent


async def test_builds_timeline_from_documents_and_bank_records(new_case):
    c = new_case("A")
    run = await run_agent(timeline_reconstructor, f"case_id={c.id}")
    assert run.calls == ["parse_document", "normalize_events"]
    c = case_service.get(c.id)
    assert c.state == "reconstructed" and c.utr == "612345678901" and c.amount_inr == 4250 and c.rail == "UPI"
    assert {d.origin for d in c.documents} == {"customer", "bank_connector"}
    assert {"NPCI switch", "Remitter CBS", "Beneficiary CBS", "Bank statement", "SMS"} <= {e.source for e in c.timeline}
    assert [(e.date, e.time or "") for e in c.timeline] == sorted((e.date, e.time or "") for e in c.timeline)
    assert all(e.doc_id for e in c.timeline)  # every event points at its source document


async def test_unrelated_statement_rows_are_left_out(new_case):
    c = new_case("A")
    await run_agent(timeline_reconstructor, f"case_id={c.id}")
    text = " ".join(e.text for e in case_service.get(c.id).timeline)
    assert "SALARY" not in text and "GROCER" not in text


async def test_state_moves_are_audited_under_the_case_tracker(new_case):
    c = new_case("A")
    await run_agent(timeline_reconstructor, f"case_id={c.id}")
    moves = [a for a in case_service.get(c.id).audit if a.tool == "advance_state"]
    assert [(m.agent, m.inputs["to"]) for m in moves] == [("case_tracker", "reconstructed")]
