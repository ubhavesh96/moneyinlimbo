"""Read-only endpoints for oversight: decision log, evals, rule library, outage clusters, insights
and the evidence export. Plus the demo reset."""

from __future__ import annotations

import hashlib
import io
import json
import statistics
import zipfile
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from mil_agent.api.dependencies import actor, get_case, row_view
from mil_agent.data import synthetic
from mil_agent.services import case_service, eval_service, seed_service
from mil_agent.tools.policy import policies

router = APIRouter(prefix="/api", tags=["oversight"])


@router.get("/audit/decisions")
def decisions():
    out = []
    for c in case_service.list_cases():
        for d in c.decisions:
            out.append({"case_id": c.id, "ref": c.ref, "title": c.title, **d.model_dump()})
    return sorted(out, key=lambda x: x["at"], reverse=True)


@router.get("/audit/evals")
def evals():
    return eval_service.run()


@router.get("/rules")
def rules():
    p = policies()
    return {"disclaimer": p["disclaimer"], "last_reviewed": p["rules_last_reviewed"],
            "rbi_wait_days": p["rbi_wait_days"], "rbi_file_within_days": p["rbi_file_within_days"],
            "rules": p["rules"]}


@router.get("/insights")
def insights():
    cases = case_service.list_cases()
    clusters = []
    for cl in synthetic.all_clusters():
        members = [row_view(c) for c in cases if c.diagnosis and c.diagnosis.cluster_id == cl["cluster_id"]]
        complained = {c.utr for c in cases}
        silent = [u for u in cl["utrs"] if u not in complained]
        clusters.append({**{k: v for k, v in cl.items() if k != "utrs"}, "cases": members,
                         "affected_without_complaint": len(silent)})

    def secs(a: str, b: str) -> float:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()

    approved = [(c, d) for c in cases for d in c.decisions if d.action == "approved" and d.kind == "customer_reply"]
    sent = [c for c in cases if "customer_reply" in c.sent]
    on_time = [c for c in sent if c.rights and c.sent["customer_reply"]["date"] <= c.rights.deadline]
    open_cases = [c for c in cases if c.state not in ("resolved", "closed")]
    breached_open = [c for c in open_cases if c.rights and c.rights.breached]
    reply_ages = [(date.fromisoformat(c.sent["customer_reply"]["date"]) - date.fromisoformat(c.received)).days
                  for c in sent]
    edited = [c for c in sent if c.drafts.get("customer_reply") and c.drafts["customer_reply"].edited_by_officer]
    return {
        "kpis": {
            "open_cases": len(open_cases),
            "awaiting_approval": sum(1 for c in cases if c.approval and c.approval.status in ("pending", "rejected")),
            "breached_open": len(breached_open),
            "compensation_owed_inr": sum(c.rights.compensation_inr for c in open_cases if c.rights),
            "referrals_flagged": sum(1 for c in cases if c.referral and c.referral.internal_ombudsman_required),
            "replies_sent": len(sent),
            "replies_within_tat": len(on_time),
            "median_days_to_reply": statistics.median(reply_ages) if reply_ages else None,
            "edit_rate": round(len(edited) / len(sent), 3) if sent else None,
            "approvals_logged": len(approved),
        },
        "clusters": clusters,
        "store": synthetic.stats(),
    }


@router.get("/cases/{case_id}/export.zip")
def export(case_id: str, request: Request):
    """Evidence export: PDF, case file, audit trail, decisions and source documents, with a SHA-256
    manifest so a reviewer can check nothing was altered after export."""
    case = get_case(case_id)
    name, role = actor(request)
    files: dict[str, bytes] = {
        "case.json": case.model_dump_json(indent=2, exclude={"events"}).encode(),
        "audit_trail.json": json.dumps([a.model_dump() for a in case.audit], indent=2).encode(),
        "decisions.json": json.dumps([d.model_dump() for d in case.decisions], indent=2).encode(),
    }
    pdf = case_service.case_dir(case.id) / "evidence.pdf"
    if pdf.exists():
        files["evidence.pdf"] = pdf.read_bytes()
    for d in case.documents:
        files[f"documents/{d.id}_{d.name}"] = d.text.encode()
    manifest = {"case": case.ref, "trace_id": case.trace_id, "exported_by": f"{name} ({role})",
                "exported_at": case_service.now_iso(), "synthetic": True,
                "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
    with case_service.acting_as("officer"):
        case_service.audit(case, name, "export_evidence", f"Evidence pack exported by {name} ({role}).")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={case.ref}_evidence.zip"})


@router.post("/demo/reset")
def demo_reset(request: Request):
    _, role = actor(request)
    if role != "officer":
        raise HTTPException(403, "Only the demo officer can reset the demo.")
    made = seed_service.reset_demo()
    return {"ok": True, "cases": len(made)}
