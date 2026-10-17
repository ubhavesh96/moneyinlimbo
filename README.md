# Money in Limbo

Every failed-payment complaint, investigated end to end, before it reaches the ombudsman.

An AI investigation agent for the grievance and compliance teams of banks, NBFCs and wallet issuers. For each failed-payment complaint it reconstructs the payment trail from the customer's documents and the bank's own records, diagnoses the failure point, checks RBI turnaround, compensation and Internal Ombudsman referral rules, and drafts a cited, regulator-ready reply that a grievance officer approves.

> **Local prototype.** Everything runs on localhost. The bank, gateway, Internal Ombudsman and RBI portal are simulated, every customer and UTR is synthetic, and the rule table must be verified against the current RBI circulars before any real use. This is not legal advice.

---

## Who uses it

| Persona | In the app |
|---|---|
| Grievance redressal officer (primary user) | Queue sorted by turnaround urgency, three-pane case workbench, approval gate |
| Internal auditor (oversight) | Read-only audit explorer, case replay with tool inputs and outputs, decision log, rule library, live evals, evidence exports |
| Customer (beneficiary) | Never talks to the agent. Receives the reply the officer approved |

## How a case flows

1. **Reconstruct.** The officer opens a complaint and uploads the customer's documents. The agent pulls the bank's records for the UTR/RRN (switch, core banking, card or ATM logs) through the `BankConnector` and builds one timeline in which every event cites its source line.
2. **Diagnose.** It proposes the failure point with a confidence and cited reasons, checks declared incidents, and scans ~5,000 transactions for an outage cluster. If the evidence is thin, it asks for a specific document instead of guessing.
3. **Check.** Code, not the model, computes the deadline (T+1 or T+5 calendar days), days overdue and compensation (Rs 100 per day). It also checks whether a proposed rejection must go to the Internal Ombudsman first.
4. **Draft.** It drafts a footnoted reply to the customer and a regulator-ready evidence PDF.
5. **Approve.** The officer confirms three checks (timeline, amounts, text) and approves. Only then does the Case Tracker send. It then watches the clocks and drafts the RBI Ombudsman response if the customer escalates.

Case states (only the Case Tracker moves them): `intake → reconstructed → diagnosed → rights_computed → complaint_ready → awaiting_party → escalated → resolved → closed`.

---

## Architecture

```
Browser
  │
  ▼
mil_webapp  (Django, :8000)     server-rendered officer and auditor pages; /api proxy with CSRF,
  │                             acting person stamped on every call, auditors read-only
  ▼
mil_adk_agent  (FastAPI, :8001)
  └─ investigation_orchestrator  (Google ADK root agent, follows get_case → RouteDecision)
       ├─ timeline_reconstructor   parse_document, normalize_events (+ BankConnector)
       ├─ failure_diagnoser        lookup_known_outages, predict_failure_point
       ├─ policy_rights            search_policies, compute_deadline, compute_compensation
       ├─ escalation               select_ombudsman_route, draft_escalation
       ├─ evidence_complaint       choose_recipient, build_evidence_pdf, draft_complaint
       └─ case_tracker             on_event, check_sla, schedule_followup
```

Design rules (project file p.16):
- **Code for numbers.** Deadlines and compensation come from `tools/policy_package/rules.py`. The model only chooses which tool to call.
- **Typed outputs.** `Timeline`, `FailureDiagnosis`, `RightsCard`, `ComplaintDraft`, `EscalationDraft`, `CaseUpdate` and `RouteDecision` forbid extra fields. Each tool output is validated and the result is recorded in the audit trail.
- **Human approval.** It is enforced three times: the API needs all three checks, an ADK `before_tool_callback` blocks the send, and `on_event` refuses anything not approved.
- **Audit trail.** Every case has one trace ID. Every tool call (inputs and outputs), state move and officer decision is stored.

### Folder structure

```
money_in_limbo/
├── mil_adk_agent/
│   ├── mil_agent/
│   │   ├── agents/        config.py, subagents.py, routers.py (root agent), scripted_llm.py, fallback_llm.py
│   │   ├── prompts/       templates/agents/*.jinja2 (one per agent + shared rules)
│   │   ├── tools/         timeline.py, diagnosis.py, policy.py, evidence.py, tracker.py, escalation.py
│   │   │   └── *_package/ parsing + bank_connector, classifier, rules, pdfgen, state_machine + simulators
│   │   ├── callbacks/     approval_guard.py
│   │   ├── services/      case_service.py, session_service.py, seed_service.py, eval_service.py
│   │   ├── api/           cases.py, audit.py, samples.py, dependencies.py
│   │   ├── data/          policies.json, outages.json, synthetic.py, samples.py
│   │   └── main.py  agent.py  models.py  settings.py  logging.py
│   ├── tests/             unit/ (one file per agent, tools, API, callbacks, services) and smoke/ (hero journeys)
│   └── scripts/           run-agent.ps1, run-unit-tests.ps1
├── mil_webapp/
│   ├── mil_project/       settings, urls, wsgi/asgi
│   ├── cases/             views.py, urls.py, agent_client.py, templatetags/mil.py, tests/ (+ fixtures)
│   ├── templates/         base.html, officer/, auditor/
│   ├── static/            css/app.css, js/app.js, js/queue.js, js/workbench.js
│   └── scripts/           run-webapp.ps1
└── run-all.ps1
```

### Cloud design and the local stand-ins

