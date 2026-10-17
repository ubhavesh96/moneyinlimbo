# mil_adk_agent

ADK service: root `investigation_orchestrator` delegating to six specialist agents via `AgentTool`.
The orchestrator follows the `RouteDecision` returned by `get_case`; the Case Tracker is the only
agent that moves a case between states (`tools/tracker_package/state_machine.py`).

```
scripts\run-agent.ps1        # http://127.0.0.1:8001  (docs at /docs)
scripts\run-unit-tests.ps1
```

| Agent | Tools | Typed output |
|---|---|---|
| Orchestrator | `get_case` + the six specialists | `RouteDecision` |
| Timeline Reconstructor | `parse_document`, `normalize_events` | `Timeline` |
| Failure Diagnoser | `lookup_known_outages`, `predict_failure_point` | `FailureDiagnosis` |
| Policy and Rights | `search_policies`, `compute_deadline`, `compute_compensation` | `RightsCard` |
| Evidence and Complaint | `choose_recipient`, `build_evidence_pdf`, `draft_complaint`, `revise_complaint` | `ComplaintDraft` |
| Case Tracker | `on_event`, `check_sla`, `schedule_followup` | `CaseUpdate` |
| Escalation | `select_ombudsman_route`, `draft_escalation` | `EscalationDraft` |

Typed outputs are validated at the tool boundary (`tools/common.done`) and the result is stored on
each audit entry (`_contract`). Some ADK versions disallow `output_schema` together with tools, so
the contract is enforced in code rather than with `output_schema`.

Synthetic data: `data/synthetic.py` (about 5,000 transactions, a seeded outage cluster, the hero
transactions), `data/samples.py` (the complaints and a labelled eval set), `data/policies.json`
(rule table), `data/outages.json` (declared incidents). Bank records come through
`tools/timeline_package/bank_connector.py` (`BankConnector` interface, `MockBankConnector`).

On first start the service seeds the demo queue with the deterministic pipeline
(`services/seed_service.py`, no LLM calls; audit entries are marked `via=seed`). Set `MIL_NO_SEED=1`
to skip it.

Add a sub-agent: write a tool in `tools/`, a prompt in `prompts/templates/agents/`, register it in
`agents/subagents.py` (`SUB_AGENTS`), add a route in `tools/tracker.route`, and add
`tests/unit/mil_agent/agents/test_<name>_agent.py`.
