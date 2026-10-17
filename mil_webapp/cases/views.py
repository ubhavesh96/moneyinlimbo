"""Grievance officer console and auditor views (server-rendered), plus the /api proxy.

Local prototype: there is no real sign-in. A signed cookie holds the demo role, and every call to
the agent service carries who is acting so decisions are attributed in the audit trail.
"""

from __future__ import annotations

from functools import wraps

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from cases import agent_client

_ALLOWED_METHODS = {"GET", "POST", "PUT"}
ROLE_COOKIE, ROLE_SALT = "mil_role", "mil-role"

ROLES = {
    "officer": {"name": "Priya Sharma", "initials": "PS", "title": "Grievance Redressal Officer", "home": "officer-queue",
                "nav": [("officer-queue", "My queue", "inbox"), ("officer-drafts", "Approvals", "pen"),
                        ("officer-new", "New complaint", "plus"), ("officer-insights", "Insights", "chart")]},
    "auditor": {"name": "Ravi Kumar", "initials": "RK", "title": "Internal Auditor (read-only)", "home": "auditor-explorer",
                "nav": [("auditor-explorer", "Audit explorer", "shield"), ("auditor-decisions", "Decision log", "list"),
                        ("auditor-rules", "Rule library", "book"), ("auditor-models", "Model status", "cpu"),
                        ("auditor-exports", "Evidence exports", "download")]},
}


def current_role(request: HttpRequest) -> str:
    role = request.get_signed_cookie(ROLE_COOKIE, default="officer", salt=ROLE_SALT)
    return role if role in ROLES else "officer"


def actor_headers(request: HttpRequest) -> dict[str, str]:
    role = current_role(request)
    return {"x-mil-actor": ROLES[role]["name"], "x-mil-role": role}


def _mode(request) -> dict | None:
    try:
        return agent_client.get_json("mode", actor_headers(request))
    except (agent_client.AgentUnavailable, agent_client.AgentError):
        return None


def _nav_counts(request, role: str, rows: list | None) -> dict:
    """Badges for the officer's navigation (open cases, drafts waiting for approval)."""
    if role != "officer":
        return {}
    try:
        rows = rows if rows is not None else agent_client.get_json("cases", actor_headers(request))
    except (agent_client.AgentUnavailable, agent_client.AgentError):
        return {}
    return {"open": sum(1 for r in rows if r["state"] not in ("resolved", "closed")),
            "review": sum(1 for r in rows if r["needs_approval"])}


def _render(request, template: str, status: int = 200, **context) -> HttpResponse:
    role = current_role(request)
    rows = context.get("rows") if context.get("all_rows") else None
    context.update(role=role, me=ROLES[role], roles=ROLES, mode=_mode(request), nav_counts=_nav_counts(request, role, rows),
                   active=request.resolver_match.url_name if request.resolver_match else "")
    return render(request, template, context, status=status)


def page(role: str):
    """A server-rendered page for one role. Agent-service failures become a friendly page."""

    def deco(view):
        @wraps(view)
        @ensure_csrf_cookie
        def inner(request, *args, **kwargs):
            if current_role(request) != role:
                return redirect(ROLES[current_role(request)]["home"])
            try:
                template, context = view(request, *args, **kwargs)
            except agent_client.AgentUnavailable:
                return _render(request, "offline.html", status=502)
            except agent_client.AgentError as e:
                return _render(request, "error.html", status=e.status, detail=e.detail)
            if isinstance(template, HttpResponse):
                return template
            return _render(request, template, **context)
        return inner
    return deco


def _get(request, path: str, query: str = ""):
    return agent_client.get_json(path, actor_headers(request), query)


def home(request: HttpRequest) -> HttpResponse:
    return redirect(ROLES[current_role(request)]["home"])


@require_POST
def switch_role(request: HttpRequest) -> HttpResponse:
    role = request.POST.get("role", "officer")
    role = role if role in ROLES else "officer"
    resp = redirect(ROLES[role]["home"])
    resp.set_signed_cookie(ROLE_COOKIE, role, salt=ROLE_SALT, httponly=True, samesite="Lax")
    return resp


# ---- officer ---------------------------------------------------------------------------------

@page("officer")
def officer_queue(request):
    rows = _get(request, "cases")
    insights = _get(request, "insights")
    return "officer/queue.html", {"rows": rows, "all_rows": True, "kpis": insights["kpis"], "title": "My queue",
                                  "subtitle": "Sorted by statutory turnaround urgency"}


@page("officer")
def officer_drafts(request):
    rows = [r for r in _get(request, "cases") if r["needs_approval"]]
    return "officer/queue.html", {"rows": rows, "kpis": None, "title": "Drafts awaiting approval",
                                  "subtitle": "Nothing below has been sent. Each item needs your approval."}


STATES = ["intake", "reconstructed", "diagnosed", "rights_computed", "complaint_ready", "awaiting_party",
          "escalated", "resolved", "closed"]


def state_path(case: dict) -> list[tuple[str, str]]:
    """Each state with 'done', 'now' or '' from the audited state moves (the path is not linear)."""
    visited = {"intake"} | {a["inputs"].get("to") for a in case["audit"] if a["tool"] == "advance_state"}
    return [(s, "now" if s == case["state"] else "done" if s in visited else "") for s in STATES]