| Cloud design (GCP) | Local prototype |
|---|---|
| API gateway and auth on Cloud Run | Django proxy with a demo role cookie (no real sign-in) |
| Agent layer: ADK on Cloud Run | `mil_adk_agent` (ADK 1.28.1) |
| Gemini on Vertex AI | Gemini via an API key, with an offline fallback model |
| Document AI | `tools/timeline_package/parsing.py` (CSV, TXT, PDF text) |
| BankConnector to core banking, switch and gateway | `MockBankConnector` over `data/synthetic.py` |
| Vertex AI failure classifier | `tools/diagnosis_package/classifier.py` (rule-based, cites evidence) |
| BigQuery (transactions, outage clusters) | ~5,000 synthetic transactions plus cluster detection in `data/synthetic.py` |
| Vertex AI Search (RBI circulars) | `data/policies.json` and keyword search |
| Cloud SQL | one JSON file per case in `runtime/<case_id>/` |
| Cloud Storage | evidence PDF on disk |
| Pub/Sub and Cloud Scheduler | in-process event list and the practice clock |
| Cloud Trace | one `trace_id` per case in the audit trail |

---

## Setup

Requires [uv](https://docs.astral.sh/uv/). If you only have another Python, `python -m pip install --user uv` works too. uv downloads Python 3.12 if needed. Each service has its own virtual environment. Do not copy a `.venv` between machines.

```powershell
cd mil_adk_agent
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e . pytest pytest-asyncio httpx ruff
copy .env.sample .env        # optional: add a Gemini key

cd ..\mil_webapp
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe "django>=5.1,<6" httpx
```

## Run

```powershell
.\run-all.ps1          # agent on :8001, web app on :8000, then opens the browser
```

Or use two terminals:

```powershell
cd mil_adk_agent; .\.venv\Scripts\python.exe -m uvicorn mil_agent.main:app --host 127.0.0.1 --port 8001
cd mil_webapp;    .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Open **http://127.0.0.1:8000**. On first start the agent service seeds a demo queue of nine complaints. This uses the deterministic tool pipeline and no Gemini quota. **Reset demo queue** at the bottom of the queue reseeds it.

## Gemini (optional)

`mil_adk_agent\.env`:

```
GOOGLE_API_KEY=your-key
GOOGLE_GENAI_USE_VERTEXAI=FALSE
LLM_MODEL=gemini-3-flash-preview
```

With a key, Gemini routes the case, runs the specialists and answers officer questions. Without one, the same ADK agents and tools run with a scripted model. If Gemini fails (quota, outage, network), the app switches to the scripted model for 15 minutes and the header badge says so. One full investigation uses roughly 20 to 30 Gemini requests, so free-tier keys run out quickly.

---

## Three-minute demo (project file p.18)

| Time | Step | In the app |
|---|---|---|
| 0:20 | Case A intake | **New complaint**, download *Case A* documents and upload them (or open MIL-24001 and press **Run investigation**) |
| 0:45 | Investigation | Timeline with sources, diagnosis (beneficiary bank, cited reasons), rights card: **T+1 breached by 6 days = Rs 600** |
| 1:35 | Approval gate | Edit the reply, tick the three checks, **Approve and send**. Then **Payments ops posts the credit** → resolved |
| 2:05 | Case C cluster | **Insights**: Coastal Co-operative Bank outage, its open complaints, and the customers who have not complained yet |
| 2:40 | Audit and evals | Switch to **Ravi Kumar (Auditor)**: case replay with tool inputs and outputs, decision log, **Model status** (live evals) |

Other cases in the queue:

| Case | Shows |
|---|---|
| B: card online, merchant never confirmed | the agent asks for the merchant's record (**Customer sent it (practice)**), then diagnoses a gateway failure. The card-online rule is flagged *pending verification* |
| D: IMPS switch timeout | officer **Override** of the failure point, with the reply redrafted |
| E: card at PoS | still inside T+5, so no compensation is due yet |
| F: ATM, already approved | tracking: **Skip 2 days** misses the follow-up and escalates; **Customer files with RBI Ombudsman** drafts the RBI response |
| G: payee was credited | proposed rejection: **Internal Ombudsman referral** first, then the reply unlocks after **Internal Ombudsman concurs** |

## Test

```powershell
cd mil_adk_agent; .\.venv\Scripts\python.exe -m pytest -q          # 98 tests, offline, never use Gemini
cd mil_webapp;    .\.venv\Scripts\python.exe manage.py test cases   # 27 tests, pages rendered against real API fixtures
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "The agent service is not switched on" | Start `mil_adk_agent` on port 8001 |
| `uv trampoline failed to spawn Python` | The `.venv` was copied from another machine. Delete it and recreate it (Setup) |
| Port already in use | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Where-Object { $_.CommandLine -like '*uvicorn*' -or $_.CommandLine -like '*runserver*' } \| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }` |
| Badge says "Offline helper (…)" | Gemini failed, usually the free quota. It retries after 15 minutes |
| Screenshot upload refused | Document AI OCR is not part of the prototype. Paste the text into a `.txt` file |

## Limitations (be honest on stage)

- **Synthetic everything.** Customers, transactions, bank logs, the outage cluster and all replies are synthetic. Diagnosis accuracy and cluster precision and recall are measured on data generated by the same team, so they prove the pipeline, not real-world accuracy.
- **Rules to verify.** The table follows RBI/2019-20/67 as transcribed in the project file. The card-online (CNP) and ATM rows, and the 90-day RBI filing window, are flagged for verification.
- **Not built yet.** ADK evalsets, rubric and hallucination checks, and practitioner review (evaluation layers 2 to 4) are not run. There are no live connectors (F13), no customer-facing status updates (F14), no real sign-in, and one officer per demo.
- **State.** ADK sessions live in memory; cases persist on disk under `runtime/`.
