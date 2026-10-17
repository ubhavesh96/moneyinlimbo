"""Local document parser (stand-in for Document AI).

Reads what the customer handed in (complaint letter, bank statement, SMS, merchant mail) and what
the BankConnector returns (switch, CBS, gateway and ATM logs). Every event keeps the document id
and the exact line it came from, so the officer can check each claim against its source.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from mil_agent.data.synthetic import CODES
from mil_agent.models import Document, TimelineEvent

_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_DATE_RE = re.compile(
    rf"(\d{{4}}-\d{{2}}-\d{{2}})|(\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{4}})|(\d{{1,2}}\s(?:{_MONTHS})[a-z]*\.?,?\s\d{{4}})",
    re.I,
)
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})(?::\d{2})?\b")
_AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)\s?([\d,]+(?:\.\d{1,2})?)", re.I)
_UTR_RE = re.compile(r"(?:utr|rrn|ref(?:erence)?(?:\s*no)?)[\s:.#/=-]*([0-9]{12})", re.I)
_BARE_UTR_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})(?::\d{2})?\s+(.+)$")
_CODE_RE = re.compile(r"\b([A-Z]+(?:_[A-Z]+){1,3})\b")

# Statement narration prefix -> payment rail
RAIL_PREFIXES = [
    (r"^UPI/P2M/", "UPI_MERCHANT"), (r"^UPI/", "UPI"), (r"^IMPS/", "IMPS"),
    (r"^CARD2CARD/", "CARD_TO_CARD"), (r"^POS/", "CARD_POS"), (r"^ECOM/", "CARD_ONLINE"),
    (r"^ATM", "ATM"),
]

# Bank log text -> event kind (first match wins)
_LOG_KINDS = [
    (r"COMPENSATION CREDIT", "compensation_paid"),
    (r"REVERSAL CREDIT|AUTO-REVERSAL POSTED", "reversal"),
    (r"CREDIT POSTED|RESULT=SUCCESS", "beneficiary_credited"),
    (r"DISPENSE FAULT", "atm_failed"),
    (r"RESULT=TIMEOUT|CREDIT NOT POSTED|TIMED OUT", "credit_failed"),
    (r"REVERSAL NOT EXECUTED|NO REVERSAL|REVERSAL ADVICE NOT RECEIVED", "reversal_missing"),
    (r"NOT GENERATED|NOT RECEIVED|NO MERCHANT CONFIRMATION|CAPTURE ADVICE NOT RECEIVED", "confirmation_missing"),
    (r"DEBIT POSTED|DEBIT CONFIRMED", "debit_posted"),
    (r"AUTH APPROVED|REQPAY|CASH WDL REQUEST|IMPS REQUEST", "request"),
]


def parse_date(raw: str) -> str | None:
    raw = raw.strip().rstrip(",").replace(".", "")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def find_dates(text: str) -> list[str]:
    return [d for d in (parse_date(m.group(0)) for m in _DATE_RE.finditer(text)) if d]


def find_amount(text: str) -> float | None:
    m = _AMOUNT_RE.search(text)
    return float(m.group(1).replace(",", "")) if m else None


def find_utr(text: str) -> str | None:
    m = _UTR_RE.search(text) or _BARE_UTR_RE.search(text)
    return m.group(1) if m else None


def find_codes(text: str) -> list[str]:
    return [c for c in _CODE_RE.findall(text) if c in CODES]


def rail_from_narration(narr: str) -> str | None:
    for pat, rail in RAIL_PREFIXES:
        if re.search(pat, narr.strip(), re.I):
            return rail
    return None


def detect_kind(name: str, text: str) -> str:
    low = text.lower()
    head = low[:300]
    if head.startswith("# source:"):
        return "bank_log"
    if head.startswith("complaint received") or "complaint received:" in head:
        return "complaint"
    if name.lower().endswith(".csv") and ("narration" in head or "description" in head):
        return "statement"
    if re.search(r"\b(debited|credited|withdrawn|spent on card|a/c)\b", low) and "order" not in head \
            and "merchant:" not in head:
        return "sms"
    if re.search(r"\b(order|refund|merchant|invoice|receipt|booking)\b", low):
        return "merchant"
    return "other"


def extract_text(name: str, data: bytes) -> str:
    if name.lower().endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if name.lower().endswith((".png", ".jpg", ".jpeg")):
        raise ValueError(
            "Screenshots need Document AI OCR, which is not part of the local prototype. "
            "Paste the text of the SMS or receipt into a .txt file instead."
        )
    return data.decode("utf-8", errors="replace")


def log_source(doc: Document) -> str:
    m = re.match(r"#\s*source:\s*([^(\n]+)", doc.text.strip(), re.I)
    name = (m.group(1).strip() if m else "").lower()
    for key, label in (("npci", "NPCI switch"), ("beneficiary", "Beneficiary CBS"), ("gateway", "Gateway log"),
                       ("atm", "ATM switch"), ("card", "Remitter CBS"), ("remitter", "Remitter CBS")):
        if key in name:
            return label
    return "Remitter CBS"


def events_from_document(doc: Document) -> list[TimelineEvent]:
    """Raw events from one document. Ids are assigned later, once the timeline is merged."""
    if doc.kind == "statement":
        return _from_statement(doc)
    if doc.kind == "bank_log":
        return _from_log(doc)
    if doc.kind == "complaint":
        return _from_complaint(doc)
    return _from_prose(doc)


def _ev(**kw) -> TimelineEvent:
    return TimelineEvent(id="", **kw)


def _num(s: str) -> float:
    try:
        return float(s.replace(",", "") or 0)
    except ValueError:
        return 0.0


def _from_statement(doc: Document) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    body = "\n".join(ln for ln in doc.text.splitlines() if not ln.lstrip().startswith("#"))
    for row in csv.DictReader(io.StringIO(body)):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        d = parse_date(row.get("date", ""))
        narr = row.get("narration") or row.get("description") or ""
        debit = _num(row.get("debit") or row.get("withdrawal") or "")
        credit = _num(row.get("credit") or row.get("deposit") or "")
        if not d:
            continue
        line = ",".join(v for v in row.values() if v)
        if debit > 0:
            events.append(_ev(date=d, source="Bank statement", kind="debit", amount_inr=debit,
                              ref=find_utr(narr), doc_id=doc.id, snippet=line,
                              text=f"Statement shows a debit of Rs {debit:,.0f} ({narr})."))
        elif credit > 0:
            kind = "reversal" if re.search(r"refund|reversal|rev\b", narr, re.I) else "credit"
            events.append(_ev(date=d, source="Bank statement", kind=kind, amount_inr=credit,
                              ref=find_utr(narr), doc_id=doc.id, snippet=line,
                              text=f"Statement shows a credit of Rs {credit:,.0f} ({narr})."))
    return events


def _from_log(doc: Document) -> list[TimelineEvent]:
    source = log_source(doc)
    events = []
    for line in doc.text.splitlines():
        m = _LOG_LINE_RE.match(line.strip())
        if not m:
            continue
        d, t, body = m.groups()
        kind = next((k for pat, k in _LOG_KINDS if re.search(pat, body, re.I)), "log")
        events.append(_ev(date=d, time=t, source=source, kind=kind, amount_inr=find_amount(body),
                          ref=find_utr(body), doc_id=doc.id, snippet=line.strip(),
                          text=_log_text(kind, body, source)))
    return events


def _log_text(kind: str, body: str, source: str) -> str:
    codes = find_codes(body)
    code = f" ({codes[0]})" if codes else ""
    return {
        "request": f"{source}: payment request received.",
        "debit_posted": f"{source}: customer's account debited.",
        "credit_failed": f"{source}: credit to the beneficiary failed{code}.",
        "beneficiary_credited": f"{source}: beneficiary account credited.",
        "reversal": f"{source}: reversal credited to the customer.",
        "reversal_missing": f"{source}: no reversal has been posted.",
        "compensation_paid": f"{source}: TAT compensation credited.",
        "atm_failed": f"{source}: ATM reported a dispense fault, no cash presented{code}.",
        "confirmation_missing": f"{source}: merchant or acquirer confirmation never arrived{code}.",
    }.get(kind, f"{source}: {body[:120]}")


def _from_complaint(doc: Document) -> list[TimelineEvent]:
    m = re.search(r"complaint received:\s*(\S+)", doc.text, re.I)
    d = parse_date(m.group(1)) if m else None
    if not d:
        return []
    return [_ev(date=d, source="Complaint", kind="complaint_received", amount_inr=find_amount(doc.text),
                ref=find_utr(doc.text), doc_id=doc.id, snippet=_tidy(doc.text, "complaint"),
                text="Customer complaint received by the grievance desk.")]


def _from_prose(doc: Document) -> list[TimelineEvent]:
    text, low = doc.text, doc.text.lower()
    dates = find_dates(text)
    if not dates:
        return []
    tm = _TIME_RE.search(text)
    base = dict(date=dates[0], time=tm.group(1) if tm and doc.kind == "sms" else None,
                amount_inr=find_amount(text), ref=find_utr(text), doc_id=doc.id, snippet=_tidy(text, doc.kind))
    if doc.kind == "sms":
        if re.search(r"credited|reversed|refund", low) and not re.search(r"debited|withdrawn|spent", low):
            return [_ev(source="SMS", kind="reversal", text="Bank SMS confirms a credit back to the customer.", **base)]
        if re.search(r"debited|withdrawn|spent", low):
            return [_ev(source="SMS", kind="debit_sms", text="Bank SMS confirms the debit to the customer.", **base)]
        return []
    if re.search(r"did not confirm|not confirmed|could not be completed|payment failed|not received", low):
        kind, msg = "merchant_not_paid", "Merchant says the payment was never confirmed to them."
    elif re.search(r"refund (has been )?(initiated|processed)|will be refunded", low):
        kind, msg = "merchant_refund", "Merchant says a refund was initiated."
    else:
        kind, msg = "note", "Merchant correspondence on file."
    gw = re.search(r"payment partner\s+(\w+)", text, re.I)
    if gw:
        msg += f" It names {gw.group(1)} as the payment partner."
    return [_ev(source="Merchant", kind=kind, text=msg, **base)]


def guess_bank(docs: list[Document]) -> str:
    for d in docs:
        for line in d.text.splitlines()[:6]:
            m = re.match(r"\s*#?\s*(bank|account bank)\s*[:=]\s*(.+)", line, re.I)
            if m:
                return m.group(2).strip()
    return ""


def focus(events: list[TimelineEvent], utr: str | None, amount: float | None) -> list[TimelineEvent]:
    """Keep only the disputed transaction: drop statement rows that match neither its reference nor
    its amount (salary, other purchases)."""
    def relevant(e: TimelineEvent) -> bool:
        if e.source != "Bank statement":
            return True
        return bool((utr and e.ref == utr) or (amount and e.amount_inr == amount))

    return [e for e in events if relevant(e)]


def _tidy(text: str, kind: str) -> str:
    """One readable line for the evidence snippet: drop header lines and boilerplate."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    subject = next((ln.split(":", 1)[1].strip() for ln in lines if ln.lower().startswith("subject:")), "")
    body = [ln for ln in lines
            if not re.match(r"(merchant|date|subject|from|to|channel|customer|complaint received)\s*:", ln, re.I)]
    out = " ".join(body)
    out = re.sub(r"\s*If not you.*$", "", out, flags=re.I)
    if kind == "merchant" and subject:
        out = f"{subject}. {out}"
    return out[:240].strip()
