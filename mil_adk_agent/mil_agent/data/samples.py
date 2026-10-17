"""Sample complaints for the officer demo, plus a labelled eval set. All synthetic.

Each sample is a complaint that reached Sunrise Bank's grievance desk, with the documents the
customer handed in. Bank-side records (switch, CBS, gateway, ATM logs) are not here: the agent
pulls them through the BankConnector, as it would in a real deployment.

    python -m mil_agent.data.samples out_folder   # write the customer documents to disk for upload
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

from mil_agent.data import synthetic
from mil_agent.data.synthetic import ENTITY, HEROES, Txn

SAMPLE_CASES = [
    {"id": "A", "hero": "Case A", "title": "UPI: debited, beneficiary not credited", "rail": "UPI",
     "blurb": "Rs 4,250 sent by UPI a week ago. The payee never got it. T+1 breached by 6 days.",
     "customer_ref": "CUST-88213", "customer_name": "Asha Verma", "received_days_ago": 6, "seed": "intake",
     "label": {"failure_type": "upi_transfer_not_credited", "failure_point": "Beneficiary bank"}},
    {"id": "B", "hero": "Case B", "title": "Card online: merchant never confirmed", "rail": "CARD_ONLINE",
     "blurb": "Rs 12,800 card payment to TravelKart. Only a statement and an SMS so far.",
     "customer_ref": "CUST-40117", "customer_name": "Rahul Menon", "received_days_ago": 7, "seed": "analyzed",
     "label": {"failure_type": "card_online_not_confirmed", "failure_point": "Gateway"}},
    {"id": "C1", "hero": "Case C", "title": "UPI: debited, beneficiary not credited", "rail": "UPI",
     "blurb": "Rs 1,999 to Coastal Co-operative Bank, 5 days ago, early evening.",
     "customer_ref": "CUST-51902", "customer_name": "Imran Khan", "received_days_ago": 4, "seed": "analyzed",
     "label": {"failure_type": "upi_transfer_not_credited", "failure_point": "Beneficiary bank"}},
    {"id": "C2", "hero": "Case C", "title": "UPI: debited, beneficiary not credited", "rail": "UPI",
     "blurb": "Rs 7,500 to Coastal Co-operative Bank, same evening.",
     "customer_ref": "CUST-51977", "customer_name": "Meena Pillai", "received_days_ago": 4, "seed": "analyzed",
     "label": {"failure_type": "upi_transfer_not_credited", "failure_point": "Beneficiary bank"}},
    {"id": "C3", "hero": "Case C", "title": "UPI: debited, beneficiary not credited", "rail": "UPI",
     "blurb": "Rs 350 to Coastal Co-operative Bank, same evening.",
     "customer_ref": "CUST-52004", "customer_name": "Sourav Das", "received_days_ago": 3, "seed": "intake",
     "label": {"failure_type": "upi_transfer_not_credited", "failure_point": "Beneficiary bank"}},
    {"id": "D", "hero": "", "title": "IMPS: debited, beneficiary not credited", "rail": "IMPS",
     "blurb": "Rs 25,000 IMPS to Harbour Bank timed out at the switch.",
     "customer_ref": "CUST-30551", "customer_name": "Kavya Rao", "received_days_ago": 2, "seed": "analyzed",
     "label": {"failure_type": "imps_not_credited", "failure_point": "NPCI switch"}},
    {"id": "E", "hero": "", "title": "Card at PoS: no charge slip, account debited", "rail": "CARD_POS",
     "blurb": "Rs 3,640 at FreshCart. Terminal declined, card still charged. Inside T+5.",
     "customer_ref": "CUST-77420", "customer_name": "Neha Joshi", "received_days_ago": 2, "seed": "analyzed",
     "label": {"failure_type": "card_pos_not_confirmed", "failure_point": "Acquiring bank"}},
    {"id": "F", "hero": "", "title": "ATM: cash not dispensed, account debited", "rail": "ATM",
     "blurb": "Rs 10,000 at another bank's ATM. Reply already approved and sent.",
     "customer_ref": "CUST-19008", "customer_name": "Arjun Patel", "received_days_ago": 7, "seed": "sent",
     "label": {"failure_type": "atm_cash_not_dispensed", "failure_point": "Acquiring bank"}},
    {"id": "G", "hero": "", "title": "UPI: customer says payee not credited", "rail": "UPI",
     "blurb": "Rs 6,000 to Pinecrest Bank. Our records show the credit went through.",
     "customer_ref": "CUST-66310", "customer_name": "Lakshmi Iyer", "received_days_ago": 5, "seed": "analyzed",
     "label": {"failure_type": "credited_successfully", "failure_point": "None"}},
]

# Documents an officer can obtain later when the agent asks for them (Case B).
REQUESTABLE = {
    "B": "merchant_email.txt",
}

_NARRATION = {
    "UPI": "UPI/P2P/{utr}/{payee}/{ben}",
    "UPI_MERCHANT": "UPI/P2M/{utr}/{ben}",
    "IMPS": "IMPS/P2A/{utr}/{payee}/{ben}",
    "CARD_TO_CARD": "CARD2CARD/{utr}/{ben}",
    "CARD_POS": "POS/{ben}/{utr}",
    "CARD_ONLINE": "ECOM/{ben}/{gw}/{utr}",
    "ATM": "ATM WDL/{ben}/{utr}",
}
_SMS_VERB = {"ATM": "withdrawn from A/c XX4821 at {ben}", "CARD_POS": "spent on card XX9012 at {ben}",
             "CARD_ONLINE": "spent on card XX9012 at {ben}", "CARD_TO_CARD": "debited from card XX9012"}


def meta(sample_id: str) -> dict:
    return next(s for s in SAMPLE_CASES if s["id"] == sample_id)


def statement(x: Txn, balance: float = 38_210.0) -> str:
    narr = _NARRATION[x.rail].format(utr=x.utr, payee=x.payee_name or "PAYEE",
                                     ben=x.beneficiary.upper().replace(",", ""), gw=(x.gateway or "").upper())
    prior = (date.fromisoformat(x.date) - timedelta(days=3)).isoformat()
    return (f"# Bank: {ENTITY}\n# Account: XXXX4821 (synthetic)\n"
            "Date,Narration,Debit,Credit,Balance\n"
            f"{prior},NEFT/SALARY/ACME LTD,,52000,{balance + x.amount + 640:.0f}\n"
            f"{prior},UPI/P2M/411122233344/GROCER,640,,{balance + x.amount:.0f}\n"
            f"{x.date},{narr},{x.amount:.0f},,{balance:.0f}\n")


def sms(x: Txn) -> str:
    verb = _SMS_VERB.get(x.rail, "debited from A/c XX4821 via {rail} to {payee}")
    what = verb.format(ben=x.beneficiary, rail=x.rail.split("_")[0], payee=x.payee_name or x.beneficiary)
    ref = "UTR" if x.rail in ("UPI", "UPI_MERCHANT", "IMPS") else "Ref"
    return f"{x.date} {x.time} {ENTITY}: Rs {x.amount:,.2f} {what}. {ref} {x.utr}. If not you, call 1800-000-000.\n"


def complaint_letter(x: Txn, m: dict, received: str) -> str:
    story = {
        "UPI": f"I sent Rs {x.amount:,.0f} by UPI to {x.payee_name.title()} at {x.beneficiary}. The money left my "
               "account but they say they never received it.",
        "IMPS": f"I sent Rs {x.amount:,.0f} by IMPS to {x.payee_name.title()} at {x.beneficiary}. It was debited "
                "but not received.",
        "CARD_ONLINE": f"I paid Rs {x.amount:,.0f} by card on {x.beneficiary}'s website. The booking failed but my "
                       "card was charged.",
        "CARD_POS": f"I paid Rs {x.amount:,.0f} by card at {x.beneficiary}. The terminal showed declined and I paid "
                    "again in cash, but my card was still charged.",
        "ATM": f"I tried to withdraw Rs {x.amount:,.0f} at {x.beneficiary}. No cash came out but my account was "
               "debited.",
    }.get(x.rail, f"Rs {x.amount:,.0f} was debited but the payment did not complete.")
    return (f"Complaint received: {received}\nChannel: Branch / mobile app (synthetic)\n"
            f"Customer: {m['customer_name']} ({m['customer_ref']})\n\n"
            f"On {x.date} {story} Reference {x.utr}. Please return my money.\n")


def merchant_email(x: Txn) -> str:
    return (f"Merchant: {x.beneficiary}\nDate: {x.date}\nSubject: Booking not confirmed\n\n"
            f"Your booking TK-55120 could not be completed. Our payment partner {x.gateway} did not confirm "
            f"your payment of Rs {x.amount:,.0f}, so no booking was made. If your card was charged, your bank "
            f"will return it. Ref {x.utr}.\n")


def sample_files(sample_id: str, today: date | None = None, include_requested: bool = False) -> dict[str, str]:
    """The documents the customer handed in for this complaint."""
    t = today or date.today()
    m = meta(sample_id)  # raises StopIteration for unknown ids
    x = synthetic.by_utr(HEROES[sample_id]["utr"], t)
    received = (t - timedelta(days=m["received_days_ago"])).isoformat()
    files = {"complaint.txt": complaint_letter(x, m, received), "bank_statement.csv": statement(x)}
    if sample_id not in ("E",):  # the PoS customer only kept the statement
        files["bank_sms.txt"] = sms(x)
    if include_requested and sample_id in REQUESTABLE:
        files.update(requested_file(sample_id, t))
    return files


def requested_file(sample_id: str, today: date | None = None) -> dict[str, str]:
    x = synthetic.by_utr(HEROES[sample_id]["utr"], today or date.today())
    if sample_id == "B":
        return {REQUESTABLE["B"]: merchant_email(x)}
    raise KeyError(sample_id)


def received_date(sample_id: str, today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=meta(sample_id)["received_days_ago"])).isoformat()


def eval_set(n: int = 60, today: date | None = None) -> list[dict]:
    """Labelled synthetic complaints drawn from the transaction store, for the diagnosis eval.

    About a third arrive with the statement only (no SMS), and the connector is told to withhold the
    switch log for one in five, so the classifier is tested on thin evidence too."""
    t = today or date.today()
    rng = random.Random(7)
    failed = [x for x in synthetic.store(t) if x.failed and not x.tags]
    ok = [x for x in synthetic.store(t) if not x.failed and x.rail in ("UPI", "IMPS")]
    picks = rng.sample(failed, min(n - 6, len(failed))) + rng.sample(ok, 6)
    out = []
    for i, x in enumerate(picks):
        m = {"customer_name": "Eval Customer", "customer_ref": f"EVAL-{i:03d}"}
        files = {"complaint.txt": complaint_letter(x, m, x.date), "bank_statement.csv": statement(x)}
        if rng.random() > 0.33:
            files["bank_sms.txt"] = sms(x)
        out.append({"utr": x.utr, "files": files, "withhold_switch_log": rng.random() < 0.2,
                    "label": {"failure_type": x.failure_type, "failure_point": x.failure_point}})
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_files")
    for c in SAMPLE_CASES:
        folder = out / c["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in sample_files(c["id"], include_requested=True).items():
            (folder / name).write_text(text, encoding="utf-8")
    print(f"Wrote samples to {out.resolve()}")
