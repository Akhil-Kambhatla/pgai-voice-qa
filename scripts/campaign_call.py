import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import call_counter, config, store

SERVER = "http://localhost:7860"
NGROK_TUNNELS = "http://127.0.0.1:4040/api/tunnels"
COMPLETION_GRACE_SECONDS = 60
POLL_SECONDS = 2


class PreflightFailure(RuntimeError):
    pass


def _get_json(url, timeout=4):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def preflight(today):
    try:
        urllib.request.urlopen(f"{SERVER}/openapi.json", timeout=4).read()
    except Exception as error:
        raise PreflightFailure(f"server on {SERVER} is not reachable: {error}")

    try:
        tunnels = _get_json(NGROK_TUNNELS)
    except Exception as error:
        raise PreflightFailure(
            f"ngrok agent API on {NGROK_TUNNELS} is not reachable, so no tunnel is running: {error}"
        )
    public_urls = [t.get("public_url") for t in tunnels.get("tunnels", [])]
    if config.PUBLIC_BASE_URL not in public_urls:
        raise PreflightFailure(
            f"PUBLIC_BASE_URL is stale: .env says {config.PUBLIC_BASE_URL}, ngrok is serving {public_urls}"
        )

    placed = call_counter.placed_on(today)
    if placed >= config.MAX_CALLS_PER_RUN:
        raise PreflightFailure(
            f"daily cap reached: {placed} of {config.MAX_CALLS_PER_RUN} calls already placed on {today}"
        )
    return placed, len(public_urls)


def dial(scenario_id, phone_number):
    request = urllib.request.Request(
        f"{SERVER}/start",
        data=json.dumps({"scenario_id": scenario_id, "phone_number": phone_number}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise PreflightFailure(f"dial refused with HTTP {error.code}: {error.read().decode()[:300]}")
    except Exception as error:
        raise PreflightFailure(f"dial failed: {error}")


def _completed_event(call_dir):
    path = os.path.join(call_dir, "call.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as handle:
            record = json.load(handle)
    except (ValueError, OSError):
        return None
    for event in record.get("status_events", []):
        if event.get("CallStatus") == "completed":
            return event
    return None


def _progress_line(call_dir, seen):
    path = os.path.join(call_dir, "turns.jsonl")
    fresh = []
    if not os.path.exists(path):
        return fresh
    with open(path) as handle:
        for index, line in enumerate(handle):
            if index < seen or not line.strip():
                continue
            try:
                turn = json.loads(line)
            except ValueError:
                continue
            fresh.append(turn)
    return fresh


def wait_for_completion(call_id, on_progress=None, sleep=time.sleep, now=time.monotonic):
    call_dir = os.path.join(config.CALLS_DIR, call_id)
    deadline = now() + config.MAX_CALL_SECONDS + COMPLETION_GRACE_SECONDS
    seen = 0
    while now() < deadline:
        event = _completed_event(call_dir)
        if event:
            return {
                "outcome": "completed",
                "duration": int(event.get("CallDuration") or 0),
                "hangup_source": event.get("HangupSource"),
                "hangup_cause": event.get("HangupCause"),
            }
        fresh = _progress_line(call_dir, seen)
        if fresh:
            seen += len(fresh)
            if on_progress:
                for turn in fresh:
                    on_progress(turn)
        sleep(POLL_SECONDS)
    return {
        "outcome": "timeout",
        "duration": None,
        "hangup_source": None,
        "hangup_cause": None,
        "waited": config.MAX_CALL_SECONDS + COMPLETION_GRACE_SECONDS,
    }
