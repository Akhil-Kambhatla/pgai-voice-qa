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

TURN_DETECTION_MODES = ("semantic_vad", "server_vad")
VAD_EAGERNESS_LEVELS = ("low", "medium", "high")


def _optional(name):
    value = os.getenv(name)
    value = value.strip() if value else ""
    return value or None


TURN_DETECTION = _optional("TURN_DETECTION") or "semantic_vad"
if TURN_DETECTION not in TURN_DETECTION_MODES:
    sys.exit(
        f"TURN_DETECTION must be one of {', '.join(TURN_DETECTION_MODES)}; got '{TURN_DETECTION}'"
    )

_eagerness = _optional("VAD_EAGERNESS")
_threshold = _optional("VAD_THRESHOLD")
_silence_ms = _optional("VAD_SILENCE_MS")

if TURN_DETECTION == "semantic_vad":
    _wrong_mode = [n for n, v in (("VAD_THRESHOLD", _threshold), ("VAD_SILENCE_MS", _silence_ms)) if v]
    if _wrong_mode:
        sys.exit(
            f"{', '.join(_wrong_mode)} applies only when TURN_DETECTION=server_vad, "
            f"but TURN_DETECTION is semantic_vad. Unset it or switch modes."
        )
elif _eagerness:
    sys.exit(
        "VAD_EAGERNESS applies only when TURN_DETECTION=semantic_vad, "
        "but TURN_DETECTION is server_vad. Unset it or switch modes."
    )

VAD_EAGERNESS = _eagerness or "low"
if VAD_EAGERNESS not in VAD_EAGERNESS_LEVELS:
    sys.exit(
        f"VAD_EAGERNESS must be one of {', '.join(VAD_EAGERNESS_LEVELS)}; got '{VAD_EAGERNESS}'"
    )

VAD_THRESHOLD = None
if _threshold:
    try:
        VAD_THRESHOLD = float(_threshold)
    except ValueError:
        sys.exit(f"VAD_THRESHOLD must be a number between 0.0 and 1.0; got '{_threshold}'")
    if not 0.0 <= VAD_THRESHOLD <= 1.0:
        sys.exit(f"VAD_THRESHOLD must be between 0.0 and 1.0; got {VAD_THRESHOLD}")

TRANSCRIBE_LANGUAGE = _optional("TRANSCRIBE_LANGUAGE") or "en"

VAD_SILENCE_MS = None
if _silence_ms:
    try:
        VAD_SILENCE_MS = int(_silence_ms)
    except ValueError:
        sys.exit(f"VAD_SILENCE_MS must be a whole number of milliseconds; got '{_silence_ms}'")
    if VAD_SILENCE_MS <= 0:
        sys.exit(f"VAD_SILENCE_MS must be greater than zero; got {VAD_SILENCE_MS}")

if not PUBLIC_BASE_URL.startswith("https://"):
    sys.exit("PUBLIC_BASE_URL must be an https:// URL (the ngrok tunnel URL)")

# wss URL for Telnyx media streaming, derived from the public https URL.
PUBLIC_WS_URL = "wss://" + PUBLIC_BASE_URL.removeprefix("https://")

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
CAMPAIGN_DIR = os.path.join(DATA_DIR, "campaign")

CALL_TREES = {
    "roleplay": (os.path.join(DATA_DIR, "calls"), DATA_DIR),
    "campaign": (os.path.join(CAMPAIGN_DIR, "calls"), CAMPAIGN_DIR),
}

CALL_TREE = _optional("CALL_TREE") or "campaign"
if CALL_TREE not in CALL_TREES:
    sys.exit(f"CALL_TREE must be one of {', '.join(CALL_TREES)}; got '{CALL_TREE}'")

CALLS_DIR, STATE_DIR = CALL_TREES[CALL_TREE]
SCENARIOS_DIR = os.path.join(PROJECT_DIR, "scenarios")
PROMPTS_DIR = os.path.join(PROJECT_DIR, "src", "prompts")
