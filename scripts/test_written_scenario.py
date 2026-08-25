import copy
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_scenario, run_campaign
from scripts.test_scenario_rules import GOOD, check, failures
from src import config, planner


def _written(scenario, directory):
    path = os.path.join(directory, "written.json")
    with open(path, "w") as handle:
        json.dump(scenario, handle)
    return path


def test_written_scenario():
    print("\n--- a hand-written scenario file")
    scratch = tempfile.mkdtemp(prefix="written-")
    original = config.SCENARIOS_DIR
    config.SCENARIOS_DIR = scratch
    original_preflight = run_campaign.campaign_call.preflight
    run_campaign.campaign_call.preflight = lambda today: (1, 1)

    def planner_must_not_run():
        raise AssertionError("the planner model was called for a hand-written scenario")

    try:
        good = copy.deepcopy(GOOD)
        good["scenario_id"] = "99-written-good"
        prompts, dialled = [], []

        def ask(prompt):
            prompts.append(prompt)
            return "s"

        outcome = run_campaign.run_one_call(
            "+15550000000", ask,
            planner=campaign_loader(_written(good, scratch), planner_must_not_run),
            dial=lambda *a: dialled.append(a), wait=lambda *a, **k: None,
            steps=lambda *a: None, regenerate=False,
        )
        check(outcome == "skipped" and prompts,
              f"a valid written scenario reaches the confirmation prompt: {prompts[0].strip()!r}",
              f"never reached confirmation: outcome={outcome} prompts={prompts}")
        check(not dialled, "and did not dial", f"it dialled: {dialled}")
        check(os.path.exists(os.path.join(scratch, "99-written-good.json")),
              "and was saved where the server will find it by id",
              "the written scenario was not saved into the scenarios directory")

        bad = copy.deepcopy(GOOD)
        bad["scenario_id"] = "99-written-bad"
        bad["facts_to_elicit"] = ["parking"]
        bad["goal"] = "You know their opening hours."
        attempts = {"n": 0}

        def counting_loader():
            attempts["n"] += 1
            with open(_written(bad, scratch)) as handle:
                return json.load(handle)

        outcome = run_campaign.run_one_call(
            "+15550000000", ask, planner=counting_loader,
            dial=lambda *a: dialled.append(a), wait=lambda *a, **k: None,
            steps=lambda *a: None, regenerate=False,
        )
        check(outcome == "planning_failed" and attempts["n"] == 1,
              f"an invalid written scenario stops after {attempts['n']} attempt, no regeneration",
              f"outcome={outcome} after {attempts['n']} attempts")
        check(not dialled, "and still did not dial", f"it dialled: {dialled}")
    finally:
        run_campaign.campaign_call.preflight = original_preflight
        config.SCENARIOS_DIR = original
        shutil.rmtree(scratch, ignore_errors=True)


def campaign_loader(path, forbidden):
    loader = campaign_scenario.load_written(path)

    def load():
        forbidden_calls = planner.plan_next_call
        planner.plan_next_call = forbidden
        try:
            return loader()
        finally:
            planner.plan_next_call = forbidden_calls

    return load


def main():
    test_written_scenario()
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
