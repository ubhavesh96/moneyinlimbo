"""Typed case file shared by every agent.

The case is investigated by the regulated entity's grievance team. The customer never talks to the
agent; the grievance officer reviews and approves everything that leaves the entity.

Each specialist returns one of the typed outputs from the project file (Timeline, FailureDiagnosis,
RightsCard, ComplaintDraft, CaseUpdate, EscalationDraft, RouteDecision). They forbid extra fields,
so a malformed tool result fails loudly instead of reaching an officer.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

Rail = Literal["UPI", "UPI_MERCHANT", "IMPS", "CARD_TO_CARD", "CARD_POS", "CARD_ONLINE", "ATM", "UNKNOWN"]
FailureType = Literal[
    "upi_transfer_not_credited",
    "upi_merchant_not_confirmed",
    "imps_not_credited",
    "card_to_card_not_credited",
    "card_pos_not_confirmed",
    "card_online_not_confirmed",
    "atm_cash_not_dispensed",
    "credited_successfully",
    "unknown",
]
FailurePoint = Literal[
    "Remitter bank", "NPCI switch", "Beneficiary bank", "Gateway", "Acquiring bank", "None", "Unknown",
]
CaseState = Literal[
    "intake", "reconstructed", "diagnosed", "rights_computed",
    "complaint_ready", "awaiting_party", "escalated", "resolved", "closed",
]
DraftKind = Literal["customer_reply", "internal_ombudsman", "rbi_ombudsman"]
EscalationLevel = Literal["internal_ombudsman", "rbi_ombudsman"]
EventSource = Literal[
    "Complaint", "Bank statement", "SMS", "Merchant", "NPCI switch", "Remitter CBS", "Beneficiary CBS",
    "Gateway log", "ATM switch", "Officer", "System",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Document(_Strict):
    id: str
    name: str
    kind: Literal["complaint", "statement", "sms", "merchant", "bank_log", "other"] = "other"
    origin: Literal["customer", "bank_connector"] = "customer"
    text: str


class TimelineEvent(_Strict):
    id: str
    date: str  # ISO yyyy-mm-dd
    time: str | None = None  # HH:MM when the source has it
    source: EventSource
    kind: str
    text: str
    amount_inr: float | None = None
    ref: str | None = None
    doc_id: str | None = None
    snippet: str | None = None  # the line of the source that proves the event


class Timeline(_Strict):
    """Timeline Reconstructor output."""

    events: list[TimelineEvent]
    utr: str | None
    amount_inr: float | None
    rail: Rail
    txn_date: str | None
    beneficiary: str
    customer_documents: int
    bank_records: int


class Override(_Strict):
    failure_point: FailurePoint
    reason: str
    by: str
    at: str


class FailureDiagnosis(_Strict):
    """Failure Diagnoser output."""

    failure_type: FailureType = "unknown"
    failure_point: FailurePoint = "Unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = ""
    next_actor: str = ""
    reasons: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    what_would_raise_confidence: str | None = None
    outage: str | None = None
    cluster_id: str | None = None
    override: Override | None = None

    @property
    def effective_point(self) -> str:
        return self.override.failure_point if self.override else self.failure_point


class Citation(_Strict):
    n: int  # footnote number used in drafts: [1], [2] ...
    label: str
    source: str
    ref: str = ""  # rule id, document id or log reference
    url: str | None = None


class ReferralCheck(_Strict):
    proposed_outcome: Literal["uphold", "reject"]
    internal_ombudsman_required: bool
    reason: str
    rbi_eligible_from: str  # customer may approach the RBI Ombudsman from this date if unresolved
    rbi_file_by: str  # last date to file with the RBI Ombudsman after that
    rule_ids: list[str]


class RightsCard(_Strict):
    """Policy and Rights output. Every number here comes from Python, never from the model."""

    rule_id: str
    rule_title: str
    rule_source: str
    rule_url: str | None
    rule_verified: bool
    tat_days: int
    tat_basis: str
    txn_date: str
    deadline: str
    as_of: str
    days_overdue: int
    breached: bool
    compensation_per_day: int
    compensation_inr: int
    arithmetic: str
    reversal_done: bool
    compensation_paid_inr: int
    principal_to_credit_inr: float
    total_to_credit_inr: float


class ComplaintDraft(_Strict):
    """Evidence and Complaint output: the entity's reply to the customer."""

    kind: Literal["customer_reply"] = "customer_reply"
    recipient: Literal["customer"] = "customer"
    title: str
    to: str
    text: str
    original_text: str
    citations: list[Citation] = Field(default_factory=list)
    edited_by_officer: bool = False
    locked_reason: str | None = None  # e.g. waiting for the Internal Ombudsman


