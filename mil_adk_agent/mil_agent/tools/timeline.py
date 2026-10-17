"""Timeline Reconstructor tools: parse_document, normalize_events."""

from __future__ import annotations

import re
from datetime import date
from collections import Counter

from google.adk.tools import ToolContext

from mil_agent.models import Case, Document, Timeline, TimelineEvent
from mil_agent.services import case_service
from mil_agent.tools.common import agent_name, done, fail, load, money
from mil_agent.tools.timeline_package import bank_connector, parsing
from mil_agent.tools.tracker_package import state_machine

AGENT = "timeline_reconstructor"
_SOURCE_RANK = {"Complaint": 9, "Bank statement": 0, "SMS": 1, "Merchant": 4}


def parse_document(case_id: str, document_name: str = "", tool_context: ToolContext = None) -> dict:
    """Extract events (dates, amounts, UTR/RRN) from the customer's documents.

    Args:
        case_id: The case.
        document_name: One document to parse; leave empty to parse every customer document.

    Returns:
        How many events were found per document, and the UTR/RRN references seen.
    """
    case = load(case_id)
    docs = [d for d in case.documents if d.origin == "customer"
            and (not document_name or d.name == document_name)]
    if not docs:
        return fail(f"No customer document named '{document_name}'." if document_name
                    else "The case has no customer documents yet.")
    found = {d.name: len(parsing.events_from_document(d)) for d in docs}
    if not sum(found.values()):
        return fail("No transactions could be read from the customer's documents.")
    case.utr = case.utr or disputed_utr(docs)
    return done(case, agent_name(tool_context, AGENT), "parse_document",
                f"Read {len(docs)} customer document(s): {sum(found.values())} event(s), reference {case.utr or 'not found'}.",
                inputs={"case_id": case_id, "document_name": document_name},
                events_per_document=found, utr=case.utr)


def disputed_utr(docs: list[Document]) -> str | None:
    """The disputed reference: the one the customer's own papers mention most."""
    refs: Counter[str] = Counter()
    for d in docs:
        if d.kind == "other":
            d.kind = parsing.detect_kind(d.name, d.text)  # type: ignore[assignment]
        refs.update(e.ref for e in parsing.events_from_document(d) if e.ref)
    return refs.most_common(1)[0][0] if refs else None


def attach_bank_records(case: Case, connector: bank_connector.BankConnector | None = None) -> int:
    """Pull the entity's own records for the UTR through the BankConnector (once per case)."""
    if not case.utr:
        return 0
    have = {d.name for d in case.documents}
    added = 0
    for name, text in (connector or bank_connector.get_connector()).records(
            case.utr, date.fromisoformat(case.created)).items():
        if name not in have:
            case.documents.append(Document(id=f"doc-{len(case.documents) + 1}", name=name, kind="bank_log",
                                           origin="bank_connector", text=text))
            added += 1
    return added


def build_timeline(case: Case) -> Timeline:
    events: list[TimelineEvent] = []
    for d in case.documents:
        events.extend(parsing.events_from_document(d))
    disputed = next((e for e in events if e.source == "Bank statement" and e.ref == case.utr), None)
    amount = disputed.amount_inr if disputed else next(
        (e.amount_inr for e in events if e.ref == case.utr and e.amount_inr), None)
    events = parsing.focus(events, case.utr, amount)
    events.sort(key=lambda e: (e.date, e.time or "", _SOURCE_RANK.get(e.source, 5)))
    for i, e in enumerate(events, 1):
        e.id = f"ev-{i}"

    rail = "UNKNOWN"
    if disputed:
        rail = parsing.rail_from_narration(disputed.snippet.split(",")[1] if disputed.snippet else "") or rail
    if rail == "UNKNOWN":
        sms = next((e for e in events if e.source == "SMS"), None)
        if sms and sms.snippet:
            low = sms.snippet.lower()
            rail = ("ATM" if " atm" in low else "UPI" if "via upi" in low else "IMPS" if "via imps" in low
                    else "CARD_POS" if "spent on card" in low else rail)
    debit = disputed or next((e for e in events if e.kind in ("debit_sms", "debit_posted")), None)
    beneficiary = ""
    if disputed and disputed.snippet:
        # Narrations name the merchant/ATM first for card and ATM rails, the payee bank last otherwise.
        parts = [p for p in disputed.snippet.split(",")[1].split("/") if p and not re.fullmatch(r"\d+", p)]
        if len(parts) > 1:
            raw = parts[1] if rail in ("CARD_POS", "CARD_ONLINE", "ATM") else parts[-1]
            beneficiary = " ".join(w if len(w) <= 3 and w.isalpha() and w.isupper() else w.capitalize()
                                   for w in raw.split())
    return Timeline(
        events=events, utr=case.utr, amount_inr=amount, rail=rail,  # type: ignore[arg-type]
        txn_date=debit.date if debit else None, beneficiary=beneficiary,
        customer_documents=sum(1 for d in case.documents if d.origin == "customer"),
        bank_records=sum(1 for d in case.documents if d.origin == "bank_connector"),
    )


def apply_timeline(case: Case) -> Timeline:
    """Build the timeline and copy its facts onto the case (in memory; the caller saves)."""
    tl = build_timeline(case)
    case.timeline, case.rail, case.amount_inr, case.txn_date = tl.events, tl.rail, tl.amount_inr, tl.txn_date
    case.beneficiary = tl.beneficiary or case.beneficiary
    case.bank = case.bank or parsing.guess_bank(case.documents)
    return tl


def normalize_events(case_id: str, tool_context: ToolContext = None) -> dict:
    """Pull the bank's own records for the transaction (switch, core banking, card or ATM logs),
    merge them with the customer's documents, keep only the disputed transaction and order it.

    Args:
        case_id: The case. Call parse_document first.

    Returns:
        The typed Timeline: ordered events, UTR, amount, payment rail and transaction date.
    """
    case = load(case_id)
    if not case.documents:
        return fail("The case has no documents yet.")
    added = attach_bank_records(case)
    tl = apply_timeline(case)
    if not tl.events:
        return fail("No events could be built from the documents.")
    case_service.save(case)
    state_machine.advance(case, "reconstructed", f"{len(tl.events)} events from {tl.customer_documents} customer "
                                                 f"document(s) and {tl.bank_records} bank record(s)")
    return done(case, agent_name(tool_context, AGENT), "normalize_events",
                f"Timeline of {len(tl.events)} events for {money(tl.amount_inr)} ({tl.rail}), "
                f"{added} bank record(s) pulled via {bank_connector.get_connector().name}.",
                output=tl)
