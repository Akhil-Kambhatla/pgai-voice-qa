import base64
import json

from fastapi import WebSocket

from src import store


def decode_body(websocket: WebSocket) -> dict:
    raw = websocket.query_params.get("body")
    if not raw:
        return {}
    return json.loads(base64.b64decode(raw))


def build_instructions(scenario: dict) -> str:
    identity = store.load("identities", {}).get(scenario["identity"], {})
    dynamic = [
        scenario["persona_block"],
        f"Your details, and the only identifying details you may ever give: "
        f"name {identity.get('name')}, date of birth {identity.get('dob')}.",
        f"Your goal for this call: {scenario['goal']}",
        f"Open with something like: \"{scenario['opening_line']}\"",
    ]
    if scenario.get("opportunistic_follow_up"):
        dynamic.append(f"One instinct to keep in your back pocket: {scenario['opportunistic_follow_up']}")
    if scenario.get("caller_id_cover"):
        dynamic.append(
            f"If they address you by a different name because of your phone number, "
            f"say something like: \"{scenario['caller_id_cover']}\""
        )
    return store.load_prompt("conversation") + "\n\nWho you are right now:\n\n" + "\n\n".join(dynamic)
