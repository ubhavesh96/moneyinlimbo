# mil_webapp

Django console for the grievance desk. Pages are server-rendered from the agent service's API
(`AGENT_SERVICE_URL`, default http://127.0.0.1:8001); small vanilla JS files handle the actions.
`/api/*` is proxied with CSRF checks, the acting person is stamped on every call, and auditors are
read-only (blocked here and again in the agent service).

| Role | Pages |
|---|---|
| Grievance officer (Priya Sharma) | My queue, Drafts awaiting approval, New complaint, Case workbench, Insights |
| Internal auditor (Ravi Kumar) | Audit explorer, Case replay, Decision log, Rule library, Model status, Evidence exports |

Switch roles from the header. There is no real sign-in in this prototype: a signed cookie holds the
demo role. No database is used; the agent service owns all case data.

```
scripts\run-webapp.ps1        # http://127.0.0.1:8000
.venv\Scripts\python.exe manage.py test cases
```

Templates: `templates/` (`officer/`, `auditor/`), filters in `cases/templatetags/mil.py`, styles in
`static/css/app.css` (design tokens from the approved prototype), scripts in `static/js/`.
Page tests render against real API responses saved in `cases/tests/fixtures/`.
