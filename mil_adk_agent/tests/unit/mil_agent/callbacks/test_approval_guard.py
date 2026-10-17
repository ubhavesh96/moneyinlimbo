from types import SimpleNamespace

from mil_agent.callbacks import before_tool_callback_require_approval as guard

ON_EVENT = SimpleNamespace(name="on_event")


def _send(case_id, kind="customer_reply"):
    return {"case_id": case_id, "event": "approved", "kind": kind}


def test_ignores_other_tools_and_non_send_events(case_at):
    c = case_at("A", "complaint")
    assert guard(SimpleNamespace(name="check_sla"), {"case_id": c.id}, None) is None
    assert guard(ON_EVENT, {"case_id": c.id, "event": "bus"}, None) is None


def test_blocks_unapproved_send(case_at):
    c = case_at("A", "complaint")
    res = guard(ON_EVENT, _send(c.id), None)
    assert res["ok"] is False and "not approved" in res["summary"]


def test_blocks_wrong_kind_even_if_something_else_is_approved(approved):
    c = approved("A")
    assert guard(ON_EVENT, _send(c.id, "rbi_ombudsman"), None)["ok"] is False


def test_allows_approved_send(approved):
    c = approved("A")
    assert guard(ON_EVENT, _send(c.id), None) is None


def test_unknown_case_is_blocked():
    assert guard(ON_EVENT, _send("nope"), None)["ok"] is False
