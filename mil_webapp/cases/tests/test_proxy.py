from unittest import mock

from django.test import Client, SimpleTestCase

from cases import agent_client


def _resp(status=200, content=b"{}", headers=None):
    return agent_client.AgentResponse(status, content, headers or {"content-type": "application/json"})


def _as_auditor(client: Client) -> Client:
    token = client.get("/officer/new").cookies.get("csrftoken")  # any page sets the cookie
    client.post("/role", {"role": "auditor"}, HTTP_X_CSRFTOKEN=token.value if token else "")
    return client


class ProxyTests(SimpleTestCase):
    @mock.patch("cases.agent_client.forward")
    def test_get_is_forwarded_with_path_query_and_actor(self, fwd):
        fwd.return_value = _resp(content=b'{"ok": 1}')
        r = Client().get("/api/cases/abc?x=1")
        self.assertEqual((r.status_code, r.content), (200, b'{"ok": 1}'))
        self.assertEqual(fwd.call_args.args, ("GET", "cases/abc"))
        self.assertEqual(fwd.call_args.kwargs["query"], "x=1")
        self.assertEqual(fwd.call_args.kwargs["headers"], {"x-mil-actor": "Priya Sharma", "x-mil-role": "officer"})

    @mock.patch("cases.agent_client.forward")
    def test_pdf_download_headers_survive(self, fwd):
        fwd.return_value = _resp(content=b"%PDF", headers={
            "content-type": "application/pdf", "content-disposition": "attachment; filename=e.pdf"})
        r = Client().get("/api/cases/abc/evidence.pdf")
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("e.pdf", r["Content-Disposition"])

    @mock.patch("cases.agent_client.forward")
    def test_agent_errors_are_passed_through(self, fwd):
        fwd.return_value = _resp(status=409, content=b'{"detail": "busy"}')
        self.assertEqual(Client().get("/api/cases/abc").status_code, 409)

    def test_post_without_csrf_token_is_rejected(self):
        r = Client(enforce_csrf_checks=True).post("/api/cases", data={"sample_id": "A"})
        self.assertEqual(r.status_code, 403)

    @mock.patch("cases.agent_client.forward")
    def test_post_with_csrf_token_is_forwarded(self, fwd):
        fwd.return_value = _resp()
        c = Client(enforce_csrf_checks=True)
        with mock.patch("cases.agent_client.get_json", side_effect=agent_client.AgentUnavailable("x")):
            token = c.get("/officer/queue").cookies["csrftoken"].value
        r = c.post("/api/cases/abc/approve", content_type="application/json", data='{"kind": "customer_reply"}',
                   HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fwd.call_args.args, ("POST", "cases/abc/approve"))

    @mock.patch("cases.agent_client.httpx.request")
    def test_multipart_upload_is_rebuilt_with_files_and_fields(self, req):
        from django.core.files.uploadedfile import SimpleUploadedFile

        req.return_value = mock.Mock(status_code=200, content=b"{}", headers={"content-type": "application/json"})
        r = Client().post("/api/cases/abc/documents", data={
            "note": "x", "files": SimpleUploadedFile("s.csv", b"a,b", content_type="text/csv")})
        self.assertEqual(r.status_code, 200)
        kw = req.call_args.kwargs
        self.assertEqual(kw["data"], {"note": ["x"]})
        self.assertEqual(kw["files"][0][1][0:2], ("s.csv", b"a,b"))
        self.assertEqual(kw["headers"]["x-mil-role"], "officer")

    @mock.patch("cases.agent_client.forward", side_effect=agent_client.AgentUnavailable("down"))
    def test_friendly_error_when_agent_service_is_down(self, _):
        r = Client().get("/api/cases/abc")
        self.assertEqual(r.status_code, 502)
        self.assertIn("not switched on", r.json()["detail"])

    def test_unsupported_method_is_405(self):
        self.assertEqual(Client().delete("/api/cases/abc").status_code, 405)

    @mock.patch("cases.agent_client.forward")
    def test_auditors_cannot_write_through_the_proxy(self, fwd):
        fwd.return_value = _resp()
        c = Client()
        with mock.patch("cases.agent_client.get_json", side_effect=agent_client.AgentUnavailable("x")):
            _as_auditor(c)
        r = c.post("/api/cases/abc/approve", content_type="application/json", data="{}")
        self.assertEqual(r.status_code, 403)
        fwd.assert_not_called()
        c.get("/api/cases/abc")
        self.assertEqual(fwd.call_args.kwargs["headers"]["x-mil-role"], "auditor")
