"""Shared helpers for agent tools."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from mil_agent.models import Case
from mil_agent.services import case_service


def agent_name(tool_context, default: str) -> str:
    return getattr(tool_context, "agent_name", None) or default


def load(case_id: str) -> Case:
    return case_service.get(str(case_id).strip())


def done(case: Case, agent: str, tool: str, summary: str, inputs: dict | None = None,
         output: BaseModel | None = None, **extra) -> dict:
    """Record the call (inputs and typed output) in the audit trail, persist, and return a compact
    result to the LLM. `output` is the tool's typed output from the project file's contract."""
    out = output.model_dump() if output is not None else {}
    contract = {}
    if output is not None:  # round-trip through the typed contract before anything is trimmed for the log
        try:
            type(output).model_validate(out)
            contract = {"_contract": f"{type(output).__name__}: valid"}
        except ValidationError as e:
            contract = {"_contract": f"{type(output).__name__}: INVALID {str(e).splitlines()[0]}"}
    case_service.audit(case, agent, tool, summary, inputs=inputs or {"case_id": case.id},
                       outputs={**contract, **out, **extra})
    result = {"ok": True, "summary": summary, **extra}
    if output is not None:
        result[type(output).__name__] = out
    return result


def fail(message: str) -> dict:
    return {"ok": False, "error": message, "summary": message}


def indian(n: float) -> str:
    """Indian digit grouping: 1234567.5 -> '12,34,567.50'."""
    whole, frac = f"{abs(n):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    out = ",".join(([head] if head else []) + groups + [tail])
    out = ("-" if n < 0 else "") + out
    return out if frac == "00" else f"{out}.{frac}"


def money(x: float | int | None) -> str:
    return "an unknown amount" if x is None else f"Rs {indian(float(x))}"
