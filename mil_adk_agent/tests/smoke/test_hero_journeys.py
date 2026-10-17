"""End-to-end journeys through the HTTP API and the real ADK runtime (offline model):
the project file's hero cases, from intake to closure."""

import io
import json
import time
import zipfile

from fastapi.testclient import TestClient

from mil_agent.main import app


def _wait(client, cid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        c = client.get(f"/api/cases/{cid}").json()
        if not c["running"]:
            return c
        time.sleep(0.1)
    raise AssertionError("agent run did not finish")


def _start(client, sample):
    return _wait(client, client.post("/api/cases", data={"sample_id": sample}).json()["id"])


def _approve(client, c, kind):
    for item in ("timeline", "amounts", "text"):
        client.put(f"/api/cases/{c['id']}/checklist", json={"item": item, "checked": True})
    r = client.post(f"/api/cases/{c['id']}/approve", json={"kind": kind})
    assert r.status_code == 200, r.text
    return _wait(client, c["id"])


def test_case_a_from_upload_to_closure():
    with TestClient(app) as client:
        files = [("files", (n, t, "text/plain")) for n, t in _sample_files("A").items()]
        c = client.post("/api/cases", files=files, data={"customer_ref": "CUST-88213", "customer_name": "Asha Verma"})
        c = _wait(client, c.json()["id"])
        assert c["error"] is None and c["state"] == "complaint_ready" and c["status"] == "Overdue"
        assert c["rights"]["compensation_inr"] == 600 and c["diagnosis"]["failure_point"] == "Beneficiary bank"
        assert len({a["trace_id"] for a in c["audit"]}) == 1  # one trace id per case
        assert client.get(f"/api/cases/{c['id']}/evidence.pdf").status_code == 200

        c = _approve(client, c, "customer_reply")
        assert c["state"] == "awaiting_party" and "customer_reply" in c["sent"]

        client.post(f"/api/cases/{c['id']}/simulate", json={"event": "reversal_posted"})
        c = _wait(client, c["id"])
        assert c["state"] == "resolved"
        c = client.post(f"/api/cases/{c['id']}/close").json()
        assert c["state"] == "closed" and c["status"] == "Closed"

        z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/cases/{c['id']}/export.zip").content))
        manifest = json.loads(z.read("MANIFEST.json"))
        assert "evidence.pdf" in manifest["files"] and manifest["synthetic"] is True


def test_case_b_asks_for_a_document_then_diagnoses():
    with TestClient(app) as client:
        c = _start(client, "B")
        assert c["status"] == "Awaiting customer" and c["awaiting_documents"]
        client.post(f"/api/cases/{c['id']}/request-documents", json={"document": c["awaiting_documents"][0]})
        client.post(f"/api/cases/{c['id']}/documents/practice")
        c = _wait(client, c["id"])
        assert c["state"] == "complaint_ready" and c["diagnosis"]["failure_point"] == "Gateway"
        assert c["rights"]["rule_verified"] is False  # card-online row still to verify


def test_case_c_cluster_is_visible_across_cases():
    with TestClient(app) as client:
        for s in ("C1", "C2", "C3"):
            assert _start(client, s)["diagnosis"]["cluster_id"].startswith("CLU-COASTAL")
        cluster = client.get("/api/insights").json()["clusters"][0]
        assert len(cluster["cases"]) >= 3 and cluster["affected_without_complaint"] > 30


def test_rejection_goes_through_the_internal_ombudsman():
    with TestClient(app) as client:
        c = _start(client, "G")
        assert c["approval"]["kind"] == "internal_ombudsman" and c["referral_required"]
        c = _approve(client, c, "internal_ombudsman")
        assert c["state"] == "escalated"
        client.post(f"/api/cases/{c['id']}/simulate", json={"event": "io_decision"})
        c = _wait(client, c["id"])
        assert c["approval"]["kind"] == "customer_reply" and "IO-DEC-" in c["drafts"]["customer_reply"]["text"]
        c = _approve(client, c, "customer_reply")
        assert c["state"] == "awaiting_party" and set(c["sent"]) == {"internal_ombudsman", "customer_reply"}


def test_rbi_complaint_and_officer_override():
    with TestClient(app) as client:
        c = _start(client, "D")
        client.post(f"/api/cases/{c['id']}/override",
                        json={"failure_point": "Beneficiary bank", "reason": "Ops confirmed Harbour Bank CBS was down"})
        c = _wait(client, c["id"])
        assert c["diagnosis"]["effective_point"] == "Beneficiary bank" and "Harbour Bank" in \
            c["drafts"]["customer_reply"]["text"]
        c = _approve(client, c, "customer_reply")
        client.post(f"/api/cases/{c['id']}/simulate", json={"event": "rbi_complaint"})
        c = _wait(client, c["id"])
        assert c["state"] == "escalated" and c["approval"]["kind"] == "rbi_ombudsman"
        assert {d["action"] for d in client.get("/api/audit/decisions").json()} >= {"override", "approved"}


def test_officer_question_is_answered_from_facts():
    with TestClient(app) as client:
        c = _start(client, "A")
        c = client.post(f"/api/cases/{c['id']}/chat", json={"message": "How much compensation is owed?"}).json()
        assert "Rs 600" in c["chat"][-1]["text"]


def _sample_files(sid):
    from mil_agent.data import samples

    return samples.sample_files(sid)
