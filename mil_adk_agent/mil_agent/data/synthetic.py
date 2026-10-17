"""Synthetic transaction store: the stand-in for BigQuery and the mock bank API.

About 5,000 transactions over the last 30 days for one regulated entity (Sunrise Bank), with:
- a background of ordinary failures (~1.5%), most of them auto-reversed in time;
- a seeded outage cluster: UPI credits to Coastal Co-operative Bank timing out for two hours,
  five days ago (hero Case C);
- the hand-written hero transactions used by the sample complaints.

Everything is generated from a fixed seed relative to the date, so the demo always lines up and
the evals can be re-run. Every name, UTR and amount is synthetic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

ENTITY = "Sunrise Bank"
ENTITY_IFSC = "SUNR0001"

BANKS = ["Northwind Bank", "Coastal Co-operative Bank", "Harbour Bank", "Meridian Bank", "Pinecrest Bank"]
MERCHANTS = ["ShopEasy", "TravelKart", "FreshCart", "QuickRide", "MediPlus"]
GATEWAYS = ["PaySwift", "TransitPay"]
CLUSTER_BANK = "Coastal Co-operative Bank"
CLUSTER_DAYS_AGO = 5
CLUSTER_HOURS = (18, 20)  # 18:00 to 19:59

# failure code -> (failure point, plain description)
CODES = {
    "BENE_CBS_TIMEOUT": ("Beneficiary bank", "beneficiary bank's core banking did not respond to the credit request"),
    "SWITCH_TIMEOUT": ("NPCI switch", "the NPCI switch timed out before the credit leg completed"),
    "GATEWAY_NO_CALLBACK": ("Gateway", "the payment gateway never sent the merchant confirmation"),
    "ACQUIRER_NOT_CONFIRMED": ("Acquiring bank", "the acquiring bank did not confirm the charge to the issuer"),
    "ATM_DISPENSE_FAULT": ("Acquiring bank", "the ATM reported a dispense fault and no cash was presented"),
    "REMITTER_CBS_ERROR": ("Remitter bank", "our own core banking debited twice after a retry"),
}

RAIL_FAILURE = {
    "UPI": "upi_transfer_not_credited",
    "UPI_MERCHANT": "upi_merchant_not_confirmed",
    "IMPS": "imps_not_credited",
    "CARD_TO_CARD": "card_to_card_not_credited",
    "CARD_POS": "card_pos_not_confirmed",
    "CARD_ONLINE": "card_online_not_confirmed",
    "ATM": "atm_cash_not_dispensed",
}
RAIL_TAT = {"UPI": 1, "IMPS": 1, "CARD_TO_CARD": 1, "UPI_MERCHANT": 5, "CARD_POS": 5, "CARD_ONLINE": 5, "ATM": 5}


@dataclass
class Txn:
    utr: str
    rail: str
    date: str
    time: str
    amount: float
    beneficiary: str
    gateway: str = ""
    status: str = "SUCCESS"  # SUCCESS | DEBITED_NOT_CREDITED | DEBITED_NOT_CONFIRMED | CASH_NOT_DISPENSED
    code: str = ""
    reversal_date: str | None = None
    compensation_paid: int = 0
    cluster: str | None = None
    payee_name: str = ""
    terminal: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status != "SUCCESS"

    @property
    def failure_point(self) -> str:
        return CODES[self.code][0] if self.code else "None"

    @property
    def failure_type(self) -> str:
        return RAIL_FAILURE[self.rail] if self.failed else "credited_successfully"


# The hero transactions behind the sample complaints. days_ago is relative to today.
HEROES: dict[str, dict] = {
    "A": dict(utr="612345678901", rail="UPI", days_ago=7, time="10:42", amount=4250.0,
              beneficiary="Northwind Bank", payee_name="R MEHTA", status="DEBITED_NOT_CREDITED",
              code="BENE_CBS_TIMEOUT"),
    "B": dict(utr="623456789012", rail="CARD_ONLINE", days_ago=9, time="21:14", amount=12800.0,
              beneficiary="TravelKart", gateway="PaySwift", status="DEBITED_NOT_CONFIRMED",
              code="GATEWAY_NO_CALLBACK"),
    "C1": dict(utr="634500000101", rail="UPI", days_ago=CLUSTER_DAYS_AGO, time="18:07", amount=1999.0,
               beneficiary=CLUSTER_BANK, payee_name="A KHAN", status="DEBITED_NOT_CREDITED",
               code="BENE_CBS_TIMEOUT", cluster="CLU-COASTAL"),
    "C2": dict(utr="634500000102", rail="UPI", days_ago=CLUSTER_DAYS_AGO, time="18:52", amount=7500.0,
               beneficiary=CLUSTER_BANK, payee_name="P NAIR", status="DEBITED_NOT_CREDITED",
               code="BENE_CBS_TIMEOUT", cluster="CLU-COASTAL"),
    "C3": dict(utr="634500000103", rail="UPI", days_ago=CLUSTER_DAYS_AGO, time="19:31", amount=350.0,
               beneficiary=CLUSTER_BANK, payee_name="S DAS", status="DEBITED_NOT_CREDITED",
               code="BENE_CBS_TIMEOUT", cluster="CLU-COASTAL"),
    "D": dict(utr="645678901234", rail="IMPS", days_ago=3, time="12:05", amount=25000.0,
              beneficiary="Harbour Bank", payee_name="K RAO", status="DEBITED_NOT_CREDITED",
              code="SWITCH_TIMEOUT"),
    "E": dict(utr="656789012345", rail="CARD_POS", days_ago=3, time="19:26", amount=3640.0,
              beneficiary="FreshCart", terminal="TID 40021877 (acquirer Meridian Bank)",
              status="DEBITED_NOT_CONFIRMED", code="ACQUIRER_NOT_CONFIRMED"),
    "F": dict(utr="667890123456", rail="ATM", days_ago=8, time="11:05", amount=10000.0,
              beneficiary="Harbour Bank ATM, MG Road", terminal="ATM ID HB-MGR-07 (acquirer Harbour Bank)",
              status="CASH_NOT_DISPENSED", code="ATM_DISPENSE_FAULT"),
    "G": dict(utr="678901234567", rail="UPI", days_ago=6, time="16:20", amount=6000.0,
              beneficiary="Pinecrest Bank", payee_name="S IYER", status="SUCCESS", code=""),
}


def _d(today: date, days_ago: int) -> str:
    return (today - timedelta(days=days_ago)).isoformat()


def _utr(rng: random.Random) -> str:
    return str(rng.randint(400_000_000_000, 599_999_999_999))


@lru_cache(maxsize=4)
def store(today: date | None = None) -> tuple[Txn, ...]:
    t = today or date.today()
    rng = random.Random(20261016)
    rails = (["UPI"] * 55 + ["UPI_MERCHANT"] * 20 + ["IMPS"] * 8 + ["CARD_POS"] * 7
             + ["CARD_ONLINE"] * 6 + ["ATM"] * 3 + ["CARD_TO_CARD"] * 1)
    out: list[Txn] = []
    for _ in range(4_900):
        rail = rng.choice(rails)
        days_ago = rng.randint(1, 30)
        hh, mm = rng.randint(6, 23), rng.randint(0, 59)
        merchant_like = rail in ("UPI_MERCHANT", "CARD_POS", "CARD_ONLINE")
        ben = rng.choice(MERCHANTS) if merchant_like else (
            f"{rng.choice(BANKS)} ATM" if rail == "ATM" else rng.choice(BANKS))
        x = Txn(utr=_utr(rng), rail=rail, date=_d(t, days_ago), time=f"{hh:02d}:{mm:02d}",
                amount=float(rng.choice([99, 250, 499, 1200, 2500, 4999, 8000, 15000])),
                beneficiary=ben, gateway=rng.choice(GATEWAYS) if rail == "CARD_ONLINE" else "")
        if rng.random() < 0.015:
            x.code = rng.choice({
                "UPI": ["BENE_CBS_TIMEOUT", "SWITCH_TIMEOUT", "REMITTER_CBS_ERROR"],
                "IMPS": ["BENE_CBS_TIMEOUT", "SWITCH_TIMEOUT"],
                "CARD_TO_CARD": ["BENE_CBS_TIMEOUT"],
                "UPI_MERCHANT": ["GATEWAY_NO_CALLBACK", "SWITCH_TIMEOUT"],
                "CARD_POS": ["ACQUIRER_NOT_CONFIRMED"],
                "CARD_ONLINE": ["GATEWAY_NO_CALLBACK"],
                "ATM": ["ATM_DISPENSE_FAULT"],
            }[rail])
            x.status = {"ATM": "CASH_NOT_DISPENSED", "CARD_POS": "DEBITED_NOT_CONFIRMED",
                        "CARD_ONLINE": "DEBITED_NOT_CONFIRMED",
                        "UPI_MERCHANT": "DEBITED_NOT_CONFIRMED"}.get(rail, "DEBITED_NOT_CREDITED")
            if rng.random() < 0.75:  # most failures reverse automatically inside the turnaround time
                x.reversal_date = _d(t, max(0, days_ago - rng.randint(0, RAIL_TAT[rail])))
        out.append(x)

    # Seeded outage cluster (Case C): Coastal Co-operative Bank's CBS stops answering for two hours.
    lo, hi = CLUSTER_HOURS
    for i in range(52):
        failed = i < 38
        out.append(Txn(
            utr=f"6345{i:08d}", rail="UPI", date=_d(t, CLUSTER_DAYS_AGO),
            time=f"{rng.randint(lo, hi - 1):02d}:{rng.randint(0, 59):02d}",
            amount=float(rng.choice([150, 499, 1200, 2500, 5000, 9999])), beneficiary=CLUSTER_BANK,
            status="DEBITED_NOT_CREDITED" if failed else "SUCCESS",
            code="BENE_CBS_TIMEOUT" if failed else "", cluster="CLU-COASTAL" if failed else None))

    for key, h in HEROES.items():
        spec = {k: v for k, v in h.items() if k != "days_ago"}
        out.append(Txn(date=_d(t, h["days_ago"]), tags=[f"hero:{key}"], **spec))
    return tuple(out)


def by_utr(utr: str | None, today: date | None = None) -> Txn | None:
    if not utr:
        return None
    return next((x for x in store(today) if x.utr == utr), None)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def detect_cluster(txn: Txn, today: date | None = None, window_min: int = 60,
                   min_failures: int = 10, min_rate: float = 0.2) -> dict | None:
    """Same beneficiary, same failure code, within +/- window_min of this transaction, at a failure
    rate far above that beneficiary's 30-day baseline. Returns the cluster or None."""
    if not txn.failed or not txn.code:
        return None
    rows = store(today)
    centre = _minutes(txn.time)
    near = [x for x in rows if x.beneficiary == txn.beneficiary and x.date == txn.date
            and abs(_minutes(x.time) - centre) <= window_min]
    failed = [x for x in near if x.failed and x.code == txn.code]
    if len(failed) < min_failures:
        return None
    rate = len(failed) / len(near)
    near_ids = {id(x) for x in near}
    others = [x for x in rows if x.beneficiary == txn.beneficiary and id(x) not in near_ids]
    base = sum(1 for x in others if x.failed) / max(1, len(others))
    if rate < min_rate or rate < 5 * base:
        return None
    times = sorted(_minutes(x.time) for x in failed)
    unreversed = [x for x in failed if not x.reversal_date]
    return {
        "cluster_id": f"CLU-{txn.beneficiary.split()[0].upper()}-{txn.date}",
        "beneficiary": txn.beneficiary,
        "code": txn.code,
        "date": txn.date,
        "window": f"{times[0] // 60:02d}:{times[0] % 60:02d}-{times[-1] // 60:02d}:{times[-1] % 60:02d}",
        "failed": len(failed),
        "in_window": len(near),
        "failure_rate": round(rate, 3),
        "baseline_rate": round(base, 4),
        "unreversed": len(unreversed),
        "utrs": [x.utr for x in failed],
        "likely_root_cause": f"{txn.beneficiary}: {CODES[txn.code][1]}",
    }


def all_clusters(today: date | None = None) -> list[dict]:
    """Scan every failed transaction once; one entry per distinct cluster (for Insights and evals)."""
    seen: dict[str, dict] = {}
    for x in store(today):
        if x.failed and x.utr not in {u for c in seen.values() for u in c["utrs"]}:
            c = detect_cluster(x, today)
            if c and c["cluster_id"] not in seen:
                seen[c["cluster_id"]] = c
    return list(seen.values())


def stats(today: date | None = None) -> dict:
    rows = store(today)
    failed = [x for x in rows if x.failed]
    return {"transactions": len(rows), "failed": len(failed),
            "unreversed": sum(1 for x in failed if not x.reversal_date),
            "days": 30, "entity": ENTITY}
