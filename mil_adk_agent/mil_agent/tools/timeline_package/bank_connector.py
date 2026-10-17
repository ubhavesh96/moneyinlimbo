"""BankConnector: how the agent reads the entity's own records for a transaction.

The interface is what a real deployment implements against core banking, the UPI/IMPS switch
and card systems. The mock reads the synthetic transaction store and renders the extracts an
operations team would export. Gateway and merchant systems sit outside the bank, so for card-online
payments the bank can only see that the confirmation never arrived, not why.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from mil_agent.data import synthetic
from mil_agent.data.synthetic import ENTITY, ENTITY_IFSC, Txn


class BankConnector(Protocol):
    name: str

    def records(self, utr: str, as_of: date | None = None) -> dict[str, str]:
        """Log extracts for one transaction, as {file name: text}. Empty if the UTR is unknown.
        `as_of` is the date the case was opened (the mock store is generated relative to it)."""
        ...


def _ts(x: Txn, plus_seconds: int) -> str:
    h, m = (int(v) for v in x.time.split(":"))
    total = h * 3600 + m * 60 + plus_seconds
    return f"{x.date} {total // 3600 % 24:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


def _remitter_ledger(x: Txn) -> str:
    lines = ["# Source: Remitter CBS ledger, " + ENTITY + " (synthetic extract)",
             f"{_ts(x, 1)} DEBIT POSTED A/c XX4821 AMT={x.amount:.2f} REF={x.utr}"]
    if x.reversal_date:
        lines.append(f"{x.reversal_date} 09:00:00 REVERSAL CREDIT A/c XX4821 AMT={x.amount:.2f} REF={x.utr}")
    elif x.failed:
        lines.append(f"{_ts(x, 2)} AUTO-REVERSAL STATUS: REVERSAL NOT EXECUTED REF={x.utr}")
    if x.compensation_paid:
        lines.append(f"{x.reversal_date or x.date} 09:05:00 COMPENSATION CREDIT AMT={x.compensation_paid:.2f} REF={x.utr}")
    return "\n".join(lines) + "\n"


def _switch_log(x: Txn) -> str:
    kind = "IMPS REQUEST" if x.rail == "IMPS" else "REQPAY"
    payee = "PAYEE_TYPE=MERCHANT" if x.rail == "UPI_MERCHANT" else "PAYEE_TYPE=PERSON"
    lines = ["# Source: NPCI switch extract (synthetic)",
             f"{_ts(x, 0)} {kind} UTR={x.utr} AMT={x.amount:.2f} PAYER={ENTITY_IFSC} BENEFICIARY={x.beneficiary} {payee}",
             f"{_ts(x, 1)} DEBIT CONFIRMED by remitter {ENTITY} UTR={x.utr}"]
    if x.failed:
        lines.append(f"{_ts(x, 31)} CREDIT_REQUEST to {x.beneficiary} RESULT=TIMEOUT ({x.code}) UTR={x.utr}")
        lines.append(f"{_ts(x, 32)} TXN STATUS=DEEMED_PENDING UTR={x.utr}")
    else:
        lines.append(f"{_ts(x, 3)} CREDIT_REQUEST to {x.beneficiary} RESULT=SUCCESS UTR={x.utr}")
    return "\n".join(lines) + "\n"


def _beneficiary_status(x: Txn) -> str:
    head = f"# Source: Beneficiary CBS status check via switch, {x.beneficiary} (synthetic)"
    if x.failed:
        body = f"{_ts(x, 3600)} STATUS CHECK UTR={x.utr}: CREDIT NOT POSTED to beneficiary account"
    else:
        body = f"{_ts(x, 3600)} STATUS CHECK UTR={x.utr}: CREDIT POSTED to beneficiary {x.payee_name} at {_ts(x, 3)[11:]}"
    return f"{head}\n{body}\n"


def _card_auth(x: Txn) -> str:
    lines = [f"# Source: Card issuing system, {ENTITY} (synthetic extract)",
             f"{_ts(x, 0)} AUTH APPROVED card XX9012 AMT={x.amount:.2f} MERCHANT={x.beneficiary} RRN={x.utr}",
             f"{_ts(x, 2)} DEBIT POSTED card XX9012 AMT={x.amount:.2f} RRN={x.utr}"]
    if x.failed and x.rail == "CARD_ONLINE":
        # The issuer cannot see inside the gateway: it only knows the capture never arrived.
        lines.append(f"{x.date} 23:59:00 CAPTURE ADVICE NOT RECEIVED for RRN={x.utr} (merchant side unknown)")
    elif x.failed:
        lines.append(f"{_ts(x, 40)} CHARGE SLIP NOT GENERATED; COMPLETION ADVICE NOT RECEIVED FROM ACQUIRER "
                     f"({x.code}) {x.terminal} RRN={x.utr}")
    return "\n".join(lines) + "\n"


def _atm_log(x: Txn) -> str:
    lines = [f"# Source: ATM switch / electronic journal, {x.terminal} (synthetic)",
             f"{_ts(x, 0)} CASH WDL REQUEST card XX9012 AMT={x.amount:.2f} RRN={x.utr}",
             f"{_ts(x, 1)} DEBIT POSTED A/c XX4821 AMT={x.amount:.2f} RRN={x.utr}"]
    if x.failed:
        lines.append(f"{_ts(x, 25)} DISPENSE FAULT ({x.code}) cash not presented RRN={x.utr}")
        lines.append(f"{_ts(x, 26)} REVERSAL ADVICE NOT RECEIVED FROM ACQUIRER RRN={x.utr}")
    return "\n".join(lines) + "\n"


class MockBankConnector:
    """Reads the synthetic store. `withhold` drops the switch log, to test thin-evidence cases."""

    name = "Mock bank API (synthetic)"

    def __init__(self, today: date | None = None, withhold_switch_log: bool = False):
        self.today = today
        self.withhold = withhold_switch_log

    def records(self, utr: str, as_of: date | None = None) -> dict[str, str]:
        x = synthetic.by_utr(utr, self.today or as_of)
        if x is None:
            return {}
        out = {f"remitter_cbs_{utr}.log": _remitter_ledger(x)}
        if x.rail in ("UPI", "UPI_MERCHANT", "IMPS", "CARD_TO_CARD"):
            if not self.withhold:
                out[f"npci_switch_{utr}.log"] = _switch_log(x)
            if x.rail != "UPI_MERCHANT":
                out[f"beneficiary_status_{utr}.log"] = _beneficiary_status(x)
        elif x.rail in ("CARD_POS", "CARD_ONLINE"):
            out[f"card_issuing_{utr}.log"] = _card_auth(x)
        elif x.rail == "ATM" and not self.withhold:
            out[f"atm_switch_{utr}.log"] = _atm_log(x)
        return out


_connector: BankConnector = MockBankConnector()


def get_connector() -> BankConnector:
    return _connector


def set_connector(c: BankConnector) -> None:
    """Swap the connector (tests, evals, or a real core-banking adapter later)."""
    global _connector
    _connector = c
