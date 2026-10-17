"""Demo queue and the deterministic investigation pipeline.

`investigate_offline` runs the same tools the agents call, in the order the orchestrator's
RouteDecision gives, without any LLM. It seeds the officer's queue on first start (so the demo
does not spend Gemini quota) and powers the evals. Audit entries it writes are marked via='seed'.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import date

from mil_agent import settings
from mil_agent.data import samples
from mil_agent.models import Approval, Case, Checklist, Document
from mil_agent.services import case_service
from mil_agent.tools import diagnosis, escalation, evidence, policy, timeline, tracker
from mil_agent.tools.timeline_package import parsing

log = logging.getLogger("mil.seed")
OFFICER = "Priya Sharma"

_STEPS = {
    "timeline_reconstructor": [timeline.parse_document, timeline.normalize_events],
    "failure_diagnoser": [diagnosis.lookup_known_outages, diagnosis.predict_failure_point],
    "policy_rights": [policy.compute_deadline, policy.compute_compensation],
    "escalation": [escalation.select_ombudsman_route],
    "evidence_complaint": [evidence.choose_recipient, evidence.build_evidence_pdf, evidence.draft_complaint],
}


def documents_from_files(files: dict[str, str], start: int = 1) -> list[Document]:
    return [Document(id=f"doc-{i}", name=n, text=t, kind=parsing.detect_kind(n, t))  # type: ignore[arg-type]
            for i, (n, t) in enumerate(files.items(), start)]


def next_ref() -> str:
    used = {c.ref for c in case_service.list_cases()}
    n = 24001
    while f"MIL-{n}" in used:
        n += 1
    return f"MIL-{n}"


def new_case(title: str, docs: list[Document], customer_ref: str, customer_name: str = "",
             received: str | None = None, label: dict | None = None, officer: str = OFFICER) -> Case:
    today = date.today().isoformat()
    case = Case(id=uuid.uuid4().hex[:8], ref=next_ref(), trace_id=uuid.uuid4().hex, title=title,
                customer_ref=customer_ref.strip() or "CUST-NEW", customer_name=customer_name.strip(),
                received=received or today, created=today, today=today, documents=docs,
                assigned_officer=officer, label=label or {})
    case_service.save(case)
    case_service.audit(case, "grievance_desk", "open_case",
                       f"Case opened with {len(docs)} customer document(s).",
                       inputs={"customer_ref": case.customer_ref}, outputs={"documents": [d.name for d in docs]})
    return case


def new_sample_case(sample_id: str) -> Case:
    m = samples.meta(sample_id)
    docs = documents_from_files(samples.sample_files(sample_id))
    return new_case(m["title"], docs, m["customer_ref"], m["customer_name"],
                    received=samples.received_date(sample_id), label=m["label"])


def investigate_offline(case_id: str) -> Case:
    """Advance the case with the real tools until it needs the officer (or a document)."""
    with case_service.acting_as("seed"):
        for _ in range(8):
            case = case_service.get(case_id)
            nxt = tracker.route(case).next_agent
            if nxt not in _STEPS:
                break
            for step in _STEPS[nxt]:
                res = step(case_id)
                if not res.get("ok"):
                    log.info("offline pipeline stopped at %s: %s", step.__name__, res.get("error"))
                    return case_service.get(case_id)
                if step is escalation.select_ombudsman_route and res.get("escalation_level"):
                    escalation.draft_escalation(case_id, res["escalation_level"])
    return case_service.get(case_id)


def approve_and_send(case_id: str, officer: str = OFFICER) -> Case:
    case = case_service.get(case_id)
    ap: Approval = case.approval
    ap.checklist = Checklist(timeline=True, amounts=True, text=True)
    ap.status, ap.approved_by, ap.approved_at = "approved", officer, case_service.now_iso()
    case_service.decide(case, officer, "Grievance officer", "approved", kind=ap.kind,
                        compensation_inr=case.rights.compensation_inr if case.rights else None)
    with case_service.acting_as("seed"):
        tracker.on_event(case_id, "approved", ap.kind)
    return case_service.get(case_id)


def seed_demo(force: bool = False) -> list[Case]:
    """Create the demo queue if there are no readable cases (or always, with force)."""
    if not force and case_service.list_cases():
        return []
    made = []
    for m in samples.SAMPLE_CASES:
        case = new_sample_case(m["id"])
        if m["seed"] in ("analyzed", "sent"):
            case = investigate_offline(case.id)
        if m["seed"] == "sent" and case.approval:
            case = approve_and_send(case.id)
        made.append(case)
    log.info("Seeded %d demo cases.", len(made))
    return made


def reset_demo() -> list[Case]:
    """Delete the current-format cases and seed a fresh queue. Demo use only: folders from an older
    schema are left untouched."""
    ids = [c.id for c in case_service.list_cases()]
    case_service.forget_all()
    for case_id in ids:
        shutil.rmtree(settings.RUNTIME_DIR / case_id, ignore_errors=True)
    return seed_demo(force=True)
