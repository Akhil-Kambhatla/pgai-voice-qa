import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from src import config, oracle, persona, store
from src.planner import plan_next_call

REQUIRED_FIELDS = (
    "scenario_id", "axes", "identity", "persona_block", "opening_situation",
    "goal", "primary_probe", "opportunistic_follow_up", "facts_to_elicit", "claims_to_verify",
)
CLINIC_FACT_WORDS = (
    "open", "close", "closed", "hours", "am", "pm", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "accepts", "charges", "costs",
)
SERVICE_SIDE = (
    "anything else", "how can i help", "what do you need", "need anything",
    "offer to help", "let them know you", "wrap up", "before you go",
)


KNOWLEDGE_MARKERS = (
    "you know", "you have learned", "you find out", "you understand", "you have the answer",
)
OUTCOME_MARKERS = (
    "booked", "moved", "cancelled", "canceled", "confirmed", "sorted", "resolved",
    "corrected", "updated", "arranged", "rescheduled", "scheduled", "set up",
    "on the books", "have an appointment", "call back", "nothing further", "done",
    "next step", "what to do", "when to call", "what you need", "routed", "approved",
)


def learned_not_achieved(goal):
    clauses = [c for c in re.split(r",| and | or |;", goal.lower()) if c.strip()]
    if not any(any(m in c for m in KNOWLEDGE_MARKERS) for c in clauses):
        return False
    return not any(any(m in c for m in OUTCOME_MARKERS) for c in clauses)


def clinic_facts_in(text, oracle_data):
    if not text:
        return []
    oracle_text = " ".join(str(v).lower() for v in oracle_data.values()) if oracle_data else ""
    hits = []
    for sentence in re.split(r"[.;]", text):
        lowered = sentence.lower()
        if re.search(r"\bthey (open|close|are open|are closed)\b", lowered) or \
           re.search(r"\b(open|close[sd]?) at \d", lowered):
            if lowered.strip() not in oracle_text:
                hits.append(sentence.strip())
    return hits


def assess(scenario, oracle_data):
    failures = []
    for field in REQUIRED_FIELDS:
        if field not in scenario:
            failures.append(f"missing field {field}")
    for field in ("persona_block", "goal", "opening_situation"):
        text = scenario.get(field) or ""
        if not text:
            continue
        if persona.THIRD_PERSON.search(text) and not persona.SECOND_PERSON.search(text):
            failures.append(f"{field} is third person")
    goal = scenario.get("goal") or ""
    if goal and learned_not_achieved(goal):
        failures.append("goal describes a fact learned, not something achieved")

    for slot in scenario.get("facts_to_elicit") or []:
        if slot not in oracle.ORACLE_SLOTS:
            failures.append(f"facts_to_elicit carries {slot!r}, which is not an oracle slot name")

    identity = store.load("identities", {}).get(scenario.get("identity"), {})
    persona_text = scenario.get("persona_block") or ""
    if identity:
        for key in ("dob", "member_id"):
            value = identity.get(key)
            if value and value in persona_text:
                failures.append(f"persona volunteers the identity {key}")
        first_name = (identity.get("name") or "").split(" ")[0]
        if first_name and first_name.lower() not in persona_text.lower():
            failures.append(f"persona does not use the identity name {first_name}")
    else:
        failures.append(f"identity {scenario.get('identity')!r} is not in identities.json")

    invented = clinic_facts_in(persona_text, oracle_data)
    for fact in invented:
        failures.append(f"persona asserts a clinic fact absent from the oracle: {fact!r}")

    follow_up = (scenario.get("opportunistic_follow_up") or "").lower()
    for phrase in SERVICE_SIDE:
        if phrase in follow_up:
            failures.append(f"opportunistic_follow_up takes the service side: {phrase!r}")
    return failures


def sample(draws):
    oracle_data = store.load("oracle", {})
    scratch = tempfile.mkdtemp(prefix="smoke-scenarios-")
    original = config.SCENARIOS_DIR
    config.SCENARIOS_DIR = scratch
    dropped = []
    sink = logger.add(lambda m: dropped.append(m.record["message"]), level="WARNING")
    results = []
    try:
        for _ in range(draws):
            before = len(dropped)
            try:
                scenario = plan_next_call()
            except Exception as error:
                results.append(("<planner error>", [f"{type(error).__name__}: {error}"]))
                continue
            failures = assess(scenario, oracle_data)
            for message in dropped[before:]:
                if "facts_to_elicit" in message:
                    failures.append(f"validator had to strip the emitted facts_to_elicit: {message}")
            results.append((scenario.get("scenario_id", "<no slug>"), failures))
    finally:
        logger.remove(sink)
        config.SCENARIOS_DIR = original
        shutil.rmtree(scratch, ignore_errors=True)
    return results
