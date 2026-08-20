import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import call_exit, config, persona, store, transcribe

REAL_SCENARIO = "01-past-hours-akhil"
CLINIC_SCOPE = "Your own life runs the other way."
STATIC_TOKEN_RANGE = (600, 900)


def approximate_tokens(text):
    return round(len(text) / 4)


def ngrams(text, size):
    words = re.findall(r"[a-z']+", text.lower())
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def prompt_assembly():
    scenario = store.load_scenario(REAL_SCENARIO)
    instructions = persona.build_instructions(scenario, "smoke")
    assert CLINIC_SCOPE in instructions, "clinic-scope paragraph missing or reworded"

    outside_persona = instructions.replace(scenario["persona_block"], "")
    stray = persona.THIRD_PERSON.findall(outside_persona)
    assert not stray, f"third-person pronouns referring to the caller: {stray}"

    assert "The first one" in instructions and "before there is anything to set it against" in instructions, \
        "conversation.md no longer says the first fact counts"
    tool_description = next(
        t.description for t in _tool_schemas() if t.name == "silent_compare"
    )
    assert "first such fact of the call" in tool_description, \
        "silent_compare tool description no longer says the first fact counts"

    for name in ("silent_compare", "silent_note", "hang_up"):
        assert name in instructions, f"{name} missing from the assembled prompt"

    static = store.load_prompt("conversation")
    tokens = approximate_tokens(static)
    low, high = STATIC_TOKEN_RANGE
    assert low <= tokens <= high, \
        f"static prompt is about {tokens} tokens, outside the {low} to {high} target"


def _tool_schemas():
    from src.bot_tools import build_tools

    class Logger:
        turns = []

        def stalled(self):
            return False

    scenario = {"goal": "g", "facts_to_elicit": [], "claims_to_verify": []}
    return build_tools("smoke", Logger(), scenario, None, None)


def payload_hygiene():
    goal = store.load_scenario(REAL_SCENARIO)["goal"]
    goal_four_grams = ngrams(goal, 4)
    payloads = [
        {"hangup": "denied", "unmet": [call_exit.UNMET_GOAL]},
        {"hangup": "denied", "unmet": [call_exit.UNMET_CLAIM]},
        {"unmet": [call_exit.UNMET_GOAL], "nudge": 1},
        {"unmet": [call_exit.UNMET_CLAIM], "nudge": 2},
    ]
    for payload in payloads:
        text = json.dumps(payload)
        assert not (ngrams(text, 4) & goal_four_grams), f"{text} quotes the scenario goal"
        assert not re.search(r"[a-z]+\s+[a-z]+\s+[a-z]+\s+[a-z]+", text, re.IGNORECASE), \
            f"{text} contains an English sentence"
        for code in payload["unmet"]:
            assert code and len(code.split()) == 1, f"{text} carries a non-code: {code!r}"


def transcription_mapping():
    assert transcribe.BOT_CHANNEL == 1, f"BOT_CHANNEL is {transcribe.BOT_CHANNEL}, want 1"
    assert transcribe.AGENT_CHANNEL == 0, f"AGENT_CHANNEL is {transcribe.AGENT_CHANNEL}, want 0"
    assert transcribe._LABELS[1] == "BOT" and transcribe._LABELS[0] == "AGENT", transcribe._LABELS


def call_tree_resolution():
    campaign_calls = config.CALL_TREES["campaign"][0]
    roleplay_calls = config.CALL_TREES["roleplay"][0]
    assert config.CALLS_DIR == campaign_calls, f"new calls would land in {config.CALLS_DIR}"

    resolved = store.resolve_call_dir("call-14")
    assert resolved == os.path.join(roleplay_calls, "call-14"), resolved

    shared = os.path.join(campaign_calls, "call-14")
    os.makedirs(shared, exist_ok=True)
    try:
        store.resolve_call_dir("call-14")
        raise AssertionError("an id in both trees resolved silently")
    except SystemExit as error:
        assert "campaign/call-14" in str(error) and "roleplay/call-14" in str(error), str(error)
    finally:
        os.rmdir(shared)
