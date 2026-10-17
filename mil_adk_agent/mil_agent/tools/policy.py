"""Policy and Rights tools: search_policies (stand-in for Vertex AI Search), compute_deadline and
compute_compensation. The model only chooses which to call; every date and rupee comes from
policy_package.rules."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

from google.adk.tools import ToolContext

from mil_agent import settings
from mil_agent.data.synthetic import RAIL_FAILURE
from mil_agent.models import Case, RightsCard
from mil_agent.services import case_service
from mil_agent.tools.common import agent_name, done, fail, load, money
from mil_agent.tools.policy_package import rules
from mil_agent.tools.tracker_package import state_machine

AGENT = "policy_rights"


@lru_cache(maxsize=1)
def policies() -> dict:
    return json.loads((settings.DATA_DIR / "policies.json").read_text(encoding="utf-8"))


def rule_by_id(rule_id: str) -> dict:
    return next(r for r in policies()["rules"] if r["id"] == rule_id)


def rule_for(case: Case) -> dict | None:
    ftype = case.diagnosis.failure_type if case.diagnosis else "unknown"
    if ftype == "credited_successfully":
        ftype = RAIL_FAILURE.get(case.rail, "unknown")  # the rule that would have applied
    return next((r for r in policies()["rules"] if ftype in r["failure_types"]), None)


def search_policies(query: str, tool_context: ToolContext = None) -> dict:
    """Search the rule library (RBI circulars, Ombudsman scheme) and return matching rules with
    their source, link and whether the rule text has been verified.

    Args:
        query: What to look up, e.g. 'UPI transfer debited not credited reversal'.
    """
    words = {w for w in query.lower().replace(",", " ").split() if len(w) > 2}
    scored = []
    for r in policies()["rules"]:
        hay = " ".join(r["keywords"] + [r["title"].lower(), r["text"].lower()])
        score = sum(1 for w in words if w in hay)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    hits = [{"rule_id": r["id"], "title": r["title"], "source": r["source"], "url": r["url"],
             "verified": r["verified"], "text": r["text"]} for _, r in scored[:3]]
    return {"ok": True, "summary": f"Found {len(hits)} matching rule(s).", "results": hits,
            "disclaimer": policies()["disclaimer"]}


def _card(case: Case, rule: dict) -> RightsCard:
    """Exact rights for the case as of its current date."""
    txn = date.fromisoformat(case.txn_date)
    due = rules.deadline(txn, rule["tat_days"])
    as_of = date.fromisoformat(case.today)
    kinds = {e.kind: e for e in case.timeline}
    reversal = kinds.get("reversal")
    credited = case.diagnosis and case.diagnosis.failure_type == "credited_successfully"
    paid = int(sum(e.amount_inr or 0 for e in case.timeline if e.kind == "compensation_paid"))
    stop = date.fromisoformat(reversal.date) if reversal else as_of  # compensation stops at reversal
    per_day = rule["compensation_per_day"]
    owed = 0 if credited else max(0, rules.compensation(due, stop, per_day) - paid)
    late = 0 if credited else rules.days_overdue(due, stop)
    principal = 0.0 if (credited or reversal) else float(case.amount_inr or 0)
    if credited:
        sums = "Not applicable: the beneficiary was credited, so no turnaround time was breached."
    else:
        sums = rules.arithmetic(due, stop, per_day) + (f" - Rs {paid:,} already paid = Rs {owed:,}" if paid else "")
    return RightsCard(
        rule_id=rule["id"], rule_title=rule["title"], rule_source=rule["source"], rule_url=rule.get("url"),
        rule_verified=rule["verified"], tat_days=rule["tat_days"], tat_basis=rule["tat_basis"],
        txn_date=txn.isoformat(), deadline=due.isoformat(), as_of=as_of.isoformat(), days_overdue=late,
        breached=late > 0, compensation_per_day=per_day, compensation_inr=owed, arithmetic=sums,
        reversal_done=bool(reversal), compensation_paid_inr=paid, principal_to_credit_inr=principal,
        total_to_credit_inr=principal + owed)


def compute_deadline(case_id: str, tool_context: ToolContext = None) -> dict:
    """Find the applicable turnaround rule and compute the reversal deadline (T + turnaround days)
    and how many days it has been breached by, as of the case date.

    Args:
        case_id: The case. Needs a diagnosis.
    """
    case = load(case_id)
    if not case.diagnosis or case.diagnosis.failure_type == "unknown":
        return fail("Cannot compute a deadline until the failure has been diagnosed.")
    if case.diagnosis.missing_documents:
        return fail(f"The diagnosis is not confirmed yet: waiting for {case.diagnosis.missing_documents[0].lower()}.")
    if not case.txn_date:
        return fail("The transaction date is unknown.")
    rule = rule_for(case)
    if rule is None:
        return fail(f"No turnaround rule covers {case.diagnosis.failure_type}.")
    card = _card(case, rule)
    case.rights = card
    status = (f"breached by {card.days_overdue} day(s)" if card.breached
              else "not breached" if case.diagnosis.failure_type == "credited_successfully"
              else f"due {card.deadline}")
    return done(case, agent_name(tool_context, AGENT), "compute_deadline",
                f"{rule['id']}: T={card.txn_date}, T+{card.tat_days} = {card.deadline}; {status}"
                + ("" if rule["verified"] else " (rule pending verification)") + ".",
                rule_id=rule["id"], deadline=card.deadline, days_overdue=card.days_overdue,
                breached=card.breached, rule_verified=rule["verified"])


def compute_compensation(case_id: str, tool_context: ToolContext = None) -> dict:
    """Compute the compensation owed (Rs per day beyond the deadline, less anything already paid)
    and the total to credit. Exact arithmetic from code.

    Args:
        case_id: The case. Call compute_deadline first.

    Returns:
        The typed RightsCard.
    """
    case = load(case_id)
    if not case.rights:
        return fail("Compute the deadline first.")
    card = _card(case, rule_by_id(case.rights.rule_id))
    case.rights = card
    case.rights_ready_at = case.rights_ready_at or case_service.now_iso()
    case_service.save(case)
    state_machine.advance(case, "rights_computed", f"compensation Rs {card.compensation_inr}")
    return done(case, agent_name(tool_context, AGENT), "compute_compensation",
                f"Compensation {card.arithmetic}. Total to credit {money(card.total_to_credit_inr)}.",
                output=card)


def refresh_rights(case: Case) -> None:
    """Re-run the maths for the case's current date (compensation grows while the money is stuck)."""
    if case.rights and case.diagnosis:
        case.rights = _card(case, rule_by_id(case.rights.rule_id))


def settings_days() -> tuple[int, int]:
    p = policies()
    return p["rbi_wait_days"], p["rbi_file_within_days"]