class EscalationDraft(_Strict):
    """Escalation output: a referral to the Internal Ombudsman or a response to the RBI Ombudsman."""

    kind: EscalationLevel
    level: EscalationLevel
    title: str
    to: str
    text: str
    original_text: str
    grounds: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    edited_by_officer: bool = False
    locked_reason: str | None = None


Draft = Annotated[Union[ComplaintDraft, EscalationDraft], Field(discriminator="kind")]


class Checklist(_Strict):
    timeline: bool = False
    amounts: bool = False
    text: bool = False

    @property
    def complete(self) -> bool:
        return self.timeline and self.amounts and self.text


class Approval(_Strict):
    kind: DraftKind
    title: str
    status: Literal["pending", "approved", "sent", "rejected"] = "pending"
    checklist: Checklist = Field(default_factory=Checklist)
    approved_by: str | None = None
    approved_at: str | None = None
    rejection_reason: str | None = None


class FollowUp(_Strict):
    due: str
    what: str
    done: bool = False


class CaseUpdate(_Strict):
    """Case Tracker output."""

    state: CaseState
    previous_state: CaseState
    as_of: str
    message: str
    escalation_level: EscalationLevel | None = None
    redraft: bool = False
    followups_due: list[str] = Field(default_factory=list)


class RouteDecision(_Strict):
    """Orchestrator output: which specialist should act next, and why."""

    next_agent: str | None
    reason: str
    blocked_on_officer: bool = False


class BusEvent(_Strict):
    """Local stand-in for a Pub/Sub message."""

    id: str
    topic: str  # reversal_posted | customer_reply | rbi_complaint | io_decision | clock_tick
    date: str
    payload: dict = Field(default_factory=dict)
    processed: bool = False


class AuditEntry(_Strict):
    at: str  # ISO timestamp, UTC
    trace_id: str
    agent: str
    tool: str
    summary: str
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    via: Literal["adk", "seed", "officer", "system"] = "adk"


class Decision(_Strict):
    """Every human decision on a case, for the decision log."""

    at: str
    actor: str
    role: str
    action: Literal[
        "approved", "rejected_draft", "override", "requested_documents", "edited_draft",
        "closed", "reinvestigated",
    ]
    kind: str | None = None
    reason: str = ""
    compensation_inr: int | None = None


class Case(_Strict):
    id: str
    ref: str  # human-facing case number, e.g. MIL-24017
    trace_id: str
    title: str
    rail: Rail = "UNKNOWN"
    customer_ref: str
    customer_name: str = ""
    channel: str = "Branch / app complaint"
    received: str  # date the complaint reached the entity
    created: str
    today: str  # simulated 'now' for this case (moves with the practice clock)
    state: CaseState = "intake"
    running: bool = False
    step: str | None = None  # what the agent is doing right now, for the queue chip
    error: str | None = None
    assigned_officer: str = "Priya Sharma"
    bank: str = ""  # the regulated entity (remitter / issuer)
    beneficiary: str = ""  # beneficiary bank, merchant or ATM owner
    amount_inr: float | None = None
    utr: str | None = None
    txn_date: str | None = None
    documents: list[Document] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    diagnosis: FailureDiagnosis | None = None
    rights: RightsCard | None = None
    referral: ReferralCheck | None = None
    drafts: dict[str, Draft] = Field(default_factory=dict)
    approval: Approval | None = None
    sent: dict[str, dict] = Field(default_factory=dict)  # kind -> {date, reference, to}
    evidence_sha256: str | None = None
    awaiting_documents: list[str] = Field(default_factory=list)
    followups: list[FollowUp] = Field(default_factory=list)
    events: list[BusEvent] = Field(default_factory=list)
    audit: list[AuditEntry] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    chat: list[dict] = Field(default_factory=list)
    label: dict = Field(default_factory=dict)  # ground truth for synthetic cases (evals only)
    analysis_started_at: str | None = None
    rights_ready_at: str | None = None
