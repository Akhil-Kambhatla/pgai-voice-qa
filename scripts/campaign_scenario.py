import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.smoke_planner import learned_not_achieved
from scripts.campaign_detectors import (
    asserts_a_record,
    creates_a_profile,
    stonewalls_identification,
    unsure_of_own_life,
)
from src import ledgers, oracle, persona

CALLER_FIELDS = ("persona_block", "goal", "opening_situation")


def validate(scenario, record_identities=None):
    failures = []
    if record_identities is None:
        record_identities = ledgers.identities_with_records()
    for slot in scenario.get("facts_to_elicit") or []:
        if slot not in oracle.ORACLE_SLOTS:
            failures.append(f"facts_to_elicit carries {slot!r}, which is not one of the ten oracle slots")

    for field in CALLER_FIELDS:
        text = scenario.get(field) or ""
        if text and persona.THIRD_PERSON.search(text) and not persona.SECOND_PERSON.search(text):
            failures.append(f"{field} talks about the caller in the third person")

    goal = scenario.get("goal") or ""
    if goal and learned_not_achieved(goal):
        failures.append("goal describes a fact learned rather than an outcome achieved")

    persona_text = (scenario.get("persona_block") or "").lower()
    sentence, marker = unsure_of_own_life(persona_text)
    if sentence:
        failures.append(
            f"persona makes the caller unsure of their own life ({marker!r}): {sentence!r}"
        )

    sentence, marker = stonewalls_identification(persona_text)
    if sentence:
        failures.append(
            f"persona has the caller stonewall identification ({marker!r}): {sentence!r}"
        )

    identity = scenario.get("identity")
    if identity in record_identities:
        sentence, verb = creates_a_profile(persona_text)
        if sentence:
            failures.append(
                f"{identity} already has a record, but the persona has them "
                f"{verb!r} a profile: {sentence!r}"
            )
    else:
        sentence, marker = asserts_a_record(persona_text)
        if sentence:
            failures.append(
                f"{identity} has no record, but the persona asserts one "
                f"({marker!r}): {sentence!r}"
            )

    return failures
