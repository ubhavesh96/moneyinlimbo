"""Server-rendered pages, rendered against real agent-service responses captured in fixtures/."""

import json
from pathlib import Path
from unittest import mock

from django.test import Client, SimpleTestCase

from cases import agent_client
from cases.templatetags import mil

FIX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def fake_get_json(path, headers=None, query=""):
    routes = {"mode": "mode.json", "cases": "rows.json", "insights": "insights.json", "audit/evals": "evals.json",
              "audit/decisions": "decisions.json", "rules": "rules.json", "samples": "samples.json"}
    if path in routes:
        return fx(routes[path])
    if path.startswith("cases/"):
        cid = path.split("/")[1]
        for name in ("case_ready.json", "case_sent.json", "case_intake.json"):
            c = fx(name)
            if c["id"] == cid:
                return c
        raise agent_client.AgentError(404, "Case not found")
    raise AssertionError(f"unexpected path {path}")


@mock.patch("cases.agent_client.get_json", side_effect=fake_get_json)
class OfficerPageTests(SimpleTestCase):
    def test_home_redirects_to_the_officer_queue(self, _):
        r = Client().get("/")
        self.assertRedirects(r, "/officer/queue", fetch_redirect_response=False)

    def test_queue_lists_cases_by_urgency_with_kpis(self, _):
        r = Client().get("/officer/queue")
        self.assertContains(r, "My queue")
        self.assertContains(r, "Outage cluster")
        self.assertContains(r, "Turnaround already breached")
        self.assertContains(r, "/static/js/queue.js")
        self.assertIn("csrftoken", r.cookies)

    def test_workbench_shows_the_three_panes_and_the_gate(self, _):
        case = fx("case_ready.json")
        r = Client().get(f"/officer/cases/{case['id']}")
        self.assertContains(r, case["ref"])
        self.assertContains(r, "Event timeline")
        self.assertContains(r, "Diagnosis and failure point")
        self.assertContains(r, "6 days x Rs 100 = Rs 600")
        self.assertContains(r, "Calculated by the rules engine, not by AI")
        self.assertContains(r, "Human approval gate")
        self.assertContains(r, 'data-check="amounts"')
        self.assertContains(r, "Nothing is sent to the customer")

    def test_sent_case_shows_tracking_and_practice_controls(self, _):
        case = fx("case_sent.json")
        r = Client().get(f"/officer/cases/{case['id']}")
        self.assertContains(r, "Payments ops posts the credit")
        self.assertContains(r, "Sent:")

    def test_new_case_starts_investigation(self, _):
        case = fx("case_intake.json")
        r = Client().get(f"/officer/cases/{case['id']}")
        self.assertContains(r, "Run investigation")

    def test_unknown_case_is_a_friendly_404(self, _):
        r = Client().get("/officer/cases/nope")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Case not found", status_code=404)

    def test_new_complaint_form_and_samples(self, _):
        r = Client().get("/officer/new")
        self.assertContains(r, "Upload the customer")
        self.assertContains(r, "Case A")

    @mock.patch("cases.agent_client.forward")
    def test_opening_a_sample_redirects_to_its_workbench(self, fwd, _):
        fwd.return_value = agent_client.AgentResponse(200, b'{"id": "abc123"}', {"content-type": "application/json"})
        r = Client().post("/officer/new", {"sample_id": "A"})
        self.assertRedirects(r, "/officer/cases/abc123", fetch_redirect_response=False)
        self.assertEqual(fwd.call_args.kwargs["form"], {"sample_id": ["A"]})

    def test_insights_show_the_outage_cluster(self, _):
        r = Client().get("/officer/insights")
        self.assertContains(r, "Outage clusters")
        self.assertContains(r, "Affected customers who have not complained")

    def test_officer_cannot_open_auditor_pages(self, _):
        self.assertRedirects(Client().get("/auditor/explorer"), "/officer/queue", fetch_redirect_response=False)


@mock.patch("cases.agent_client.get_json", side_effect=fake_get_json)
class AuditorPageTests(SimpleTestCase):
    def setUp(self):
        self.c = Client()
        with mock.patch("cases.agent_client.get_json", side_effect=fake_get_json):
            self.c.post("/role", {"role": "auditor"})

    def test_role_switch_lands_on_the_explorer(self, _):
        r = self.c.get("/")
        self.assertRedirects(r, "/auditor/explorer", fetch_redirect_response=False)
        r = self.c.get("/auditor/explorer")
        self.assertContains(r, "Auditors cannot change cases")
        self.assertNotContains(r, "Approve and send")

    def test_replay_shows_trace_states_and_diff(self, _):
        case = fx("case_sent.json")
        r = self.c.get(f"/auditor/replay/{case['id']}")
        self.assertContains(r, case["trace_id"])
        self.assertContains(r, "State history")
        self.assertContains(r, "Tool inputs")
        self.assertContains(r, "AI draft vs text sent")

    def test_decision_log_rules_models_exports(self, _):
        self.assertContains(self.c.get("/auditor/decisions"), "Decision log")
        self.assertContains(self.c.get("/auditor/rules"), "RBI-TAT-UPI-01")
        r = self.c.get("/auditor/models")
        self.assertContains(r, "Failure-point diagnosis matches the label")
        self.assertContains(r, "Messages sent without approval")
        self.assertContains(self.c.get("/auditor/exports"), "MANIFEST.json")

    def test_auditor_is_kept_out_of_officer_pages(self, _):
        self.assertRedirects(self.c.get("/officer/queue"), "/auditor/explorer", fetch_redirect_response=False)


class OfflineTests(SimpleTestCase):
    @mock.patch("cases.agent_client.get_json", side_effect=agent_client.AgentUnavailable("down"))
    def test_pages_explain_how_to_start_the_agent_service(self, _):
        r = Client().get("/officer/queue")
        self.assertEqual(r.status_code, 502)
        self.assertContains(r, "not switched on", status_code=502)


class FilterTests(SimpleTestCase):
    def test_indian_rupees(self):
        self.assertEqual(mil.inr(4250), "₹4,250")
        self.assertEqual(mil.inr(125000), "₹1,25,000")
        self.assertEqual(mil.inr(None), "—")

    def test_word_diff_marks_changes_and_escapes(self):
        html = mil.worddiff("pay Rs 600 now", "pay Rs 700 <b>now</b>")
        self.assertIn("<del>600</del>", html)
        self.assertIn("<ins>700</ins>", html)
        self.assertIn("&lt;b&gt;", html)

    def test_citations_become_links(self):
        self.assertIn('href="#cite-2"', mil.cited("see [2]"))
