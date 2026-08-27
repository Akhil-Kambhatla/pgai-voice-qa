import json

from openai import OpenAI

from src import config, store

KINDS = ("vacuous", "out_of_band", "in_call")


def _ask_model(promises):
    described = [
        {"promise_id": p["id"], "text": p.get("text"), "action": p.get("action")}
        for p in promises
    ]
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.PLANNER_MODEL,
        messages=[
            {"role": "system", "content": store.load_prompt("promise_kind")},
            {"role": "user", "content": json.dumps(described, indent=2)},
        ],
        response_format={"type": "json_object"},
    )
    returned = json.loads(response.choices[0].message.content).get("kinds") or []
    return {item.get("promise_id"): item for item in returned}


def classify(promises, ask=_ask_model):
    if not promises:
        return {}
    returned = ask(promises)
    classified = {}
    for promise in promises:
        item = returned.get(promise["id"]) or {}
        kind, note = item.get("kind"), None
        if kind not in KINDS:
            note = f"classifier returned an unusable kind {kind!r}; treated as an in-call promise"
            kind = "in_call"
        classified[promise["id"]] = {
            "kind": kind,
            "why": item.get("why"),
            "note": note,
        }
    return classified
