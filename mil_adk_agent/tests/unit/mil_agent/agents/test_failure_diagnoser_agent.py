import pytest

from mil_agent.agents.subagents import failure_diagnoser
from mil_agent.services import case_service
from tests.unit.helpers import run_agent


@pytest.mark.parametrize("sample,ftype,point", [
    ("A", "upi_transfer_not_credited", "Beneficiary bank"),
    ("D", "imps_not_credited", "NPCI switch"),
    ("F", "atm_cash_not_dispensed", "Acquiring bank"),
    ("G", "credited_successfully", "None"),
])
async def test_diagnoses_hero_cases(case_at, sample, ftype, point):
    c = case_at(sample, "timeline")
    run = await run_agent(failure_diagnoser, f"case_id={c.id}")
    assert run.calls == ["lookup_known_outages", "predict_failure_point"]
    c = case_service.get(c.id)
    assert (c.diagnosis.failure_type, c.diagnosis.failure_point) == (ftype, point)
    assert c.state == "diagnosed" and c.diagnosis.reasons


async def test_thin_evidence_asks_for_a_document_and_does_not_advance(case_at):
    c = case_at("B", "timeline")
    run = await run_agent(failure_diagnoser, f"case_id={c.id}")
    c = case_service.get(c.id)
    assert c.state == "reconstructed" and c.awaiting_documents
    assert "Needs:" in run.final or "merchant" in run.final.lower()
