"""Practice controls: mock payments operations, customer, Internal Ombudsman and RBI portal, plus a
local event bus (stand-in for Pub/Sub) and a movable clock (stand-in for Cloud Scheduler ticks)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta

from mil_agent.models import BusEvent, Case


def publish(case: Case, topic: str, payload: dict | None = None) -> BusEvent:
    ev = BusEvent(id=uuid.uuid4().hex[:8], topic=topic, date=case.today, payload=payload or {})
    case.events.append(ev)
    return ev


def advance_clock(case: Case, days: int) -> BusEvent:
    case.today = (date.fromisoformat(case.today) + timedelta(days=days)).isoformat()
    return publish(case, "clock_tick", {"days": days})


def reversal_posted(case: Case) -> BusEvent:
    return publish(case, "reversal_posted")


def rbi_complaint(case: Case) -> BusEvent:
    return publish(case, "rbi_complaint")


def io_decision(case: Case) -> BusEvent:
    return publish(case, "io_decision", {"outcome": "concur", "reference": acknowledgement(case, "io_decision")})


def acknowledgement(case: Case, kind: str) -> str:
    """Reference numbers the mock systems hand back."""
    h = hashlib.sha256(f"{case.id}:{kind}".encode()).hexdigest()[:6].upper()
    return {"customer_reply": f"RPL-{h}", "internal_ombudsman": f"IO-REF-{h}", "io_decision": f"IO-DEC-{h}",
            "rbi_ombudsman": f"RBI-CMS-{h}"}[kind]