@page("officer")
def officer_case(request, case_id: str):
    case = _get(request, f"cases/{case_id}")
    return "officer/workbench.html", {"case": case, "statepath": state_path(case), "failure_points": [
        "Beneficiary bank", "NPCI switch", "Gateway", "Acquiring bank", "Remitter bank", "None"]}


@page("officer")
def officer_new(request):
    if request.method == "POST":
        files = [("files", (f.name, f.read(), f.content_type or "application/octet-stream"))
                 for f in request.FILES.getlist("files")]
        form = {k: request.POST.getlist(k) for k in ("sample_id", "customer_ref", "customer_name", "received")
                if request.POST.get(k)}
        r = agent_client.forward("POST", "cases", form=form, files=files, headers=actor_headers(request))
        if r.status < 400:
            return redirect("officer-case", case_id=r.json()["id"]), {}
        samples = _get(request, "samples")
        return "officer/new_case.html", {"samples": samples, "error": r.json().get("detail", "Could not open the case."),
                                         "values": request.POST}
    return "officer/new_case.html", {"samples": _get(request, "samples"), "values": {}}


@page("officer")
def officer_insights(request):
    return "officer/insights.html", {"data": _get(request, "insights")}


# ---- auditor ---------------------------------------------------------------------------------

@page("auditor")
def auditor_explorer(request):
    return "auditor/explorer.html", {"rows": _get(request, "cases")}


@page("auditor")
def auditor_replay(request, case_id: str):
    case = _get(request, f"cases/{case_id}")
    moves = [a for a in case["audit"] if a["tool"] == "advance_state"]
    steps = [a for a in case["audit"] if a["tool"] != "advance_state"]
    return "auditor/replay.html", {"case": case, "moves": moves, "steps": steps}


@page("auditor")
def auditor_decisions(request):
    return "auditor/decisions.html", {"decisions": _get(request, "audit/decisions")}


@page("auditor")
def auditor_rules(request):
    return "auditor/rules.html", {"lib": _get(request, "rules")}


@page("auditor")
def auditor_models(request):
    return "auditor/models.html", {"ev": _get(request, "audit/evals"), "agents": AGENT_CATALOGUE}


@page("auditor")
def auditor_exports(request):
    return "auditor/exports.html", {"rows": _get(request, "cases")}


AGENT_CATALOGUE = [
    ("Orchestrator", "Routes the case to the next agent, keeps case state, blocks any outbound message until approved",
     "get_case, transfer to specialist", "RouteDecision"),
    ("Timeline Reconstructor", "Extracts events from statements, SMS and receipts, pulls bank records and orders them",
     "parse_document, normalize_events", "Timeline"),
    ("Failure Diagnoser", "Proposes the failure point with a confidence and reasons; asks for documents if unsure",
     "lookup_known_outages, predict_failure_point", "FailureDiagnosis"),
    ("Policy and Rights", "Finds the rule, then computes deadline, days overdue and compensation in code",
     "search_policies, compute_deadline, compute_compensation", "RightsCard"),
    ("Evidence and Complaint", "Chooses the recipient, drafts the cited reply and builds the evidence PDF",
     "choose_recipient, draft_complaint, build_evidence_pdf", "ComplaintDraft"),
    ("Case Tracker", "Moves the case between states and watches deadlines and follow-ups",
     "on_event, check_sla, schedule_followup", "CaseUpdate"),
    ("Escalation", "Decides the Internal Ombudsman or RBI route and drafts the grounds",
     "select_ombudsman_route, draft_escalation", "EscalationDraft"),
]


# ---- API proxy -------------------------------------------------------------------------------

def agent_api(request: HttpRequest, path: str) -> HttpResponse:
    """Pass /api/... calls through to the agent service. CSRF is enforced by middleware; the acting
    person comes from the role cookie, and auditors are read-only."""
    if request.method not in _ALLOWED_METHODS:
        return JsonResponse({"detail": "Method not allowed."}, status=405)
    if request.method != "GET" and current_role(request) == "auditor":
        return JsonResponse({"detail": "Auditors cannot change cases."}, status=403)
    extra: dict = {"headers": actor_headers(request)}
    if request.content_type == "multipart/form-data":
        extra["form"] = {k: vals for k, vals in request.POST.lists()}
        extra["files"] = [(k, (f.name, f.read(), f.content_type or "application/octet-stream"))
                          for k, fl in request.FILES.lists() for f in fl]
    else:
        extra["body"] = request.body
        extra["content_type"] = request.headers.get("content-type", "")
    try:
        resp = agent_client.forward(request.method, path, query=request.META.get("QUERY_STRING", ""), **extra)
    except agent_client.AgentUnavailable:
        return JsonResponse(
            {"detail": "The agent service is not switched on. Start mil_adk_agent on port 8001 and try again."},
            status=502,
        )
    out = HttpResponse(resp.content, status=resp.status)
    for k, v in resp.headers.items():
        out[k] = v
    return out
