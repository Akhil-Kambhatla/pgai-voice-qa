import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_scenario
from scripts.test_scenario_rules import GOOD, check, failures
from src import ledgers


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
    check(not campaign_scenario.validate(confirming, record_identities={"dana"}),
          "confirming an existing profile is accepted when the record exists",
          "confirming was rejected for a record-having identity")
    check(any("has no record" in p
              for p in campaign_scenario.validate(confirming, record_identities=set())),
          "confirming a profile is rejected when no record exists, which is the same leak",
          "a no-record identity was allowed to confirm a profile it does not have")

    asserting = copy.deepcopy(GOOD)
    asserting["persona_block"] = (
        GOOD["persona_block"] + " You already exist in their system and will confirm who you are."
    )
    no_record = campaign_scenario.validate(asserting, record_identities=set())
    check(any("has no record" in p for p in no_record),
          "a no-record identity asserting an existing record is rejected",
          f"not rejected for a no-record identity: {no_record}")

    on_file = copy.deepcopy(GOOD)
    on_file["persona_block"] = (
        GOOD["persona_block"] + " You already know this clinic has your record on file."
    )
    check(any("has no record" in p for p in campaign_scenario.validate(on_file, record_identities=set())),
          "the on-file phrasing is rejected too",
          "the on-file phrasing slipped through")

    check(not campaign_scenario.validate(creating, record_identities=set()),
          "a no-record persona offering to create one is still accepted",
          "the creation persona was wrongly rejected for a no-record identity")

    check(campaign_scenario.validate(asserting, record_identities={"dana"}) == [],
          "the same assertion is accepted when the identity does have a record",
          "asserting a real record was rejected")

    derived = ledgers.identities_with_records()
    check(derived == {"dana"}, f"records derived from the claims ledger: {sorted(derived)}",
          f"derivation returned {sorted(derived)}, want dana from claim-01")


def main():
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
