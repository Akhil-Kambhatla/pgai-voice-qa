import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_summary
from scripts.test_far_end_disconnect import FIXTURES, check, failures
from src import store


def test_summary_reports_each_ending():
    print("\n--- the summary tells the three endings apart")
    granted = [{"t": 176.9, "source": "lifecycle",
                "event": {"type": "exit.hangup_granted", "grant_condition": "stalled"}}]
    how, condition, _ = campaign_summary.ending(granted, {"hangup_source": "caller"})
    check("granted" in how and condition == "stalled", f"granted hang_up: {how!r} / {condition!r}",
          f"granted misreported: {how} {condition}")

    watchdog = [{"t": 240.0, "source": "lifecycle", "event": {"type": "exit.watchdog_terminated"}}]
    how, condition, _ = campaign_summary.ending(watchdog, {})
    check("watchdog" in how and condition == "watchdog", f"watchdog: {how!r}",
          f"watchdog misreported: {how} {condition}")

    dropped = [{"t": 161.3, "source": "lifecycle",
                "event": {"type": "exit.far_end_disconnected", "signal": "telnyx_stop"}}]
    how, condition, _ = campaign_summary.ending(dropped, {"hangup_source": "callee"})
    check("far end disconnected at 161.3s" in how and "telnyx_stop" in condition,
          f"far-end drop: {how!r} / {condition!r}", f"drop misreported: {how} {condition}")
    check(campaign_summary.ending(granted, {})[0] != campaign_summary.ending(dropped, {})[0],
          "the three endings are distinct", "endings collide")


def test_recordings_survive():
    print("\n--- recordings and transcripts of calls that ended by far-end drop")
    for call_id in FIXTURES:
        call_dir = store.resolve_call_dir(call_id)
        sizes = {
            name: os.path.getsize(os.path.join(call_dir, name))
            for name in ("recording.mp3", "transcript.txt")
            if os.path.exists(os.path.join(call_dir, name))
        }
        check(sizes.get("recording.mp3", 0) > 10000 and sizes.get("transcript.txt", 0) > 200,
              f"{call_id}: recording {sizes.get('recording.mp3')} bytes, "
              f"transcript {sizes.get('transcript.txt')} bytes",
              f"{call_id}: artifacts missing or truncated: {sizes}")


def main():
    test_summary_reports_each_ending()
    test_recordings_survive()
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
