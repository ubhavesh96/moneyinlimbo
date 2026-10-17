import time

import pytest
from fastapi.testclient import TestClient

from mil_agent.main import app
from mil_agent.services import seed_service

AUDITOR = {"x-mil-role": "auditor", "x-mil-actor": "Ravi Kumar"}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _wait(client, cid):
    for _ in range(100):
        c = client.get(f"/api/cases/{cid}").json()
        if not c["running"]:
            return c
        time.sleep(0.1)
    raise AssertionError("agent run did not finish")


def test_health_and_mode(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/mode").json()["live_llm"] is False


def test_unknown_case_is_404(client):
    assert client.get("/api/cases/nope").status_code == 404


def test_create_requires_documents(client):
    assert client.post("/api/cases", data={}).status_code == 400


def test_unknown_sample_is_404(client):
    assert client.post("/api/cases", data={"sample_id": "zzz"}).status_code == 404


def test_screenshot_upload_is_refused_politely(client):
    r = client.post("/api/cases", files=[("files", ("slip.jpg", b"x", "image/jpeg"))])
    assert r.status_code == 400 and "Document AI" in r.json()["detail"]


def test_sample_list_hides_labels_and_downloads(client):
    samples = client.get("/api/samples").json()
    assert len(samples) == 9 and all("label" not in s for s in samples)
    r = client.get("/api/samples/B/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"


def test_seeded_queue_is_sorted_by_urgency(client):
    seed_service.seed_demo(force=True)
    rows = client.get("/api/cases").json()
    statuses = [r["status"] for r in rows]
    assert statuses.index("Overdue") < statuses.index("New")
    assert any(r["cluster_id"] for r in rows) and any(r["referral_required"] for r in rows)


def test_approval_needs_all_three_checks(client):
    cid = _wait(client, client.post("/api/cases", data={"sample_id": "A"}).json()["id"])["id"]
    r = client.post(f"/api/cases/{cid}/approve", json={"kind": "customer_reply"})
    assert r.status_code == 400 and "three checks" in r.json()["detail"]


def test_auditors_cannot_change_cases(client):
    cid = _wait(client, client.post("/api/cases", data={"sample_id": "A"}).json()["id"])["id"]
    assert client.post(f"/api/cases/{cid}/approve", json={"kind": "customer_reply"}, headers=AUDITOR).status_code == 403
    assert client.get(f"/api/cases/{cid}", headers=AUDITOR).status_code == 200
    assert client.get(f"/api/cases/{cid}/export.zip", headers=AUDITOR).status_code == 200


def test_reject_needs_a_reason_and_is_logged(client):
    cid = _wait(client, client.post("/api/cases", data={"sample_id": "A"}).json()["id"])["id"]
    assert client.post(f"/api/cases/{cid}/reject", json={"kind": "customer_reply", "reason": "no"}).status_code == 422
    c = client.post(f"/api/cases/{cid}/reject",
                    json={"kind": "customer_reply", "reason": "Wrong beneficiary bank named"}).json()
    assert c["approval"]["status"] == "rejected" and c["decisions"][-1]["action"] == "rejected_draft"


def test_editing_the_draft_resets_the_text_check(client):
    cid = _wait(client, client.post("/api/cases", data={"sample_id": "A"}).json()["id"])["id"]
    client.put(f"/api/cases/{cid}/checklist", json={"item": "text", "checked": True})
    c = client.get(f"/api/cases/{cid}").json()
    text = c["drafts"]["customer_reply"]["text"] + "\nPS: we apologise for the delay."
    c = client.put(f"/api/cases/{cid}/draft", json={"kind": "customer_reply", "text": text}).json()
    assert c["approval"]["checklist"]["text"] is False and c["drafts"]["customer_reply"]["edited_by_officer"]


def test_practice_events_only_when_they_apply(client):
    cid = _wait(client, client.post("/api/cases", data={"sample_id": "A"}).json()["id"])["id"]
    assert client.post(f"/api/cases/{cid}/simulate", json={"event": "reversal_posted"}).status_code == 400


def test_oversight_endpoints(client):
    _wait(client, client.post("/api/cases", data={"sample_id": "C1"}).json()["id"])
    assert client.get("/api/rules").json()["rules"]
    ins = client.get("/api/insights").json()
    assert ins["clusters"] and ins["clusters"][0]["affected_without_complaint"] > 0
    assert isinstance(client.get("/api/audit/decisions").json(), list)
