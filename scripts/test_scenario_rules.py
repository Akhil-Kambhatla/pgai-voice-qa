import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_scenario, campaign_summary, run_campaign
from src import ledgers

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


def test_profile_creation_is_conditional():
    print("--- profile creation depends on whether the identity has a record")
    creating = copy.deepcopy(GOOD)
    creating["persona_block"] = (
        GOOD["persona_block"] + " You will set up whatever patient profile they need."
    )
    with_record = campaign_scenario.validate(creating, record_identities={"dana"})
    check(any("already has a record" in p for p in with_record),
          "a record-having identity offering to create a profile is rejected",
          f"not rejected for a record-having identity: {with_record}")

    without_record = campaign_scenario.validate(creating, record_identities=set())
    check(not without_record,
          "the same persona is accepted for an identity with no record",
          f"wrongly rejected for an identity with no record: {without_record}")

    confirming = copy.deepcopy(GOOD)
    confirming["persona_block"] = (
        GOOD["persona_block"] + " Your profile is already on file, so you just confirm who you are."
    )
    for label, records in (("record-having", {"dana"}), ("no record", set())):
        problems = campaign_scenario.validate(confirming, record_identities=records)
        check(not problems, f"confirming an existing profile is accepted ({label})",
              f"confirming persona rejected ({label}): {problems}")

    derived = ledgers.identities_with_records()
    check(derived == {"dana"}, f"records derived from the claims ledger: {sorted(derived)}",
          f"derivation returned {sorted(derived)}, want dana from claim-01")


def main():
    test_validation()
    test_profile_creation_is_conditional()
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
