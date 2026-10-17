"""Case persistence: one JSON file per case under runtime/ (stands in for Cloud SQL)."""

from __future__ import annotations

import contextvars
import logging
import threading
from contextlib import contextmanager
from datetime import UTC, datetime

from pydantic import ValidationError

from mil_agent import settings
from mil_agent.models import AuditEntry, Case, Decision

log = logging.getLogger("mil.cases")
_lock = threading.RLock()
_cases: dict[str, Case] = {}

# Who is driving the tools right now: the ADK runtime, the seeding pipeline, or an officer action.
_via: contextvars.ContextVar[str] = contextvars.ContextVar("mil_via", default="adk")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def acting_as(via: str):
    token = _via.set(via)
    try:
        yield
    finally:
        _via.reset(token)


def _path(case_id: str):
    return settings.RUNTIME_DIR / case_id / "case.json"


def case_dir(case_id: str):
    d = settings.RUNTIME_DIR / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(case: Case) -> None:
    with _lock:
        _cases[case.id] = case
        case_dir(case.id)
        _path(case.id).write_text(case.model_dump_json(indent=2), encoding="utf-8")


def get(case_id: str) -> Case:
    with _lock:
        if case_id in _cases:
            return _cases[case_id]
        p = _path(case_id)
        if not p.exists():
            raise KeyError(f"Unknown case {case_id}")
        case = Case.model_validate_json(p.read_text(encoding="utf-8"))
        _cases[case_id] = case
        return case


def list_cases() -> list[Case]:
    """Every readable case. Files from an older schema are skipped, not deleted."""
    if settings.RUNTIME_DIR.exists():
        for p in settings.RUNTIME_DIR.glob("*/case.json"):
            if p.parent.name in _cases:
                continue
            try:
                get(p.parent.name)
            except (ValidationError, ValueError, KeyError):
                log.debug("Skipping unreadable case file %s", p)
    return sorted(_cases.values(), key=lambda c: (c.received, c.ref), reverse=True)


def forget_all() -> None:
    """Drop the in-memory cache (demo reset)."""
    with _lock:
        _cases.clear()


def audit(case: Case, agent: str, tool: str, summary: str,
          inputs: dict | None = None, outputs: dict | None = None) -> None:
    """Append to the audit trail; every entry carries the case's single trace id."""
    case.audit.append(AuditEntry(
        at=now_iso(), trace_id=case.trace_id, agent=agent, tool=tool, summary=summary,
        inputs=inputs or {}, outputs=_compact(outputs or {}), via=_via.get(),  # type: ignore[arg-type]
    ))
    save(case)


def decide(case: Case, actor: str, role: str, action: str, kind: str | None = None,
           reason: str = "", compensation_inr: int | None = None) -> Decision:
    d = Decision(at=now_iso(), actor=actor, role=role, action=action,  # type: ignore[arg-type]
                 kind=kind, reason=reason, compensation_inr=compensation_inr)
    case.decisions.append(d)
    with acting_as("officer"):
        audit(case, actor, f"officer.{action}", reason or action.replace("_", " "),
              inputs={"kind": kind} if kind else {}, outputs={"role": role})
    return d


def _compact(value, depth: int = 0):
    """Keep tool outputs readable in the audit trail: trim long text and long lists."""
    if isinstance(value, dict):
        return {k: _compact(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        items = [_compact(v, depth + 1) for v in value[:12]]
        return items + [f"... {len(value) - 12} more"] if len(value) > 12 else items
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "..."
    return value
