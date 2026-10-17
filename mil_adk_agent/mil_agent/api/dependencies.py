"""Shared helpers for API routers: who is acting, case lookup, and the views the web app renders."""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi import HTTPException, Request, UploadFile

from mil_agent.models import Case, Document
from mil_agent.services import case_service
from mil_agent.tools.timeline_package import parsing
from mil_agent.tools.tracker import route
from mil_agent.tools.tracker_package.state_machine import ENTERED_WHEN

_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    """Run an agent job in the background and keep a reference so it is not garbage collected."""
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def actor(request: Request) -> tuple[str, str]:
    """The signed-in person, as asserted by the web app (local prototype: no real auth)."""
    name = request.headers.get("x-mil-actor") or "Priya Sharma"
    role = request.headers.get("x-mil-role") or "officer"
    return name[:60], role[:20]


def get_case(case_id: str) -> Case:
    try:
        return case_service.get(case_id)
    except KeyError:
        raise HTTPException(404, "Case not found")


def require_idle(case: Case) -> None:
    if case.running:
        raise HTTPException(409, "The agent is still working on this case. Try again in a moment.")


def display_status(case: Case) -> str:
    """The status chip in the officer's queue (UI vocabulary from the design)."""
    if case.running:
        return "Agent working"
    s = case.state
    if s == "intake":
        return "New"
    if s == "reconstructed" and case.awaiting_documents:
        return "Awaiting customer"
    if s in ("reconstructed", "diagnosed", "rights_computed"):
        return "Needs your review"
    if s == "complaint_ready":
        return "Overdue" if case.rights and case.rights.breached else "Needs your review"
    return {"awaiting_party": "Awaiting customer", "escalated": "Escalated", "resolved": "Resolved",
            "closed": "Closed"}[s]


def deadline_info(case: Case) -> dict:
    r = case.rights
    if not r:
        return {"deadline": None, "relative": "Not computed yet", "breached": False}
    today = date.fromisoformat(case.today)
    due = date.fromisoformat(r.deadline)
    if case.diagnosis and case.diagnosis.failure_type == "credited_successfully":
        rel = "No breach: payment completed"
    elif r.reversal_done:
        rel = f"Reversed{', ' + str(r.days_overdue) + ' day(s) late' if r.days_overdue else ' on time'}"
    elif r.breached:
        rel = f"Breached {r.days_overdue} day{'s' if r.days_overdue != 1 else ''} ago"
    else:
        left = (due - today).days
        rel = "Due today" if left == 0 else f"Due in {left} day{'s' if left != 1 else ''}"
    return {"deadline": r.deadline, "relative": rel, "breached": r.breached}


def row_view(case: Case) -> dict:
    d, r = case.diagnosis, case.rights
    return {
        "id": case.id, "ref": case.ref, "title": case.title, "rail": case.rail, "amount_inr": case.amount_inr,
        "utr": case.utr, "customer_ref": case.customer_ref, "customer_name": case.customer_name,
        "received": case.received, "state": case.state, "status": display_status(case), "step": case.step,
        "failure_point": d.effective_point if d else None, "confidence": d.confidence if d else None,
        "cluster_id": d.cluster_id if d else None, "compensation_inr": r.compensation_inr if r else None,
        "days_overdue": r.days_overdue if r else None, **deadline_info(case),
        "referral_required": bool(case.referral and case.referral.internal_ombudsman_required),
        "needs_approval": bool(case.approval and case.approval.status in ("pending", "rejected")),
        "assigned_officer": case.assigned_officer, "error": case.error, "has_evidence": bool(case.evidence_sha256),
    }


def case_view(case: Case) -> dict:
    d = case.model_dump(exclude={"events", "label"})
    d.update(row_view(case))
    d["documents"] = [x.model_dump() for x in case.documents]
    d["has_evidence"] = bool(case.evidence_sha256)
    d["route"] = route(case).model_dump()
    d["state_help"] = ENTERED_WHEN[case.state]
    if case.diagnosis:
        d["diagnosis"]["effective_point"] = case.diagnosis.effective_point
    return d


async def read_uploads(files: list[UploadFile], start: int) -> list[Document]:
    docs = []
    for i, f in enumerate(files):
        data = await f.read()
        if len(data) > 2_000_000:
            raise HTTPException(413, f"{f.filename} is larger than 2 MB.")
        name = f.filename or "file.txt"
        try:
            text = parsing.extract_text(name, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        docs.append(Document(id=f"doc-{start + i}", name=name, text=text,
                             kind=parsing.detect_kind(name, text)))  # type: ignore[arg-type]
    return docs
