import collections
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.test_scenario_rules import check, failures
from src import config, planner, scoring, store

DRAWS = 12
FREE_AXES = ("temporal", "cooperation", "delivery", "continuity", "curveball")


def draw(count, pinned):
    axes_space = store.load("axes", {})
    history, unverified_claims, open_suspicions = planner.gather_state()
    return [
        scoring.select_scenario_axes(
            axes_space, history, open_suspicions, unverified_claims,
            len(history) + 1, pinned=pinned,
        )[0]
        for _ in range(count)
    ]


def test_two_axes_pinned():
    print("--- pinning two axes")
    pinned = planner.pinned_axes(axis_pairs=["intent=refill", "register=neutral"])
    check(pinned == {"intent": "refill", "register": "neutral"},
          f"two axes resolve to {pinned}", f"resolved to {pinned}")

    draws = draw(DRAWS, pinned)
    intents = {d["intent"] for d in draws}
    registers = {d["register"] for d in draws}
    check(intents == {"refill"} and registers == {"neutral"},
          f"every draw holds both pins across {DRAWS} draws",
          f"pins leaked: intent={intents} register={registers}")

    print(f"\n  axis distribution across {DRAWS} draws")
    varying = []
    for axis in ("intent", "register", "identity") + FREE_AXES:
        counts = collections.Counter(d[axis] for d in draws)
        print(f"    {axis:12} {len(counts)} distinct   "
              + "  ".join(f"{v}:{n}" for v, n in counts.most_common()))
        if axis in FREE_AXES and len(counts) > 1:
            varying.append(axis)
    check(len(varying) >= 3, f"{len(varying)} of {len(FREE_AXES)} free axes still vary",
          f"only {varying} varied; the sampler collapsed")


def test_bad_axis_fails_loudly():
    print("\n--- unknown axis name and value")
    for arguments, expected in (
        (["--axis", "nope=x"], "unknown axis"),
        (["--axis", "intent=nonsense"], "unknown value"),
        (["--axis", "intentrefill"], "expects name=value"),
    ):
        done = subprocess.run(
            [sys.executable, os.path.join(config.PROJECT_DIR, "scripts", "run_campaign.py"),
             "+15550000000", *arguments],
            cwd=config.PROJECT_DIR, capture_output=True, text=True,
        )
        message = ((done.stderr or done.stdout).strip().splitlines() or [""])[-1]
        check(done.returncode != 0 and expected in message,
              f"{' '.join(arguments)} exits {done.returncode}: {message}",
              f"{arguments} was accepted: {done.returncode} {message}")


def main():
    test_two_axes_pinned()
    test_bad_axis_fails_loudly()
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
