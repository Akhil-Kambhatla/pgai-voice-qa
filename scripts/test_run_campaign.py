import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_summary, run_campaign
from scripts.test_scenario_rules import GOOD, check, failures


def test_gives_up_after_three_attempts():
    print("--- planner retry ceiling")
    attempts = {"n": 0}

    def always_bad():
        attempts["n"] += 1
        scenario = copy.deepcopy(GOOD)
        scenario["facts_to_elicit"] = ["parking"]
        scenario["scenario_id"] = f"99-bad-{attempts['n']}"
        return scenario

    scenario, tried = run_campaign.plan_valid_scenario(always_bad)
    check(scenario is None, "gives up rather than dialling a bad scenario", "a bad scenario got through")
    check(attempts["n"] == 3, f"stopped after {attempts['n']} attempts", f"made {attempts['n']} attempts, want 3")

    good_on_second = {"n": 0}

    def bad_then_good():
        good_on_second["n"] += 1
        if good_on_second["n"] == 1:
            scenario = copy.deepcopy(GOOD)
            scenario["facts_to_elicit"] = ["parking"]
            return scenario
        return copy.deepcopy(GOOD)

    scenario, tried = run_campaign.plan_valid_scenario(bad_then_good)
    check(scenario is not None and len(tried) == 2, "regenerates and accepts the second draw",
          f"retry did not recover: {tried}")


def test_summary_against_call_05():
    print("--- summary against the real campaign/call-05")
    rendered = campaign_summary.summarise("campaign/call-05")
    print()
    print(rendered)
    print()
    check("176.9s" in rendered, "reports the granted hangup at 176.9s", "grant time missing")
    check("stalled" in rendered, "reports the grant condition", "grant condition missing")
    check("180s" in rendered, "reports the Telnyx duration", "duration missing")
    check("latency" in rendered and "median" in rendered, "reports latency", "latency missing")
    return rendered



def main():
    test_gives_up_after_three_attempts()
    test_summary_against_call_05()
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
