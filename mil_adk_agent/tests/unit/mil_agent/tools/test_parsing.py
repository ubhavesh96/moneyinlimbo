import pytest

from mil_agent.models import Document, TimelineEvent
from mil_agent.tools.timeline_package import bank_connector, parsing


def _e(**kw):
    return TimelineEvent(id="", **kw)


def test_dates_in_indian_formats():
    assert parsing.find_dates("on 12-10-2026 and 3 Oct 2026 and 2026-09-01") == [
        "2026-10-12", "2026-10-03", "2026-09-01"]


def test_amount_utr_and_failure_codes():
    assert parsing.find_amount("debited Rs. 2,499.00 today") == 2499.0
    assert parsing.find_utr("UTR 412345678901 done") == "412345678901"
    assert parsing.find_utr("no reference here") is None
    assert parsing.find_codes("RESULT=TIMEOUT (BENE_CBS_TIMEOUT) PAYEE_TYPE=PERSON") == ["BENE_CBS_TIMEOUT"]


def test_statement_rows_keep_their_source_line():
    doc = Document(id="doc-1", name="s.csv", kind="statement", text=(
        "# Bank: Test Bank\nDate,Narration,Debit,Credit,Balance\n"
        "2026-10-01,UPI/P2P/111122223333/A B/X BANK,500,,900\n2026-10-02,REVERSAL UPI,,500,1400\n"))
    ev = parsing.events_from_document(doc)
    assert [e.kind for e in ev] == ["debit", "reversal"]
    assert ev[0].ref == "111122223333" and ev[0].doc_id == "doc-1" and "UPI/P2P" in ev[0].snippet


def test_bank_logs_become_cited_events():
    logs = bank_connector.MockBankConnector().records("612345678901")  # hero Case A
    assert set(logs) == {"remitter_cbs_612345678901.log", "npci_switch_612345678901.log",
                         "beneficiary_status_612345678901.log"}
    doc = Document(id="doc-9", name="npci.log", kind="bank_log", origin="bank_connector",
                   text=logs["npci_switch_612345678901.log"])
    assert parsing.detect_kind(doc.name, doc.text) == "bank_log"
    events = parsing.events_from_document(doc)
    assert "credit_failed" in [e.kind for e in events]
    assert all(e.source == "NPCI switch" and e.doc_id == "doc-9" for e in events)


def test_bank_records_line_up_with_the_day_the_case_was_opened():
    """A case seeded yesterday and investigated today must get logs dated relative to yesterday."""
    from datetime import date

    logs = bank_connector.MockBankConnector().records("612345678901", as_of=date(2026, 1, 10))
    assert logs["remitter_cbs_612345678901.log"].splitlines()[1].startswith("2026-01-03")  # Case A is T-7


def test_unknown_reference_returns_no_bank_records():
    assert bank_connector.MockBankConnector().records("000000000000") == {}


def test_rail_from_statement_narration():
    assert parsing.rail_from_narration("UPI/P2M/1/SHOP") == "UPI_MERCHANT"
    assert parsing.rail_from_narration("ECOM/TRAVELKART/PAYSWIFT/1") == "CARD_ONLINE"
    assert parsing.rail_from_narration("ATM WDL/X/1") == "ATM"


def test_screenshots_are_refused_with_a_helpful_message():
    with pytest.raises(ValueError, match=".txt"):
        parsing.extract_text("slip.jpg", b"x")


def test_focus_keeps_only_the_disputed_transaction():
    ev = [_e(date="2026-10-01", source="Bank statement", kind="credit", text="salary", amount_inr=50000),
          _e(date="2026-10-02", source="Bank statement", kind="debit", text="shop", amount_inr=999,
             ref="123456789012"),
          _e(date="2026-10-02", source="SMS", kind="debit_sms", text="sms", amount_inr=999, ref="123456789012")]
    assert {e.text for e in parsing.focus(ev, "123456789012", 999)} == {"shop", "sms"}
