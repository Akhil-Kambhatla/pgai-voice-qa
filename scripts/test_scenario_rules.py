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
    ("caller unsure of their own dates",
     {"persona_block": GOOD["persona_block"] + " You are not sure which day your shift falls on."},
     "unsure of their own life"),
    ("caller cannot recall their own details",
     {"persona_block": GOOD["persona_block"] + " You don't know when your last appointment with your physio was."},
     "unsure of their own life"),
    ("goal is only a fact learned",
     {"goal": "You know whether Aetna is accepted here."},
     "fact learned"),
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
    ("uncertainty belongs to the agent",
     {"persona_block": GOOD["persona_block"] + " You may repeat it if they seem unsure."}),
    ("uncertainty about something the clinic owns",
     {"persona_block": GOOD["persona_block"] + " You are not sure whether they take your insurance."}),
    ("uncertainty about whether a booking went through",
     {"persona_block": GOOD["persona_block"] + " You booked something last week but you are not sure it went through."}),
    ("goal pairs a fact with a next step",
     {"goal": "You know whether your Medicare plan is accepted, and if it is, you have the next step for getting seen."}),
    ("goal is a plain outcome",
     {"goal": "You have the appointment moved to a time you can actually make."}),
]

failures = []


def check(condition, passed, failed):
    if condition:
        print(f"  PASS {passed}")
    else:
        failures.append(failed)


def test_validation():
    print("--- validation")
    problems = campaign_scenario.validate(GOOD, record_identities=set())
    check(not problems, "a good scenario is accepted", f"good scenario rejected: {problems}")
    for label, override, expected in BAD_SHAPES:
        scenario = copy.deepcopy(GOOD)
        scenario.update(override)
        problems = campaign_scenario.validate(scenario, record_identities=set())
        hit = any(expected in problem for problem in problems)
        check(hit, f"rejected: {label}", f"{label} was not rejected, got {problems}")
    for label, override in ACCEPTED_SHAPES:
        scenario = copy.deepcopy(GOOD)
        scenario.update(override)
        problems = campaign_scenario.validate(scenario, record_identities=set())
        check(not problems, f"accepted: {label}", f"{label} was wrongly rejected: {problems}")


def main():
    test_validation()
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
