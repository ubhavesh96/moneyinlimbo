"""Shared fixtures: complaints at any stage, built with the real tools (no LLM involved)."""

from __future__ import annotations

import pytest

from mil_agent.services import case_service, seed_service
from mil_agent.tools import diagnosis, escalation, evidence, policy, timeline


@pytest.fixture
def new_case():
    """new_case('A') -> a fresh complaint with the sample documents loaded, nothing investigated yet."""
    return seed_service.new_sample_case


def _route(case_id):
    res = escalation.select_ombudsman_route(case_id)
    if res.get("escalation_level"):
        escalation.draft_escalation(case_id, res["escalation_level"])


STAGES = {
    "timeline": [timeline.parse_document, timeline.normalize_events],
    "diagnosis": [diagnosis.lookup_known_outages, diagnosis.predict_failure_point],
    "rights": [policy.compute_deadline, policy.compute_compensation],
    "route": [_route],
    "complaint": [evidence.choose_recipient, evidence.build_evidence_pdf, evidence.draft_complaint],
}


@pytest.fixture
def case_at(new_case):
    """case_at('A', 'rights') -> a complaint advanced through the real tools up to that stage."""

    def make(sample_id: str, stage: str):
        c = new_case(sample_id)
        for name, steps in STAGES.items():
            for step in steps:
                step(c.id)
            if name == stage:
                break
        return case_service.get(c.id)

    return make


@pytest.fixture
def approved(case_at):
    """approved('A') -> a complaint whose pending item the officer has approved (not yet sent)."""

    def make(sample_id: str):
        c = case_at(sample_id, "complaint")
        c.approval.checklist.timeline = c.approval.checklist.amounts = c.approval.checklist.text = True
        c.approval.status, c.approval.approved_by = "approved", "Test Officer"
        case_service.decide(c, "Test Officer", "officer", "approved", kind=c.approval.kind)
        return c

    return make
