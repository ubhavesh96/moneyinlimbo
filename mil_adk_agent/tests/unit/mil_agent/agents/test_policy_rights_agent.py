from datetime import date

import pytest

from mil_agent.agents.subagents import policy_rights
from mil_agent.services import case_service
from mil_agent.tools.policy_package import rules
from tests.unit.helpers import run_agent


@pytest.mark.parametrize("sample,rule,tat,overdue", [
    ("A", "RBI-TAT-UPI-01", 1, 6),    # project file Case A: T+1 breached by 6 days
    ("D", "RBI-TAT-IMPS-01", 1, 2),
    ("E", "RBI-TAT-POS-01", 5, 0),    # still inside T+5
    ("F", "RBI-TAT-ATM-01", 5, 3),
])
async def test_exact_deadline_and_compensation(case_at, sample, rule, tat, overdue):
    c = case_at(sample, "diagnosis")
    run = await run_agent(policy_rights, f"case_id={c.id}")
    assert run.calls == ["search_policies", "compute_deadline", "compute_compensation"]
    c = case_service.get(c.id)
    r = c.rights
    assert (r.rule_id, r.tat_days, r.days_overdue) == (rule, tat, overdue)
    assert r.deadline == rules.deadline(date.fromisoformat(r.txn_date), tat).isoformat()
    assert r.compensation_inr == overdue * 100
    assert r.total_to_credit_inr == c.amount_inr + r.compensation_inr
    assert c.state == "rights_computed"


async def test_case_a_matches_the_project_file(case_at):
    c = case_at("A", "diagnosis")
    await run_agent(policy_rights, f"case_id={c.id}")
    r = case_service.get(c.id).rights
    assert r.compensation_inr == 600 and r.arithmetic == "6 days x Rs 100 = Rs 600" and r.rule_verified


async def test_unverified_rule_is_flagged(case_at, new_case):
    from mil_agent.data import samples
    from mil_agent.services import seed_service

    c = new_case("B")
    c.documents += seed_service.documents_from_files(samples.requested_file("B"), start=len(c.documents) + 1)
    case_service.save(c)
    seed_service.investigate_offline(c.id)
    r = case_service.get(c.id).rights
    assert r.rule_id == "RBI-TAT-CNP-01" and r.rule_verified is False


async def test_no_rights_without_a_diagnosis(case_at):
    c = case_at("B", "diagnosis")  # waiting for a document
    await run_agent(policy_rights, f"case_id={c.id}")
    assert case_service.get(c.id).rights is None
