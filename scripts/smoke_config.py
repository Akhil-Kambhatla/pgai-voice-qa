import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

PROJECT = config.PROJECT_DIR
VAD_VARS = ("TURN_DETECTION", "VAD_EAGERNESS", "VAD_THRESHOLD", "VAD_SILENCE_MS")

BASE_ENV = {
    "TELNYX_API_KEY": "smoke", "TELNYX_ACCOUNT_SID": "smoke", "TELNYX_APPLICATION_SID": "smoke",
    "TELNYX_PHONE_NUMBER": "+10000000000", "OPENAI_API_KEY": "smoke", "DEEPGRAM_API_KEY": "smoke",
    "PUBLIC_BASE_URL": "https://smoke.invalid", "TARGET_NUMBER": "+10000000000",
    "MAX_CALL_SECONDS": "240", "MAX_CALLS_PER_RUN": "6",
    "REALTIME_MODEL": "gpt-realtime-2.1-mini", "PLANNER_MODEL": "gpt-5.4-mini",
}


def run_python(source, overrides=None):
    scratch = tempfile.mkdtemp(prefix="smoke-env-")
    settings = dict(BASE_ENV)
    settings.update(overrides or {})
    with open(os.path.join(scratch, ".env"), "w") as handle:
        for key, value in settings.items():
            handle.write(f"{key}={value}\n")
    try:
        environment = {k: v for k, v in os.environ.items() if k not in VAD_VARS}
        return subprocess.run(
            [sys.executable, "-c", source], cwd=scratch, env=environment,
            capture_output=True, text=True,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


CONFIG_PROBE = """
import json, sys
sys.path.insert(0, %r)
from src import config, session_config
print("RESULT " + json.dumps(session_config.resolved_turn_detection()))
""" % PROJECT


def config_combinations():
    valid = [
        ({}, {"type": "semantic_vad", "eagerness": "low"}),
        ({"VAD_EAGERNESS": "high"}, {"type": "semantic_vad", "eagerness": "high"}),
        ({"TURN_DETECTION": "server_vad"},
         {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 500}),
        ({"TURN_DETECTION": "server_vad", "VAD_THRESHOLD": "0.6", "VAD_SILENCE_MS": "600"},
         {"type": "server_vad", "threshold": 0.6, "prefix_padding_ms": 300, "silence_duration_ms": 600}),
    ]
    for overrides, expected in valid:
        done = run_python(CONFIG_PROBE, overrides)
        line = next((l for l in done.stdout.splitlines() if l.startswith("RESULT ")), None)
        assert line, f"{overrides} did not assemble: {done.stderr.strip()[-200:]}"
        assert json.loads(line[len("RESULT "):]) == expected, f"{overrides} assembled wrongly"

    invalid = [
        {"TURN_DETECTION": "banana"},
        {"VAD_THRESHOLD": "0.6"},
        {"TURN_DETECTION": "server_vad", "VAD_EAGERNESS": "high"},
        {"VAD_EAGERNESS": "urgent"},
        {"TURN_DETECTION": "server_vad", "VAD_THRESHOLD": "2.5"},
        {"TURN_DETECTION": "server_vad", "VAD_SILENCE_MS": "abc"},
    ]
    for overrides in invalid:
        assert run_python(CONFIG_PROBE, overrides).returncode != 0, f"{overrides} was accepted"
