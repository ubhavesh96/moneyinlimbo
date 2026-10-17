from datetime import date

from mil_agent.tools.policy_package import rules


def test_turnaround_counts_calendar_days():
    assert rules.deadline(date(2026, 10, 9), 1) == date(2026, 10, 10)  # Fri -> Sat: no weekend skip
    assert rules.deadline(date(2026, 10, 1), 5) == date(2026, 10, 6)


def test_project_file_case_a_six_days_is_600():
    due = rules.deadline(date(2026, 10, 2), 1)
    assert rules.days_overdue(due, date(2026, 10, 9)) == 6
    assert rules.compensation(due, date(2026, 10, 9), 100) == 600
    assert rules.arithmetic(due, date(2026, 10, 9), 100) == "6 days x Rs 100 = Rs 600"


def test_no_compensation_on_or_before_deadline():
    assert rules.compensation(date(2026, 10, 12), date(2026, 10, 12), 100) == 0
    assert rules.compensation(date(2026, 10, 12), date(2026, 10, 1), 100) == 0
    assert rules.arithmetic(date(2026, 10, 12), date(2026, 10, 13), 100) == "1 day x Rs 100 = Rs 100"


def test_rbi_window_is_30_then_90_days():
    eligible, last = rules.rbi_window(date(2026, 10, 1), 30, 90)
    assert (eligible, last) == (date(2026, 10, 31), date(2027, 1, 29))
