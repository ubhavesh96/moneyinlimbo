"""Failure Diagnoser tools: lookup_known_outages, predict_failure_point."""

from __future__ import annotations

from google.adk.tools import ToolContext

from mil_agent.tools.common import agent_name, done, fail, load
from mil_agent.tools.diagnosis_package import classifier
from mil_agent.tools.tracker_package import state_machine

AGENT = "failure_diagnoser"


def lookup_known_outages(case_id: str, tool_context: ToolContext = None) -> dict:
    """Check declared incidents and scan the transaction store for an outage cluster around this
    transaction (same beneficiary, same failure code, same window, far above baseline).

    Args:
        case_id: The case. Needs a reconstructed timeline.
    """
    case = load(case_id)
    if not case.timeline:
        return fail("Reconstruct the timeline before looking for outages.")
    outage, cluster = classifier.outage_for(case), classifier.cluster_for(case)
    parts = []
    if outage:
        parts.append(f"declared incident: {outage['entity']} ({outage['note']})")
    if cluster:
        parts.append(f"cluster {cluster['cluster_id']}: {cluster['failed']} failures in {cluster['window']}, "
                     f"{cluster['unreversed']} still unreversed")
    msg = ("Found " + "; ".join(parts) + ".") if parts else "No declared incident or outage cluster around this transaction."
    return done(case, agent_name(tool_context, AGENT), "lookup_known_outages", msg,
                outage=outage, cluster={k: v for k, v in cluster.items() if k != "utrs"} if cluster else None)


def predict_failure_point(case_id: str, tool_context: ToolContext = None) -> dict:
    """Propose where the payment failed, with a confidence and cited reasons. If the evidence is too
    thin, list exactly which document would settle it instead of guessing.

    Args:
        case_id: The case. Needs a reconstructed timeline.

    Returns:
        The typed FailureDiagnosis.
    """
    case = load(case_id)
    if not case.timeline:
        return fail("Reconstruct the timeline before diagnosing.")
    diag = classifier.predict(case)
    case.diagnosis = diag
    case.awaiting_documents = list(diag.missing_documents)
    if not diag.missing_documents:
        state_machine.advance(case, "diagnosed", f"{diag.failure_point} ({diag.confidence:.0%})")
    summary = (f"{diag.failure_point}, confidence {diag.confidence:.0%}: {diag.summary}"
               + (f" Needs: {diag.missing_documents[0]}." if diag.missing_documents else ""))
    return done(case, agent_name(tool_context, AGENT), "predict_failure_point", summary, output=diag,
                needs_documents=bool(diag.missing_documents))
