"""Deterministic rights maths. The LLM never does date or money arithmetic.

T is the transaction day. The RBI turnaround times are counted in calendar days (T+1, T+5), so
a UPI transfer made on the 2nd must be reversed by the 3rd, and each day after that costs Rs 100.
"""

from __future__ import annotations

from datetime import date, timedelta


def deadline(txn_day: date, tat_days: int) -> date:
    return txn_day + timedelta(days=tat_days)


def days_overdue(due: date, today: date) -> int:
    return max(0, (today - due).days)


def compensation(due: date, today: date, per_day: int) -> int:
    return days_overdue(due, today) * per_day


def arithmetic(due: date, today: date, per_day: int) -> str:
    """The sum the officer can check by hand, e.g. '6 days x Rs 100 = Rs 600'."""
    n = days_overdue(due, today)
    return f"{n} day{'s' if n != 1 else ''} x Rs {per_day} = Rs {n * per_day:,}"


def rbi_window(received: date, wait_days: int, file_within_days: int) -> tuple[date, date]:
    """From when the customer may approach the RBI Ombudsman, and the last day to file."""
    eligible = received + timedelta(days=wait_days)
    return eligible, eligible + timedelta(days=file_within_days)
