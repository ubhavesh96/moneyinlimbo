"""Failure-point classifier (stand-in for the Vertex AI custom model), outage lookup (stand-in for
the BigQuery incident table) and outage-cluster detection over the transaction store.

Deterministic and explainable: every reason cites the timeline event it rests on, and the
confidence only rises with independent evidence.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from mil_agent import settings
from mil_agent.data import synthetic
from mil_agent.data.synthetic import CODES, RAIL_FAILURE
from mil_agent.models import Case, FailureDiagnosis, TimelineEvent
from mil_agent.tools.timeline_package import parsing

CONFIDENT = 0.6  # below this the agent asks for more evidence before the rules are applied

_REQUEST = {
    "CARD_ONLINE": ("Merchant's order status or payment-failure email (it names the payment gateway)",
                    "The merchant's own record would show whether the gateway or the merchant dropped the payment."),
    "UPI": ("NPCI switch extract for the UTR (from payments operations)",
            "The switch record shows which leg of the transfer failed."),
    "IMPS": ("NPCI switch extract for the UTR (from payments operations)",
             "The switch record shows which leg of the transfer failed."),
    "ATM": ("ATM electronic journal or switch log for the RRN",
            "The ATM journal shows whether cash was presented."),
}


def _minutes(hhmm: str | None) -> int | None:
    if not hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def declared_outages(case: Case) -> list[dict]:
    raw = json.loads((settings.DATA_DIR / "outages.json").read_text(encoding="utf-8"))
    out = []
    for o in raw["outages"]:
        day = (date.fromisoformat(case.created) - timedelta(days=o["days_ago"])).isoformat()
        out.append({**o, "date": day})
    return out


def _txn_time(case: Case) -> tuple[str | None, int | None]:
    timed = [e for e in case.timeline if e.time and e.kind in ("request", "debit_posted", "debit_sms")]
    first = min(timed, key=lambda e: (e.date, e.time)) if timed else None
    return (first.date, _minutes(first.time)) if first else (case.txn_date, None)


def outage_for(case: Case) -> dict | None:
    """A declared incident on the transaction day that covers its time and involves its parties."""
    day, minute = _txn_time(case)
    gateway_text = " ".join(e.snippet or "" for e in case.timeline).lower()
    for o in declared_outages(case):
        if o["date"] != day:
            continue
        party = o["entity"].split()[0].lower()
        if party not in gateway_text and party not in (case.beneficiary or "").lower():
            continue
        if minute is not None and not (_minutes(o["start"]) - 60 <= minute <= _minutes(o["end"])):
            continue
        return o
    return None


def cluster_for(case: Case) -> dict | None:
    as_of = date.fromisoformat(case.created)
    txn = synthetic.by_utr(case.utr, as_of)
    return synthetic.detect_cluster(txn, as_of) if txn else None


def _cite(e: TimelineEvent) -> str:
    when = f"{e.date}{' ' + e.time if e.time else ''}"
    return f"[{e.id}] {e.source}, {when}"


def predict(case: Case) -> FailureDiagnosis:
    evs = case.timeline
    kinds = {e.kind for e in evs}
    by_kind = {}
    for e in evs:
        by_kind.setdefault(e.kind, e)
    stmt_debit = next((e for e in evs if e.source == "Bank statement" and e.kind == "debit"), None)
    bank_debit = by_kind.get("debit_posted")
    rail = case.rail

    if not (stmt_debit or bank_debit):
        return FailureDiagnosis(
            confidence=0.2, summary="There is no record of the debit yet, so the failure cannot be placed.",
            next_actor="Officer: obtain the customer's bank statement for the transaction date",
            reasons=["Neither the customer's statement nor the core-banking ledger shows the disputed debit."],
            missing_documents=["Bank statement showing the debit"],
            what_would_raise_confidence="A statement row or ledger entry with the UTR/RRN.")

    if "beneficiary_credited" in kinds:
        e = by_kind["beneficiary_credited"]
        return FailureDiagnosis(
            failure_type="credited_successfully", failure_point="None", confidence=0.93,
            summary=(f"Our records show the payment completed: {case.beneficiary or 'the beneficiary'} "
                     "credited the payee. Nothing is stuck."),
            next_actor="Officer: propose rejection; refer to the Internal Ombudsman before replying",
            reasons=[f"{_cite(e)}: beneficiary account credited.",
                     *([f"{_cite(bank_debit)}: debit posted as instructed."] if bank_debit else []),
                     "No timeout, decline or reversal appears in any bank record."])

    reasons: list[str] = []
    if stmt_debit:
        reasons.append(f"{_cite(stmt_debit)}: customer's statement shows the debit of Rs {stmt_debit.amount_inr:,.0f}.")
    if bank_debit:
        reasons.append(f"{_cite(bank_debit)}: our ledger confirms the debit.")
    if "debit_sms" in kinds:
        reasons.append(f"{_cite(by_kind['debit_sms'])}: debit SMS sent to the customer.")

    codes = [(c, e) for e in evs if e.source != "Bank statement" for c in parsing.find_codes(e.snippet or "")]
    failure_type = RAIL_FAILURE.get(rail, "unknown")
    point, conf, missing, raise_hint = "Unknown", 0.4, [], None

    if codes:
        code, ev = codes[0]
        point, why = CODES[code]
        reasons.append(f"{_cite(ev)}: {why} ({code}).")
        conf = 0.62 + 0.1 * bool(stmt_debit) + 0.05 * ("debit_sms" in kinds) + 0.1 * bool(bank_debit)
    elif rail == "CARD_ONLINE" and "confirmation_missing" in kinds:
        reasons.append(f"{_cite(by_kind['confirmation_missing'])}: the capture advice never reached us; "
                       "the cause sits outside the bank (merchant or gateway).")
        merchant = by_kind.get("merchant_not_paid")
        if merchant and "payment partner" in (merchant.snippet or "").lower():
            point, conf = "Gateway", 0.84
            reasons.append(f"{_cite(merchant)}: the merchant says its payment gateway never confirmed the payment.")
        else:
            point, conf = "Gateway", 0.45
    elif rail in ("UPI", "IMPS", "CARD_TO_CARD"):
        point, conf = "Beneficiary bank", 0.5  # the most common cause; not proven without the switch log
        reasons.append("No switch record is on file, so the failing leg is inferred from the payment type only.")
    elif rail == "ATM":
        point, conf = "Acquiring bank", 0.5
        reasons.append("No ATM journal is on file; an ATM debit without cash is usually an acquirer fault.")
    elif rail in ("CARD_POS", "UPI_MERCHANT"):
        point, conf = "Acquiring bank" if rail == "CARD_POS" else "Gateway", 0.5

    if "reversal_missing" in kinds:
        reasons.append(f"{_cite(by_kind['reversal_missing'])}: no automatic reversal has been posted.")
        conf += 0.05
    reversal = by_kind.get("reversal")
    if reversal:
        reasons.append(f"{_cite(reversal)}: a reversal of Rs {reversal.amount_inr or 0:,.0f} has already been posted.")

    outage, cluster = outage_for(case), cluster_for(case)
    if outage:
        reasons.append(f"Declared incident that day: {outage['entity']} {outage['start']}-{outage['end']} ({outage['note']})")
        conf += 0.05
    if cluster:
        reasons.append(f"Outage cluster {cluster['cluster_id']}: {cluster['failed']} of {cluster['in_window']} "
                       f"transactions to {cluster['beneficiary']} failed {cluster['window']} with {cluster['code']} "
                       f"(baseline {cluster['baseline_rate']:.1%}).")
        conf += 0.05
    conf = round(min(conf, 0.97), 2)

    if conf < CONFIDENT:
        need, hint = _REQUEST.get(rail, ("The bank's switch or ledger record for the UTR",
                                          "A bank-side record would show which party failed."))
        missing, raise_hint = [need], hint

    who = case.bank or "We"
    to_credit = 0 if reversal else case.amount_inr or 0
    actor = (f"{who} payments operations: credit Rs {to_credit:,.0f} plus any TAT compensation"
             + (f", then claim from {case.beneficiary}" if point in ("Beneficiary bank", "Acquiring bank", "Gateway")
                and case.beneficiary else "")) if not missing else f"Officer: obtain {missing[0].lower()}"
    plain = {
        "Beneficiary bank": f"The debit went through, but {case.beneficiary or 'the beneficiary bank'} never "
                            "posted the credit and no reversal followed.",
        "NPCI switch": "The switch timed out after the debit, so the credit leg never completed.",
        "Gateway": "The card was charged, but the payment gateway never confirmed the payment to the merchant.",
        "Acquiring bank": ("The ATM did not dispense cash and the acquiring bank sent no reversal advice."
                           if rail == "ATM" else
                           "The terminal's acquiring bank never confirmed the charge, so no charge slip exists."),
        "Remitter bank": "Our own core banking debited the account without completing the payment.",
    }.get(point, "The failure point is not clear from the evidence on file.")
    return FailureDiagnosis(
        failure_type=failure_type, failure_point=point, confidence=conf, summary=plain,  # type: ignore[arg-type]
        next_actor=actor, reasons=reasons, missing_documents=missing, what_would_raise_confidence=raise_hint,
        outage=f"{outage['entity']}: {outage['note']}" if outage else None,
        cluster_id=cluster["cluster_id"] if cluster else None)
