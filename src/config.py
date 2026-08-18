"""Environment configuration. Validates on import and exposes module-level constants."""

import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

_REQUIRED = [
    "TELNYX_API_KEY",
    "TELNYX_ACCOUNT_SID",
    "TELNYX_APPLICATION_SID",
    "TELNYX_PHONE_NUMBER",
    "OPENAI_API_KEY",
    "DEEPGRAM_API_KEY",
    "PUBLIC_BASE_URL",
    "TARGET_NUMBER",
    "MAX_CALL_SECONDS",
    "MAX_CALLS_PER_RUN",
    "REALTIME_MODEL",
    "PLANNER_MODEL",
]

_missing = [name for name in _REQUIRED if not os.getenv(name)]
if _missing:
    sys.exit(
        "Missing required environment variables: "
        + ", ".join(_missing)
        + "\nSet them in .env (see .env.example)."
    )

TELNYX_API_KEY = os.environ["TELNYX_API_KEY"]
TELNYX_ACCOUNT_SID = os.environ["TELNYX_ACCOUNT_SID"]
TELNYX_APPLICATION_SID = os.environ["TELNYX_APPLICATION_SID"]
TELNYX_PHONE_NUMBER = os.environ["TELNYX_PHONE_NUMBER"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DEEPGRAM_API_KEY = os.environ["DEEPGRAM_API_KEY"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")
TARGET_NUMBER = os.environ["TARGET_NUMBER"]
MAX_CALL_SECONDS = int(os.environ["MAX_CALL_SECONDS"])
MAX_CALLS_PER_RUN = int(os.environ["MAX_CALLS_PER_RUN"])
REALTIME_MODEL = os.environ["REALTIME_MODEL"]
PLANNER_MODEL = os.environ["PLANNER_MODEL"]

if not PUBLIC_BASE_URL.startswith("https://"):
    sys.exit("PUBLIC_BASE_URL must be an https:// URL (the ngrok tunnel URL)")

# wss URL for Telnyx media streaming, derived from the public https URL.
PUBLIC_WS_URL = "wss://" + PUBLIC_BASE_URL.removeprefix("https://")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
CALLS_DIR = os.path.join(DATA_DIR, "calls")
SCENARIOS_DIR = os.path.join(PROJECT_DIR, "scenarios")
PROMPTS_DIR = os.path.join(PROJECT_DIR, "src", "prompts")
