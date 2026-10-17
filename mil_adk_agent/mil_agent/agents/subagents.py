"""The six specialist agent definitions (project file p.15-16)."""

from google.adk.agents import Agent

from mil_agent.agents.config import (
    AGENT_PROMPTS_DIR,
    CASE_TRACKER_PROMPT,
    ESCALATION_PROMPT,
    EVIDENCE_COMPLAINT_PROMPT,
    FAILURE_DIAGNOSER_PROMPT,
    POLICY_RIGHTS_PROMPT,
    TIMELINE_RECONSTRUCTOR_PROMPT,
    agent_config,
    model_for,
)
from mil_agent.callbacks import before_tool_callback_require_approval
from mil_agent.prompts import Prompt
from mil_agent.tools import diagnosis, escalation, evidence, policy, timeline, tracker


def _instruction(template: str) -> str:
    return Prompt(f"{AGENT_PROMPTS_DIR}/{template}").render({})


timeline_reconstructor = Agent(
    name="timeline_reconstructor",
    model=model_for("timeline_reconstructor"),
    description="Extracts events from the customer's documents, pulls the bank's own records for the UTR and "
                "orders them into one cited timeline.",
    instruction=_instruction(TIMELINE_RECONSTRUCTOR_PROMPT),
    tools=[timeline.parse_document, timeline.normalize_events],
    generate_content_config=agent_config,
)

failure_diagnoser = Agent(
    name="failure_diagnoser",
    model=model_for("failure_diagnoser"),
    description="Proposes the failure point with a confidence and cited reasons, checks declared outages and "
                "outage clusters, and asks for a document when unsure.",
    instruction=_instruction(FAILURE_DIAGNOSER_PROMPT),
    tools=[diagnosis.lookup_known_outages, diagnosis.predict_failure_point],
    generate_content_config=agent_config,
)

policy_rights = Agent(
    name="policy_rights",
    model=model_for("policy_rights"),
    description="Finds the applicable RBI rule, then computes the deadline, days overdue and compensation in code.",
    instruction=_instruction(POLICY_RIGHTS_PROMPT),
    tools=[policy.search_policies, policy.compute_deadline, policy.compute_compensation],
    generate_content_config=agent_config,
)

evidence_complaint = Agent(
    name="evidence_complaint",
    model=model_for("evidence_complaint"),
    description="Chooses the recipient, builds the regulator-ready evidence PDF and drafts the cited reply to the "
                "customer. Never sends anything.",
    instruction=_instruction(EVIDENCE_COMPLAINT_PROMPT),
    tools=[evidence.choose_recipient, evidence.build_evidence_pdf, evidence.draft_complaint,
           evidence.revise_complaint],
    generate_content_config=agent_config,
)

case_tracker = Agent(
    name="case_tracker",
    model=model_for("case_tracker"),
    description="Sends only what the officer approved, moves the case between states, and watches deadlines "
                "and follow-ups.",
    instruction=_instruction(CASE_TRACKER_PROMPT),
    tools=[tracker.on_event, tracker.check_sla, tracker.schedule_followup],
    generate_content_config=agent_config,
    before_tool_callback=before_tool_callback_require_approval,
)

escalation_agent = Agent(
    name="escalation",
    model=model_for("escalation"),
    description="Decides whether the case needs an Internal Ombudsman referral or an RBI Ombudsman response, and "
                "drafts it. Never sends anything.",
    instruction=_instruction(ESCALATION_PROMPT),
    tools=[escalation.select_ombudsman_route, escalation.draft_escalation],
    generate_content_config=agent_config,
)

SUB_AGENTS = [
    timeline_reconstructor,
    failure_diagnoser,
    policy_rights,
    evidence_complaint,
    case_tracker,
    escalation_agent,
]
