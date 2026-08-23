import copy
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_call, campaign_summary, run_campaign
from scripts.test_run_campaign import GOOD
from src import config

failures = []


def check(condition, passed, failed):
    if condition:
        print(f"  PASS {passed}")
    else:
        failures.append(failed)


def _fake_call_dir(root, call_id, status_events):
    path = os.path.join(root, call_id)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "call.json"), "w") as handle:
        json.dump({"call_id": call_id, "status_events": status_events}, handle)
    return path


def test_completion_detection():
    print("--- completion detection")
    root = tempfile.mkdtemp(prefix="campaign-wait-")
    original = config.CALLS_DIR
    config.CALLS_DIR = root
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    def sleep(seconds):
        clock["t"] += seconds

    try:
        _fake_call_dir(root, "call-a", [{"CallStatus": "completed", "CallDuration": "176",
                                         "HangupSource": "caller", "HangupCause": "normal_clearing"}])
        result = campaign_call.wait_for_completion("call-a", sleep=sleep, now=now)
        check(result["outcome"] == "completed" and result["hangup_source"] == "caller",
              f"granted hangup detected: {result['duration']}s by {result['hangup_source']}",
              f"granted hangup not detected: {result}")

        clock["t"] = 0.0
        _fake_call_dir(root, "call-b", [{"CallStatus": "completed", "CallDuration": "42",
                                         "HangupSource": "callee", "HangupCause": "normal_clearing"}])
        result = campaign_call.wait_for_completion("call-b", sleep=sleep, now=now)
        check(result["outcome"] == "completed" and result["hangup_source"] == "callee",
              f"far-end drop detected: {result['duration']}s by {result['hangup_source']}",
              f"far-end drop not detected: {result}")

        clock["t"] = 0.0
        _fake_call_dir(root, "call-c", [{"CallStatus": "ringing"}])
        result = campaign_call.wait_for_completion("call-c", sleep=sleep, now=now)
        check(result["outcome"] == "timeout",
              f"neither ending: times out after {result['waited']}s rather than hanging",
              f"no-completion case did not time out: {result}")
    finally:
        config.CALLS_DIR = original
        shutil.rmtree(root, ignore_errors=True)


def test_loop_with_dial_stubbed():
    print("--- whole loop, dial and wait stubbed, nothing is called")
    dialled = []
    ran = []
    original_preflight = campaign_call.preflight
    campaign_call.preflight = lambda today: (1, 1)
    try:
        outcome = run_one_call_stubbed(dialled, ran)
    finally:
        campaign_call.preflight = original_preflight
    check(outcome == "completed", f"loop completed one call end to end", f"loop returned {outcome}")
    check(dialled == [("99-good-scenario", "+15550000000")],
          f"dialled exactly once, with the stub number {dialled}", f"unexpected dials: {dialled}")
    check([name for name, _ in ran] == ["fetch_and_transcribe.py", "analyze_call.py"],
          f"ran fetch then analyse: {[n for n, _ in ran]}", f"wrong steps: {ran}")

    skipped = run_campaign.run_one_call(
        "+15550000000", lambda prompt: "s", planner=lambda: copy.deepcopy(GOOD),
        dial=lambda *a: dialled.append(("SHOULD NOT HAPPEN", a)),
        wait=lambda *a, **k: None, steps=lambda *a: None,
    )
    check(skipped == "skipped" and len(dialled) == 1, "answering s skips without dialling",
          f"skip path dialled: {dialled}")

    quit_result = run_campaign.run_one_call(
        "+15550000000", lambda prompt: "q", planner=lambda: copy.deepcopy(GOOD),
        dial=lambda *a: dialled.append(("SHOULD NOT HAPPEN", a)),
        wait=lambda *a, **k: None, steps=lambda *a: None,
    )
    check(quit_result == "quit" and len(dialled) == 1, "answering q quits without dialling",
          f"quit path dialled: {dialled}")


def run_one_call_stubbed(dialled, ran):
    def dial(scenario_id, number):
        dialled.append((scenario_id, number))
        return {"call_id": "call-05", "placed_at": "2026-08-23T00:00:00+00:00"}

    def wait(call_id, on_progress=None):
        return {"outcome": "completed", "duration": 180, "hangup_source": "caller",
                "hangup_cause": "normal_clearing"}

    def steps(name, *arguments):
        ran.append((name, arguments))
        return ""

    return run_campaign.run_one_call(
        "+15550000000", lambda prompt: "", planner=lambda: copy.deepcopy(GOOD),
        dial=dial, wait=wait, steps=steps,
    )


def main():
    test_completion_detection()
    test_loop_with_dial_stubbed()
    print()
    if failures:
        print("FAILED")
        for failure in failures:
            print("  " + failure)
        return 1
    print("ALL VERIFICATIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
