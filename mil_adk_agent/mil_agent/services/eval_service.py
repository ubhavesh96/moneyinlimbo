"""Live evaluation of the prototype targets in the project file (p.17 and p.24).

Everything here is computed from the code and the current cases when asked, not hard-coded:
1. Failure-point diagnosis vs label on synthetic complaints (target >= 80%).
2. Deadline and compensation maths vs hand-worked answers (target 100%).
3. Outputs that validate against the typed contract (target 100%).
4. Messages sent without an approval decision (target 0).
5. Outage-cluster detection precision and recall on the seeded cluster.
6. Time from upload to rights card, and the officer edit rate (measured, no target).

Caveat shown in the UI: the synthetic data and the classifier come from the same team, so these
numbers prove the plumbing, not real-world accuracy.
"""

from __future__ import annotations

import statistics
import time
from datetime import date, datetime

from pydantic import ValidationError

from mil_agent.data import samples, synthetic
from mil_agent.models import (
    Case,
    CaseUpdate,
    ComplaintDraft,
    EscalationDraft,
    FailureDiagnosis,
    ReferralCheck,
    RightsCard,
    Timeline,
)
from mil_agent.services import case_service
from mil_agent.tools import timeline as timeline_tools
from mil_agent.tools.diagnosis_package import classifier
from mil_agent.tools.policy_package import rules
from mil_agent.tools.timeline_package.bank_connector import MockBankConnector

TYPED = {"normalize_events": Timeline, "predict_failure_point": FailureDiagnosis, "compute_compensation": RightsCard,
         "select_ombudsman_route": ReferralCheck, "draft_complaint": ComplaintDraft,
         "draft_escalation": EscalationDraft, "on_event": CaseUpdate, "check_sla": CaseUpdate}

# Hand-worked answers: (T, tat_days, as_of, expected deadline, days overdue, Rs at 100/day)
MATHS_CASES = [
    ("2026-10-02", 1, "2026-10-09", "2026-10-03", 6, 600),   # project file Case A: T+1 breached by 6 days
    ("2026-10-01", 5, "2026-10-09", "2026-10-06", 3, 300),   # T+5 card at PoS
    ("2026-10-08", 1, "2026-10-09", "2026-10-09", 0, 0),     # deadline is today: not yet late
    ("2026-10-07", 5, "2026-10-09", "2026-10-12", 0, 0),     # inside T+5
    ("2026-09-28", 1, "2026-10-01", "2026-09-29", 2, 200),   # crosses a month end
    ("2026-02-27", 1, "2026-03-02", "2026-02-28", 2, 200),   # crosses February
    ("2026-10-03", 5, "2026-10-31", "2026-10-08", 23, 2300), # long breach
]

_cache: dict = {"at": 0.0, "result": None}


def _eval_case(files: dict[str, str], withhold: bool, label: dict) -> Case:
    today = date.today().isoformat()
    docs = [d for d in _documents(files)]
    c = Case(id="eval", ref="EVAL", trace_id="e" * 32, title="eval", customer_ref="EVAL", received=today,
             created=today, today=today, documents=docs, label=label)
    c.utr = timeline_tools.disputed_utr(c.documents)
    timeline_tools.attach_bank_records(c, MockBankConnector(withhold_switch_log=withhold))
    timeline_tools.apply_timeline(c)
    c.diagnosis = classifier.predict(c)
    return c


def _documents(files):
    from mil_agent.services.seed_service import documents_from_files

    return documents_from_files(files)


def diagnosis_accuracy() -> dict:
    rows = []
    for item in samples.eval_set():
        c = _eval_case(item["files"], item["withhold_switch_log"], item["label"])
        rows.append((c, item["label"]))
    for m in samples.SAMPLE_CASES:
        c = _eval_case(samples.sample_files(m["id"], include_requested=True), False, m["label"])
        rows.append((c, m["label"]))
    answered = [(c, lab) for c, lab in rows if not c.diagnosis.missing_documents]
    correct = sum(1 for c, lab in answered if c.diagnosis.failure_point == lab["failure_point"])
    correct_all = sum(1 for c, lab in rows if c.diagnosis.failure_point == lab["failure_point"])
    misses = [{"utr": c.utr, "expected": lab["failure_point"], "got": c.diagnosis.failure_point,
               "confidence": c.diagnosis.confidence} for c, lab in rows
              if c.diagnosis.failure_point != lab["failure_point"]][:8]
    return {"cases": len(rows), "answered": len(answered), "abstained": len(rows) - len(answered),
            "accuracy_answered": round(correct / max(1, len(answered)), 3),
            "accuracy_all": round(correct_all / max(1, len(rows)), 3), "target": 0.8, "misses": misses}


