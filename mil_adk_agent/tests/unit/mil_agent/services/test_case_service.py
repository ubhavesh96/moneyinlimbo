import pytest

from mil_agent.services import case_service, eval_service
from mil_agent.tools.tracker_package import state_machine


def test_roundtrip_through_disk(new_case):
    c = new_case("A")
    case_service.audit(c, "tester", "tool", "hello", inputs={"x": 1}, outputs={"y": "z" * 900})
    case_service._cases.clear()  # force a reload from the JSON file
    again = case_service.get(c.id)
    last = again.audit[-1]
    assert last.summary == "hello" and last.trace_id == c.trace_id and last.inputs == {"x": 1}
    assert len(last.outputs["y"]) < 500  # long outputs are trimmed for the log


def test_unknown_case_raises():
    with pytest.raises(KeyError):
        case_service.get("does-not-exist")


def test_illegal_state_move_is_refused(new_case):
    c = new_case("A")
    with pytest.raises(state_machine.IllegalTransition):
        state_machine.advance(c, "awaiting_party", "skipping the investigation")


def test_decisions_are_logged_and_audited(new_case):
    c = new_case("A")
    case_service.decide(c, "Priya Sharma", "officer", "override", kind="failure_point", reason="checked the log")
    assert c.decisions[-1].actor == "Priya Sharma"
    assert c.audit[-1].via == "officer" and c.audit[-1].tool == "officer.override"


def test_evals_meet_the_prototype_targets(approved):
    approved("A")
    r = eval_service.run(max_age_seconds=0)
    assert r["diagnosis"]["accuracy_answered"] >= 0.8
    assert r["maths"]["rate"] == 1.0
    assert r["contract"]["rate"] == 1.0 and r["contract"]["outputs"] > 0
    assert r["approval"]["without_approval"] == 0
    assert r["clusters"]["precision"] >= 0.9 and r["clusters"]["recall"] >= 0.9
