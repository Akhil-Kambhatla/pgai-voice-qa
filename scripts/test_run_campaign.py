import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_scenario, campaign_summary, run_campaign

GOOD = {
    "scenario_id": "99-good-scenario",
    "identity": "dana",
    "axes": {"intent": "book", "temporal": "explicit"},
    "persona_block": (
        "You are Dana Whitfield. Your knee has been sore since Saturday and you want it seen. "
        "You work Monday and Wednesday, so Tuesday August 25 is the day you can make."
    ),
    "opening_situation": "You are on a short break, wanting a knee appointment on Tuesday August 25.",
    "goal": "You have an appointment booked on a day you can actually make, or you know when to call back.",
    "primary_probe": {"name": "explicit-date-booking", "what_happens": "You ask for one specific date.",
                      "expected_correct_behavior": "The agent books on that date or says it cannot."},
    "opportunistic_follow_up": "If they mention a second location, ask whether the hours differ.",
    "facts_to_elicit": ["providers", "appointment_length"],
    "claims_to_verify": [],
}

BAD_SHAPES = [
    ("facts_to_elicit outside the ten slots", {"facts_to_elicit": ["claim-01", "parking"]}, "not one of the ten"),
    ("third person about the caller", {"goal": "She has the appointment booked for Tuesday."}, "third person"),
    ("goal is a fact learned", {"goal": "You know their opening hours for August 25."}, "fact learned"),
    ("caller unsure of own life",
     {"persona_block": GOOD["persona_block"] + " You are not sure which day your shift falls on."},
     "unsure of their own life"),
    ("caller stonewalls identification",
     {"persona_block": GOOD["persona_block"] + " You refuse to give your name until they explain why."},
     "stonewall identification"),
]

ACCEPTED_SHAPES = [
    ("claims_to_verify populated", {"claims_to_verify": ["claim-01"]}),
    ("persona silent about names", {"persona_block": "You are Dana Whitfield. Your knee has been sore since Saturday."}),
    ("declines a time slot, not a name",
     {"persona_block": GOOD["persona_block"] + " You decline the first slot they offer because you are working."}),
    ("gives the name in a later sentence",
     {"persona_block": "You are Dana Whitfield. You refuse to be rushed. You give your name when asked."}),
]

failures = []


def check(condition, passed, failed):
    if condition:
        print(f"  PASS {passed}")
    else:
        failures.append(failed)


def test_validation():
    print("--- validation")
    problems = campaign_scenario.validate(GOOD)
    check(not problems, "a good scenario is accepted", f"good scenario rejected: {problems}")
    for label, override, expected in BAD_SHAPES:
        scenario = copy.deepcopy(GOOD)
        scenario.update(override)
        problems = campaign_scenario.validate(scenario)
        hit = any(expected in problem for problem in problems)
        check(hit, f"rejected: {label}", f"{label} was not rejected, got {problems}")
    for label, override in ACCEPTED_SHAPES:
        scenario = copy.deepcopy(GOOD)
        scenario.update(override)
        problems = campaign_scenario.validate(scenario)
        check(not problems, f"accepted: {label}", f"{label} was wrongly rejected: {problems}")


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
    test_validation()
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
