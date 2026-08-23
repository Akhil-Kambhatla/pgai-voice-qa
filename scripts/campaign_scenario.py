import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.smoke_planner import learned_not_achieved
from src import ledgers, oracle, persona

UNSURE_MARKERS = (
    "not sure", "unsure", "cannot remember", "can't remember", "does not remember",
    "doesn't remember", "cannot recall", "can't recall", "no idea", "does not know",
    "doesn't know", "you do not know", "you don't know", "forgotten", "forgets",
    "vague about", "hazy", "cannot say which", "not certain",
)
REFUSAL_MARKERS = (
    "refuse", "refusing", "decline", "declining", "withhold", "withholding",
    "will not give", "won't give", "do not give", "don't give", "will not say",
    "won't say", "do not say", "don't say", "not willing to give", "unwilling to give",
    "reluctant to give", "reluctant to share", "avoid giving", "resist giving",
    "hold back", "rather not give", "rather not say", "push back on giving",
    "does not want to give", "doesn't want to give", "not want to give",
    "keep to yourself", "keeps to yourself",
)
IDENTIFICATION_TARGETS = (
    "name", "date of birth", "dob", "identify", "identification", "profile", "who you are",
)
PROFILE_WORDS = ("profile", "account")
PROFILE_CREATION_VERBS = (
    "set up", "sets up", "setting up", "create", "creates", "creating",
    "register", "registering", "sign up", "signing up", "start one", "set one up",
)
RECORD_WORDS = ("record", "profile", "account", "chart", "in their system", "in the system")
RECORD_EXISTS_MARKERS = (
    "already", "exists", "existing", "on file", "on record", "from last time",
    "from before", "they have your", "you are registered", "previously set up",
)
NEGATION_MARKERS = (" not ", "n't", "never", "no record", "no profile", "yet to")
PROFILE_EXISTS_MARKERS = (
    "already", "exists", "existing", "on file", "on record", "from last time",
    "from before", "have a profile", "has a profile", "confirm",
)
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
    for marker in UNSURE_MARKERS:
        if marker in persona_text:
            failures.append(f"persona makes the caller unsure of their own life: {marker!r}")
            break

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


def asserts_a_record(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        if any(marker in sentence for marker in NEGATION_MARKERS):
            continue
        if not any(word in sentence for word in RECORD_WORDS):
            continue
        for marker in RECORD_EXISTS_MARKERS:
            if marker in sentence:
                return sentence.strip(), marker
    return None, None


def creates_a_profile(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        if not any(word in sentence for word in PROFILE_WORDS):
            continue
        if any(marker in sentence for marker in PROFILE_EXISTS_MARKERS):
            continue
        for verb in PROFILE_CREATION_VERBS:
            if verb in sentence:
                return sentence.strip(), verb
    return None, None


def stonewalls_identification(persona_text):
    for sentence in re.split(r"[.;!?\n]", persona_text.lower()):
        if not any(target in sentence for target in IDENTIFICATION_TARGETS):
            continue
        for marker in REFUSAL_MARKERS:
            if marker in sentence:
                return sentence.strip(), marker
    return None, None
