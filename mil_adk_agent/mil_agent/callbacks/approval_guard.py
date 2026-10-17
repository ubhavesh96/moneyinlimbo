"""Human-in-the-loop guard: nothing leaves the entity unless the officer approved that exact item.

Defence in depth: on_event checks too, but this callback stops the call before it runs, whatever
the LLM decides.
"""

from __future__ import annotations

from mil_agent.services import case_service


def before_tool_callback_require_approval(tool, args, tool_context):
    if getattr(tool, "name", "") != "on_event" or args.get("event") != "approved":
        return None
    kind = args.get("kind")
    try:
        case = case_service.get(str(args.get("case_id", "")).strip())
    except KeyError:
        return {"ok": False, "error": "Unknown case.", "summary": "Unknown case. Nothing was sent."}
    ap = case.approval
    if not ap or ap.kind != kind or ap.status != "approved":
        msg = f"The officer has not approved the {str(kind).replace('_', ' ')}. Nothing was sent."
        return {"ok": False, "error": msg, "summary": msg}
    return None
