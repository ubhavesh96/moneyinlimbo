"""FastAPI entry point for the Money in Limbo agent service (localhost only).

Run:  uvicorn mil_agent.main:app --port 8001
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mil_agent import settings
from mil_agent.api.audit import router as audit_router
from mil_agent.api.cases import router as cases_router
from mil_agent.api.samples import router as samples_router
from mil_agent.logging import get_logger
from mil_agent.services import seed_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not os.getenv("MIL_NO_SEED"):
        seed_service.seed_demo()
    logger.info("Agent service ready. LLM: %s", "Gemini " + settings.LLM_MODEL if settings.has_api_key()
                else "offline demo")
    yield


app = FastAPI(title="Money in Limbo: agent service", lifespan=lifespan)


@app.middleware("http")
async def auditors_are_read_only(request: Request, call_next):
    """Defence in depth: the web app blocks this too. Auditors can read and export, never change a case."""
    if request.headers.get("x-mil-role") == "auditor" and request.method not in ("GET", "HEAD", "OPTIONS"):
        return JSONResponse({"detail": "Auditors cannot change cases."}, status_code=403)
    return await call_next(request)


app.include_router(cases_router)
app.include_router(audit_router)
app.include_router(samples_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def _unhandled(_, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse({"detail": f"Unexpected error: {exc}"}, status_code=500)
