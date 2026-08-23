import collections
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, planner, scoring, store

PINNED_DRAWS = 20
FREE_DRAWS = 10
FREE_AXES = ("intent", "temporal", "cooperation", "delivery", "register", "continuity", "curveball")

failures = []


def check(condition, passed, failed):
    if condition:
        print(f"  PASS {passed}")
    else:
        failures.append(failed)


def draw(count, pinned):
    axes_space = store.load("axes", {})
    history, unverified_claims, open_suspicions = planner.gather_state()
    call_index = len(history) + 1
    return [
        scoring.select_scenario_axes(
            axes_space, history, open_suspicions, unverified_claims, call_index, pinned=pinned
        )[0]
        for _ in range(count)
    ]


def distribution(draws, label):
    print(f"\n  axis distribution across {len(draws)} draws ({label})")
    for axis in ("identity",) + FREE_AXES:
        counts = collections.Counter(d[axis] for d in draws)
        rendered = "  ".join(f"{value}:{n}" for value, n in counts.most_common())
        print(f"    {axis:12} {len(counts)} distinct   {rendered}")
    return {axis: collections.Counter(d[axis] for d in draws) for axis in FREE_AXES}


def test_pinned_identity():
    print("--- twenty draws with identity pinned to dana")
    draws = draw(PINNED_DRAWS, {"identity": "dana"})
    identities = {d["identity"] for d in draws}
    check(identities == {"dana"}, f"every draw uses dana ({len(draws)} draws)",
          f"pinned draws used {identities}")

    spread = distribution(draws, "identity pinned")
    varying = [axis for axis, counts in spread.items() if len(counts) > 1]
    check(len(varying) >= 5,
          f"{len(varying)} of {len(FREE_AXES)} free axes vary: {', '.join(varying)}",
          f"only {len(varying)} free axes varied, the sampler has collapsed: {spread}")

    combinations = {tuple(d[axis] for axis in FREE_AXES) for d in draws}
    check(len(combinations) >= PINNED_DRAWS // 2,
          f"{len(combinations)} distinct free-axis combinations across {PINNED_DRAWS} draws",
          f"only {len(combinations)} distinct combinations, collapsed onto one shape")


def test_unpinned_still_varies():
    print("\n--- ten draws with no pin")
    draws = draw(FREE_DRAWS, None)
    identities = collections.Counter(d["identity"] for d in draws)
    distribution(draws, "no pin")
    check(len(identities) > 1, f"identity still varies: {dict(identities)}",
          f"identity collapsed to {dict(identities)} with no pin")


def test_unknown_identity_fails_loudly():
    print("\n--- unknown identity")
    done = subprocess.run(
        [sys.executable, os.path.join(config.PROJECT_DIR, "scripts", "plan_call.py"),
         "--identity", "nobody"],
        cwd=config.PROJECT_DIR, capture_output=True, text=True,
    )
    message = (done.stderr or done.stdout).strip().splitlines()
    message = message[-1] if message else ""
    check(done.returncode != 0, f"plan_call.py exits {done.returncode}",
          "an unknown identity was accepted")
    check("unknown identity" in message and "akhil" in message,
          f"message names the problem and the valid keys: {message}",
          f"unhelpful message: {message}")

    runner = subprocess.run(
        [sys.executable, os.path.join(config.PROJECT_DIR, "scripts", "run_campaign.py"),
         "+15550000000", "--identity", "nobody"],
        cwd=config.PROJECT_DIR, capture_output=True, text=True,
    )
    runner_message = (runner.stderr or runner.stdout).strip().splitlines()
    runner_message = runner_message[-1] if runner_message else ""
    check(runner.returncode != 0 and "unknown identity" in runner_message,
          f"run_campaign.py rejects it before dialling: exit {runner.returncode}",
          f"run_campaign accepted an unknown identity: {runner.returncode} {runner_message}")

    try:
        planner.pinned_axes_for("nobody")
        failures.append("pinned_axes_for accepted an unknown identity")
    except SystemExit as error:
        check("nobody" in str(error), f"pinned_axes_for refuses: {error}", f"wrong error: {error}")
    check(planner.pinned_axes_for(None) == {}, "unset pins nothing", "unset produced a pin")
    check(planner.pinned_axes_for("dana") == {"identity": "dana"},
          "a known identity pins cleanly", "known identity did not pin")


def test_pinned_axis_excluded_from_scoring():
    print("\n--- pinned axis is excluded from the exploration terms")
    axes_space = store.load("axes", {})
    history, unverified_claims, open_suspicions = planner.gather_state()
    counts = scoring.usage_counts(history, axes_space)
    pairs = scoring.covered_pairs(history)
    candidate = dict(history[-1]["axes"]) if history else {}
    candidate["identity"] = "dana"
    scored_with = scoring.score(candidate, counts, pairs, [], 7, 20, {"identity": "dana"})
    scored_without = scoring.score(candidate, counts, pairs, [], 7, 20, None)
    check(scored_with != scored_without,
          f"scoring ignores the pinned axis: {scored_with:.4f} pinned vs {scored_without:.4f} unpinned",
          "pinning made no difference to the score, so the exclusion is not wired")


def main():
    scratch = tempfile.mkdtemp(prefix="identity-pin-scenarios-")
    original = config.SCENARIOS_DIR
    config.SCENARIOS_DIR = scratch
    try:
        test_pinned_identity()
        test_unpinned_still_varies()
        test_unknown_identity_fails_loudly()
        test_pinned_axis_excluded_from_scoring()
    finally:
        config.SCENARIOS_DIR = original
        left = os.listdir(scratch)
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n  temp scenarios directory held {len(left)} files and was removed")
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
