"""The case state machine from the project file (p.17). Owned by the Case Tracker.

Every case is in exactly one state. Specialists report what they finished; the Case Tracker's
`advance` is the only code that changes `case.state`, and each move is written to the audit trail
under the case_tracker's name.

    intake -> reconstructed -> diagnosed -> rights_computed -> complaint_ready -> awaiting_party
    complaint_ready -> escalated      (referral to the Internal Ombudsman sent)
    awaiting_party  -> escalated      (deadline missed, or the customer went to the RBI Ombudsman)
    escalated       -> awaiting_party (the reviewed reply or response has been sent)
    awaiting_party / escalated -> resolved -> closed
    any pre-send state -> intake      (new documents: investigate again)
"""

from __future__ import annotations

from mil_agent.models import Case
from mil_agent.services import case_service

ORDER = ["intake", "reconstructed", "diagnosed", "rights_computed", "complaint_ready",
         "awaiting_party", "escalated", "resolved", "closed"]

TRANSITIONS: dict[str, set[str]] = {
    "intake": {"reconstructed"},
    "reconstructed": {"diagnosed", "intake"},
    "diagnosed": {"rights_computed", "intake"},
    "rights_computed": {"complaint_ready", "intake"},
    "complaint_ready": {"awaiting_party", "escalated", "intake"},
    "awaiting_party": {"escalated", "resolved"},
    "escalated": {"awaiting_party", "resolved"},
    "resolved": {"closed"},
    "closed": set(),
}

ENTERED_WHEN = {
    "intake": "Officer opened the case and uploaded documents",
    "reconstructed": "Timeline built from documents and bank records",
    "diagnosed": "Failure point proposed with confidence",
    "rights_computed": "Deadline, days overdue and compensation computed",
    "complaint_ready": "Reply and evidence file drafted, awaiting approval",
    "awaiting_party": "Approved and sent; clock running",
    "escalated": "Deadline missed or referral required",
    "resolved": "Money returned or complaint settled",
    "closed": "File archived with full audit trail",
}


class IllegalTransition(ValueError):
    pass


def can_move(case: Case, to: str) -> bool:
    return to == case.state or to in TRANSITIONS[case.state]


def advance(case: Case, to: str, reason: str) -> bool:
    """Move the case to `to`. Returns False if it is already there; raises on an illegal move."""
    if to == case.state:
        return False
    if to not in TRANSITIONS[case.state]:
        raise IllegalTransition(f"Cannot move a case from {case.state} to {to}.")
    prev = case.state
    case.state = to  # type: ignore[assignment]
    case_service.audit(case, "case_tracker", "advance_state", f"{prev} -> {to}: {reason}",
                       inputs={"from": prev, "to": to}, outputs={"reason": reason})
    return True


def at_least(case: Case, state: str) -> bool:
    return ORDER.index(case.state) >= ORDER.index(state)
