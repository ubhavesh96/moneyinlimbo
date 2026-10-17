"""Case endpoints. The Django web app calls these; they drive the ADK orchestrator.

Every officer action is recorded as a Decision (who, role, when, why) and in the audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from mil_agent import settings
from mil_agent.agents import fallback_llm
from mil_agent.api.dependencies import (
    actor,
    case_view,
    get_case,
    read_uploads,
    require_idle,
    row_view,
    spawn,
)
from mil_agent.data import samples
from mil_agent.models import FailurePoint, Override, TimelineEvent
from mil_agent.services import case_service, seed_service
from mil_agent.services.session_service import ask, run_action
from mil_agent.tools.tracker_package import simulators, state_machine

router = APIRouter(prefix="/api", tags=["cases"])

PRE_SEND = ("intake", "reconstructed", "diagnosed", "rights_computed", "complaint_ready")


@router.get("/mode")
def mode():
    live = settings.has_api_key()
    degraded = live and fallback_llm.is_degraded()
    return {"live_llm": live and not degraded, "model": settings.LLM_MODEL if live else "offline demo",
            "degraded_reason": fallback_llm.state.reason if degraded else None}


@router.get("/cases")
def list_cases(request: Request, mine: bool = False):
    name, _ = actor(request)
    rows = [row_view(c) for c in case_service.list_cases() if not mine or c.assigned_officer == name]
    urgency = {"Overdue": 0, "Needs your review": 1, "Agent working": 2, "New": 3, "Escalated": 4,
               "Awaiting customer": 5, "Resolved": 6, "Closed": 7}
    rows.sort(key=lambda r: (urgency.get(r["status"], 9), -(r["days_overdue"] or 0), r["deadline"] or "9999"))
    return rows


@router.post("/cases")
async def create_case(request: Request, sample_id: str = Form(""), customer_ref: str = Form(""),
                      customer_name: str = Form(""), received: str = Form(""),
                      files: list[UploadFile] = File(default=[])):
    name, role = actor(request)
    if sample_id:
        try:
            case = seed_service.new_sample_case(sample_id)
        except (StopIteration, KeyError):
            raise HTTPException(404, "Unknown sample")
    else:
        if not files:
            raise HTTPException(400, "Add at least one document: the complaint, a statement or the SMS.")
        if received:
            try:
                datetime.strptime(received, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(400, "Received date must be YYYY-MM-DD.")
        docs = await read_uploads(files, start=1)
        case = seed_service.new_case("Failed payment complaint", docs, customer_ref or "CUST-NEW",
                                     customer_name, received=received or None, officer=name)
    spawn(run_action(case.id, "analyze"))
    case.running = True  # so the first poll already shows progress
    return case_view(case)


@router.get("/cases/{case_id}")
def read_case(case_id: str):
    return case_view(get_case(case_id))


@router.post("/cases/{case_id}/investigate")
async def investigate(case_id: str):
    case = get_case(case_id)
    require_idle(case)
    if case.state not in PRE_SEND:
        raise HTTPException(400, "This case has already been sent; it is tracked, not re-investigated.")
    spawn(run_action(case.id, "analyze"))
    case.running = True
    return case_view(case)


async def _add_docs_and_rerun(request: Request, case_id: str, new_docs) -> dict:
    case = get_case(case_id)
    require_idle(case)
    if case.state not in PRE_SEND:
        raise HTTPException(400, "Documents can only be added before the reply is sent.")
    name, role = actor(request)
    case.documents.extend(new_docs)
    case.awaiting_documents = []
    case.diagnosis = case.rights = case.referral = case.approval = None
    case.drafts = {}
    case.evidence_sha256 = None
    case.timeline = []
    if case.state != "intake":
        state_machine.advance(case, "intake", f"{len(new_docs)} new document(s) added")
    case_service.decide(case, name, role, "reinvestigated", reason=", ".join(d.name for d in new_docs))
    spawn(run_action(case.id, "analyze"))
    case.running = True
    return case_view(case)


@router.post("/cases/{case_id}/documents")
async def add_documents(request: Request, case_id: str, files: list[UploadFile] = File(...)):
    case = get_case(case_id)
    docs = await read_uploads(files, start=len(case.documents) + 1)
    return await _add_docs_and_rerun(request, case_id, docs)


@router.post("/cases/{case_id}/documents/practice")
async def add_requested_sample(request: Request, case_id: str):
    """Practice control: the customer sends the document the agent asked for (sample cases only)."""
    case = get_case(case_id)
    sid = next((m["id"] for m in samples.SAMPLE_CASES if m["customer_ref"] == case.customer_ref), None)
    if sid not in samples.REQUESTABLE:
        raise HTTPException(400, "No practice document is available for this case. Upload one instead.")
    files = samples.requested_file(sid)
    docs = seed_service.documents_from_files(files, start=len(case.documents) + 1)
    return await _add_docs_and_rerun(request, case_id, docs)


class DraftIn(BaseModel):
    kind: str
    text: str = Field(max_length=20_000)


@router.put("/cases/{case_id}/draft")
def edit_draft(request: Request, case_id: str, body: DraftIn):
    case = get_case(case_id)
    require_idle(case)
    d = case.drafts.get(body.kind)
    if not d or body.kind in case.sent:
        raise HTTPException(400, "That draft cannot be edited.")
    if d.locked_reason:
        raise HTTPException(400, f"Locked: {d.locked_reason}.")
    if body.text.strip() != d.text.strip():
        d.text = body.text
        d.edited_by_officer = body.text.strip() != d.original_text.strip()
        ap = case.approval
        if ap and ap.kind == body.kind:
            ap.status, ap.rejection_reason = "pending", None
            ap.checklist.text = False  # the officer must re-confirm the text they changed
        name, role = actor(request)
        case_service.decide(case, name, role, "edited_draft", kind=body.kind,
                            reason=f"{len(body.text)} characters")
    case_service.save(case)
    return case_view(case)


class RestoreIn(BaseModel):
    kind: str


@router.post("/cases/{case_id}/draft/restore")
def restore_draft(request: Request, case_id: str, body: RestoreIn):
    case = get_case(case_id)
    d = case.drafts.get(body.kind)
    if not d or body.kind in case.sent:
        raise HTTPException(400, "That draft cannot be restored.")
    d.text, d.edited_by_officer = d.original_text, False
    if case.approval and case.approval.kind == body.kind:
        case.approval.checklist.text = False
    case_service.save(case)
    return case_view(case)


class ChecklistIn(BaseModel):
    item: str  # timeline | amounts | text
    checked: bool


@router.put("/cases/{case_id}/checklist")
def set_checklist(case_id: str, body: ChecklistIn):
    case = get_case(case_id)
    ap = case.approval
    if not ap or ap.status not in ("pending", "rejected"):
        raise HTTPException(400, "Nothing is waiting for approval.")
    if body.item not in ("timeline", "amounts", "text"):
        raise HTTPException(400, "Unknown checklist item.")
    setattr(ap.checklist, body.item, body.checked)
    case_service.save(case)
    return case_view(case)


class ApproveIn(BaseModel):
    kind: str


@router.post("/cases/{case_id}/approve")
async def approve(request: Request, case_id: str, body: ApproveIn):
    case = get_case(case_id)
    require_idle(case)
    ap = case.approval
    if not ap or ap.kind != body.kind or ap.status not in ("pending", "rejected"):
        raise HTTPException(400, "That item is not waiting for approval.")
    if ap.status == "rejected":
        raise HTTPException(400, "This draft was rejected. Edit it (or restore the AI draft) before approving.")
    if not ap.checklist.complete:
        raise HTTPException(400, "Confirm all three checks (timeline, amounts, reply text) before approving.")
    name, role = actor(request)
    if role != "officer":
        raise HTTPException(403, "Only a grievance officer can approve.")
    ap.status, ap.approved_by, ap.approved_at = "approved", name, case_service.now_iso()
    case_service.decide(case, name, role, "approved", kind=ap.kind,
                        compensation_inr=case.rights.compensation_inr if case.rights else None)
    spawn(run_action(case.id, "approve", f"kind={ap.kind}"))
    case.running = True
    return case_view(case)


class RejectIn(BaseModel):
    kind: str
    reason: str = Field(min_length=10, max_length=1000)


@router.post("/cases/{case_id}/reject")
def reject(request: Request, case_id: str, body: RejectIn):
    case = get_case(case_id)
    require_idle(case)
    ap = case.approval
    if not ap or ap.kind != body.kind or ap.status != "pending":
        raise HTTPException(400, "That item is not waiting for approval.")
    name, role = actor(request)
    ap.status, ap.rejection_reason = "rejected", body.reason.strip()
    ap.checklist.text = False
    case_service.decide(case, name, role, "rejected_draft", kind=body.kind, reason=body.reason.strip())
    case_service.save(case)
    return case_view(case)


class OverrideIn(BaseModel):
    failure_point: FailurePoint
    reason: str = Field(min_length=10, max_length=1000)


@router.post("/cases/{case_id}/override")
async def override(request: Request, case_id: str, body: OverrideIn):
    case = get_case(case_id)
    require_idle(case)
    if not case.diagnosis or case.state not in PRE_SEND:
        raise HTTPException(400, "The diagnosis can only be overridden before the reply is sent.")
    name, role = actor(request)
    case.diagnosis.override = Override(failure_point=body.failure_point, reason=body.reason.strip(), by=name,
                                       at=case_service.now_iso())
    case_service.decide(case, name, role, "override", kind="failure_point",
                        reason=f"{case.diagnosis.failure_point} -> {body.failure_point}: {body.reason.strip()}")
    if "customer_reply" in case.drafts and not case.drafts["customer_reply"].locked_reason:
        spawn(run_action(case.id, "redraft"))
        case.running = True
    return case_view(case)


class RequestDocIn(BaseModel):
    document: str = Field(min_length=3, max_length=200)
    note: str = Field(default="", max_length=1000)


@router.post("/cases/{case_id}/request-documents")
def request_documents(request: Request, case_id: str, body: RequestDocIn):
    case = get_case(case_id)
    require_idle(case)
    if case.state not in PRE_SEND:
        raise HTTPException(400, "Documents can only be requested before the reply is sent.")
    name, role = actor(request)
    if body.document not in case.awaiting_documents:
        case.awaiting_documents.append(body.document)
    case.timeline.append(TimelineEvent(
        id=f"ev-{len(case.timeline) + 1}", date=case.today, source="Officer", kind="documents_requested",
        text=f"{name} asked the customer for: {body.document}." + (f" Note: {body.note}" if body.note else "")))
    case_service.decide(case, name, role, "requested_documents", reason=body.document)
    case_service.save(case)
    return case_view(case)


class SimIn(BaseModel):
    event: str  # reversal_posted | rbi_complaint | io_decision | days
    days: int = 0


@router.post("/cases/{case_id}/simulate")
async def simulate(case_id: str, body: SimIn):
    """Practice controls: mock payments operations, Internal Ombudsman, RBI portal and the clock."""
    case = get_case(case_id)
    require_idle(case)
    allowed = {
        "reversal_posted": case.state in ("awaiting_party", "escalated") and "customer_reply" in case.sent,
        "rbi_complaint": case.state in ("awaiting_party", "escalated") and "customer_reply" in case.sent,
        "io_decision": "internal_ombudsman" in case.sent and not any(e.kind == "io_decision" for e in case.timeline),
        "days": 0 < body.days <= 90,
    }
    if not allowed.get(body.event):
        raise HTTPException(400, "That practice event does not apply to this case right now.")
    if body.event == "days":
        simulators.advance_clock(case, body.days)
    else:
        getattr(simulators, body.event)(case)
    case.running = True
    case_service.save(case)
    spawn(run_action(case.id, "event"))
    return case_view(case)


@router.post("/cases/{case_id}/close")
def close(request: Request, case_id: str):
    case = get_case(case_id)
    require_idle(case)
    if case.state != "resolved":
        raise HTTPException(400, "Only a resolved case can be closed.")
    name, role = actor(request)
    case_service.decide(case, name, role, "closed", reason="File archived with full audit trail")
    state_machine.advance(case, "closed", f"closed by {name}")
    return case_view(case)


class ChatIn(BaseModel):
    message: str = Field(max_length=500)


@router.post("/cases/{case_id}/chat")
async def chat(request: Request, case_id: str, body: ChatIn):
    case = get_case(case_id)
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Type a question.")
    name, _ = actor(request)
    reply = await ask(case.id, f"[ACTION:chat] case_id={case.id} Question: {msg}")
    case = get_case(case_id)
    case.chat += [{"role": "officer", "who": name, "text": msg,
                   "at": datetime.now(UTC).isoformat(timespec="seconds")},
                  {"role": "agent", "text": reply or "I could not answer that from the case facts."}]
    case_service.save(case)
    return case_view(case)


@router.get("/cases/{case_id}/evidence.pdf")
def evidence_pdf(case_id: str):
    path = case_service.case_dir(get_case(case_id).id) / "evidence.pdf"
    if not path.exists():
        raise HTTPException(404, "The evidence file is not ready yet.")
    return FileResponse(path, media_type="application/pdf", filename=f"evidence_{case_id}.pdf")
