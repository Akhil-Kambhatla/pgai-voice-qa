import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.smoke_planner import learned_not_achieved
from src import oracle, persona

UNSURE_MARKERS = (
    "not sure", "unsure", "cannot remember", "can't remember", "does not remember",
    "doesn't remember", "cannot recall", "can't recall", "no idea", "does not know",
    "doesn't know", "you do not know", "you don't know", "forgotten", "forgets",
    "vague about", "hazy", "cannot say which", "not certain",
)
PROFILE_MARKERS = ("profile",)
FULL_NAME_MARKERS = ("first and last name", "first and last", "full name", "first name and last name")
CALLER_FIELDS = ("persona_block", "goal", "opening_situation")


def validate(scenario):
    failures = []
    for slot in scenario.get("facts_to_elicit") or []:
        if slot not in oracle.ORACLE_SLOTS:
            failures.append(f"facts_to_elicit carries {slot!r}, which is not one of the ten oracle slots")

    if scenario.get("claims_to_verify"):
        failures.append(f"claims_to_verify must be empty, got {scenario['claims_to_verify']}")

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

    has_profile = any(marker in persona_text for marker in PROFILE_MARKERS)
    has_full_name = any(marker in persona_text for marker in FULL_NAME_MARKERS)
    if not (has_profile and has_full_name):
        missing = []
        if not has_profile:
            missing.append("creating the demo profile")
        if not has_full_name:
            missing.append("giving first and last name")
        failures.append(f"persona does not say the caller will: {', '.join(missing)}")

    return failures


def _wrapped(text, indent="    ", width=76):
    words = (text or "").split()
    lines, current = [], indent
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            lines.append(current)
            current = indent
        current += word + " "
    if current.strip():
        lines.append(current)
    return "\n".join(line.rstrip() for line in lines)


def _answers_when_asked(scenario):
    persona_text = scenario.get("persona_block") or ""
    opening = scenario.get("opening_situation") or ""
    dates = re.findall(
        r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\b\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\b"
        r"|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+\d{1,2}\b|\btomorrow\b|\bnext week\b|\bthis week\b",
        f"{persona_text} {opening}", re.IGNORECASE,
    )
    providers = re.findall(r"\bDr\.?\s+[A-Z][a-z]+|\b[A-Z][a-z]+ Hauser\b", f"{persona_text} {opening}")
    return sorted(set(d.lower() for d in dates)), sorted(set(providers))


def render(scenario):
    probe = scenario.get("primary_probe") or {}
    dates, providers = _answers_when_asked(scenario)
    axes = scenario.get("axes") or {}
    lines = [
        "=" * 78,
        f"SCENARIO  {scenario.get('scenario_id')}",
        "=" * 78,
        f"  identity   {scenario.get('identity')}",
        f"  intent     {axes.get('intent')}   axes: {', '.join(f'{k}={v}' for k, v in axes.items() if k != 'intent')}",
        "",
        "  persona",
        _wrapped(scenario.get("persona_block"), indent="    "),
        "",
        "  opening",
        _wrapped(scenario.get("opening_situation"), indent="    "),
        "",
        "  goal",
        _wrapped(scenario.get("goal"), indent="    "),
        "",
        f"  probe      {probe.get('name')}",
        _wrapped(probe.get("what_happens"), indent="    "),
        "  expected",
        _wrapped(probe.get("expected_correct_behavior"), indent="    "),
        "",
        f"  says when asked which date:     {', '.join(dates) if dates else 'NOTHING IN THE PERSONA'}",
        f"  says when asked which provider: {', '.join(providers) if providers else 'no preference stated'}",
        "",
        f"  facts_to_elicit   {scenario.get('facts_to_elicit')}",
        f"  follow-up         {scenario.get('opportunistic_follow_up')}",
        "=" * 78,
    ]
    return "\n".join(lines)