def maths_exactness() -> dict:
    ok = 0
    for t, tat, as_of, due, late, rs in MATHS_CASES:
        d = rules.deadline(date.fromisoformat(t), tat)
        today = date.fromisoformat(as_of)
        if (d.isoformat(), rules.days_overdue(d, today), rules.compensation(d, today, 100)) == (due, late, rs):
            ok += 1
    return {"cases": len(MATHS_CASES), "exact": ok, "rate": ok / len(MATHS_CASES), "target": 1.0}


def contract_validity(cases: list[Case]) -> dict:
    total = valid = 0
    failures = []
    for c in cases:
        for a in c.audit:
            if a.tool not in TYPED or not a.outputs or a.outputs.get("ok") is False:
                continue
            total += 1
            verdict = str(a.outputs.get("_contract", "missing"))
            if verdict.endswith(": valid") and verdict.startswith(TYPED[a.tool].__name__):
                valid += 1
            else:
                failures.append({"case": c.ref, "tool": a.tool, "result": verdict})
    # The stored case file itself must also load under the contract.
    for c in cases:
        total += 1
        try:
            Case.model_validate(c.model_dump())
            valid += 1
        except ValidationError as e:
            failures.append({"case": c.ref, "tool": "case file", "result": str(e).splitlines()[0]})
    return {"outputs": total, "valid": valid, "rate": round(valid / max(1, total), 3), "target": 1.0,
            "failures": failures[:5]}


def sent_without_approval(cases: list[Case]) -> dict:
    violations = []
    for c in cases:
        for kind, info in c.sent.items():
            ok = any(d.action == "approved" and d.kind == kind for d in c.decisions)
            if not ok:
                violations.append({"case": c.ref, "kind": kind, "reference": info.get("reference")})
    return {"sent": sum(len(c.sent) for c in cases), "without_approval": len(violations), "target": 0,
            "violations": violations}


def cluster_detection() -> dict:
    rows = synthetic.store()
    failed = [x for x in rows if x.failed]
    predicted = {x.utr for x in failed if synthetic.detect_cluster(x)}
    truth = {x.utr for x in failed if x.cluster}
    tp = len(predicted & truth)
    return {"failed_transactions": len(failed), "seeded_cluster_size": len(truth), "flagged": len(predicted),
            "precision": round(tp / max(1, len(predicted)), 3), "recall": round(tp / max(1, len(truth)), 3)}


def _secs(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()


def officer_metrics(cases: list[Case]) -> dict:
    live = [c for c in cases if c.analysis_started_at and c.rights_ready_at
            and c.rights_ready_at >= c.analysis_started_at]
    durations = [_secs(c.analysis_started_at, c.rights_ready_at) for c in live]
    approved_replies = [c.drafts["customer_reply"] for c in cases
                        if "customer_reply" in c.sent and "customer_reply" in c.drafts]
    edited = sum(1 for d in approved_replies if d.edited_by_officer)
    return {"upload_to_rights_seconds_median": round(statistics.median(durations), 1) if durations else None,
            "upload_to_rights_runs": len(durations), "target_seconds": 120,
            "replies_sent": len(approved_replies), "edited": edited,
            "edit_rate": round(edited / len(approved_replies), 3) if approved_replies else None}


def run(max_age_seconds: float = 30) -> dict:
    if _cache["result"] and time.time() - _cache["at"] < max_age_seconds:
        return _cache["result"]
    cases = case_service.list_cases()
    result = {
        "computed_at": case_service.now_iso(),
        "caveat": "Synthetic data and classifier come from the same team: these numbers prove the pipeline, "
                  "not real-world accuracy. Practitioner review (layer 4) has not happened yet.",
        "diagnosis": diagnosis_accuracy(),
        "maths": maths_exactness(),
        "contract": contract_validity(cases),
        "approval": sent_without_approval(cases),
        "clusters": cluster_detection(),
        "officer": officer_metrics(cases),
        "layers": [
            {"n": 1, "name": "Contract tests (pytest)", "status": "Run in CI",
             "detail": "Typed outputs, deadline and compensation maths, approval guard. Run: python -m pytest -q"},
            {"n": 2, "name": "ADK evalsets", "status": "Not run",
             "detail": "Trajectory and response-match evals need a Gemini key and quota."},
            {"n": 3, "name": "Rubric and hallucination checks", "status": "Planned",
             "detail": "Vertex Gen AI Evaluation Service on drafted replies."},
            {"n": 4, "name": "Officer review", "status": "Planned",
             "detail": "Hero cases reviewed by 3 to 5 practitioners; edits and time counted."},
            {"n": 5, "name": "Outage detection", "status": "Measured live",
             "detail": "Precision and recall on the seeded cluster in ~5,000 synthetic transactions."},
        ],
    }
    _cache.update(at=time.time(), result=result)
    return result
