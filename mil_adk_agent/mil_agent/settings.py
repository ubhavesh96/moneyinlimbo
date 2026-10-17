"""Local settings. Reads .env; no cloud services are touched."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if not os.getenv("MIL_SKIP_DOTENV"):  # tests set this so they never touch a real API key
    load_dotenv(ROOT / ".env")

RUNTIME_DIR = Path(os.getenv("MIL_RUNTIME_DIR", ROOT / "runtime"))
DATA_DIR = Path(__file__).resolve().parent / "data"
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-flash-preview")
APP_NAME = "money_in_limbo"
USER_ID = "grievance_desk"


def has_api_key() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
