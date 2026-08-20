import base64
import json
import re

from fastapi import WebSocket
from loguru import logger

from src import store

SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)
THIRD_PERSON = re.compile(r"\b(he|she|him|his|her|hers|himself|herself)\b", re.IGNORECASE)

CALLER_PRONOUNS = {
    "him": "you",
    "his": "your",
    "her": "your",
    "hers": "yours",
    "himself": "yourself",
    "herself": "yourself",
}

IRREGULAR_PRESENT = {
    "is": "are",
    "has": "have",
    "does": "do",
    "was": "were",
    "goes": "go",
    "isn't": "aren't",
    "hasn't": "haven't",
    "doesn't": "don't",
    "wasn't": "weren't",
}

INTERVENING_ADVERB = r"(?:\w+ly|still|just|also|never|always|now|then|already|even|again|often)"


def _matching_case(source: str, replacement: str) -> str:
    return replacement.capitalize() if source[:1].isupper() else replacement


def _base_verb(verb: str) -> str:
    lowered = verb.lower()
    if lowered in IRREGULAR_PRESENT:
        return _matching_case(verb, IRREGULAR_PRESENT[lowered])
    if lowered.endswith("ies") and len(lowered) > 4:
        return verb[:-3] + "y"
    if lowered.endswith(("sses", "shes", "ches", "xes", "zes")):
        return verb[:-2]
    if lowered.endswith("s") and not lowered.endswith(("ss", "us", "is")):
        return verb[:-1]
    return verb


def as_second_person(text: str) -> str:
    text = re.sub(
        r"\b(he|she)'s\b", lambda m: _matching_case(m.group(1), "you're"), text, flags=re.IGNORECASE
    )
    text = re.sub(
        rf"\b(he|she)\s+((?:{INTERVENING_ADVERB}\s+)*)([\w']+)",
        lambda m: f"{_matching_case(m.group(1), 'you')} {m.group(2)}{_base_verb(m.group(3))}",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"\b(him|his|her|hers|himself|herself)\b",
        lambda m: _matching_case(m.group(1), CALLER_PRONOUNS[m.group(1).lower()]),
        text,
        flags=re.IGNORECASE,
    )


def addressed_to_caller(field_name: str, text: str, call_id: str) -> str:
    if SECOND_PERSON.search(text):
        if THIRD_PERSON.search(text):
            logger.warning(
                f"{field_name} in {call_id} mixes second and third person; "
                f"left exactly as the planner wrote it"
            )
        return text
    return as_second_person(text)


def decode_body(websocket: WebSocket) -> dict:
    raw = websocket.query_params.get("body")
    if not raw:
        return {}
    return json.loads(base64.b64decode(raw))


def build_instructions(scenario: dict, call_id: str) -> str:
    identity = store.load("identities", {}).get(scenario["identity"], {})
    dynamic = [
        addressed_to_caller("persona_block", scenario["persona_block"], call_id),
        f"Your details, and the only identifying details you may ever give: "
        f"name {identity.get('name')}, date of birth {identity.get('dob')}. "
        f"Give them only when they ask you to identify yourself. "
        f"Never offer them before they ask.",
        f"What you are trying to get done on this call: "
        f"{addressed_to_caller('goal', scenario['goal'], call_id)}",
        f"Where you are as they pick up: "
        f"{addressed_to_caller('opening_situation', scenario['opening_situation'], call_id)} "
        f"Your first words are your own. Find them in the moment, the way you would "
        f"on a real call, and do not reach for a line you have heard before.",
    ]
    if scenario.get("opportunistic_follow_up"):
        dynamic.append(f"One instinct to keep in your back pocket: {scenario['opportunistic_follow_up']}")
    if scenario.get("caller_id_cover"):
        dynamic.append(
            f"If they address you by a different name because of your phone number, "
            f"say something like: \"{scenario['caller_id_cover']}\""
        )
    return store.load_prompt("conversation") + "\n\nWho you are right now:\n\n" + "\n\n".join(dynamic)
