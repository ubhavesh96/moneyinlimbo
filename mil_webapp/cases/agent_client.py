"""Thin HTTP client for the ADK agent service."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from django.conf import settings

# Headers worth passing back to the browser (everything else is connection plumbing).
_PASS_BACK = ("content-type", "content-disposition")


@dataclass
class AgentResponse:
    status: int
    content: bytes
    headers: dict[str, str]

    def json(self):
        return json.loads(self.content or b"null")


class AgentUnavailable(Exception):
    pass


class AgentError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def forward(method: str, path: str, *, body: bytes = b"", content_type: str = "", query: str = "",
            form: dict[str, list[str]] | None = None,
            files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
            headers: dict[str, str] | None = None) -> AgentResponse:
    """Call the agent service. Multipart requests are rebuilt from `form` + `files` because
    Django's CSRF check has already consumed the raw body by the time the view runs."""
    url = f"{settings.AGENT_SERVICE_URL}/api/{path}" + (f"?{query}" if query else "")
    kwargs: dict = {"timeout": settings.AGENT_TIMEOUT_SECONDS, "headers": dict(headers or {})}
    if form is not None or files is not None:
        kwargs["data"] = form or {}
        kwargs["files"] = files or None
    else:
        kwargs["content"] = body or None
        if content_type:
            kwargs["headers"]["content-type"] = content_type
    try:
        r = httpx.request(method, url, **kwargs)
    except httpx.TransportError as exc:
        raise AgentUnavailable(str(exc)) from exc
    return AgentResponse(r.status_code, r.content, {k: v for k, v in r.headers.items() if k.lower() in _PASS_BACK})


def get_json(path: str, headers: dict[str, str] | None = None, query: str = ""):
    """GET a JSON resource for server-side rendering. Raises AgentError on a non-2xx answer."""
    r = forward("GET", path, query=query, headers=headers)
    if r.status >= 400:
        try:
            detail = r.json().get("detail", "")
        except (ValueError, AttributeError):
            detail = r.content[:200].decode(errors="replace")
        raise AgentError(r.status, str(detail))
    return r.json()
