import json
import os

from openai import OpenAI

from src import config, oracle, store


def _read_call_inputs(call_id):
    call_dir = store.resolve_call_dir(call_id)
    with open(os.path.join(call_dir, "call.json")) as f:
        record = json.load(f)
    transcript_path = os.path.join(call_dir, "transcript.txt")
    transcript = ""
    if os.path.exists(transcript_path):
        with open(transcript_path) as f:
            transcript = f.read()
    turns_path = os.path.join(call_dir, "turns.jsonl")
    turns = ""
    if os.path.exists(turns_path):
        with open(turns_path) as f:
            turns = f.read()
    if not transcript and not turns:
        raise FileNotFoundError(f"No transcript.txt or turns.jsonl for {call_id}")
    return record, transcript, turns


def _extract(transcript, turns):
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    user_content = f"Transcript:\n{transcript}\n\nLive turn log (fallback view of the same call):\n{turns}"
    response = client.chat.completions.create(
        model=config.PLANNER_MODEL,
        messages=[
            {"role": "system", "content": store.load_prompt("analyst")},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _next_id(items, prefix):
    return f"{prefix}-{len(items) + 1:02d}"


def _apply_facts(facts, call_id, oracle_data, suspicions, changes):
    for fact in facts:
        slot, value, at = fact.get("slot"), fact.get("value"), fact.get("at")
        if slot not in oracle_data or not value:
            continue
        entry = oracle_data[slot]
        if not entry["value"]:
            oracle_data[slot] = {
                "value": value, "stated_in": call_id, "at": at, "times_stated": 1,
            }
            changes.append(f"oracle: {slot} filled from {call_id} at {at}")
        elif oracle.compare_statements(value, str(entry["value"])) == "conflict":
            suspicion = {
                "id": _next_id(suspicions, "susp"),
                "description": (
                    f"Contradiction on {slot}: said \"{entry['value']}\" in "
                    f"{entry['stated_in']} at {entry['at']}, but \"{value}\" in {call_id} at {at}"
                ),
                "axes_involved": {},
                "confidence": 0.6,
                "severity": "high",
                "seen_in": [entry["stated_in"], call_id],
                "status": "suspected",
            }
            suspicions.append(suspicion)
            changes.append(f"suspicion: {suspicion['id']} ({slot} contradiction)")
        elif oracle.is_more_specific(value, str(entry["value"])):
            entry.update({"value": value, "stated_in": call_id, "at": at})
            entry["times_stated"] += 1
            changes.append(f"oracle: {slot} sharpened from {call_id} at {at} to \"{value}\"")
        else:
            entry["times_stated"] += 1
            changes.append(f"oracle: {slot} restated consistently (times_stated={entry['times_stated']})")


def _apply_claims(extracted_claims, call_id, identity, claims, changes):
    for item in extracted_claims:
        claim = {
            "id": _next_id(claims, "claim"),
            "text": item.get("text"),
            "identity": identity,
            "call_id": call_id,
            "at": item.get("at"),
            "status": "unverified",
        }
        claims.append(claim)
        changes.append(f"claim: {claim['id']} unverified ({claim['text']})")


def _apply_entities(entities, call_id, frontier, changes):
    known = {e["name"].lower() for e in frontier}
    for entity in entities:
        name = (entity.get("name") or "").strip()
        if not name or name.lower() in known:
            continue
        frontier.append(
            {"name": name, "kind": entity.get("kind", "other"), "mentioned_in": call_id, "probed": False}
        )
        known.add(name.lower())
        changes.append(f"frontier: {name} ({entity.get('kind')}) unprobed")


def analyze_call(call_id):
    record, transcript, turns = _read_call_inputs(call_id)
    extracted = _extract(transcript, turns)

    oracle_data = store.load("oracle", {})
    claims = store.load("claims", [])
    suspicions = store.load("suspicions", [])
    frontier = store.load("frontier", [])
    changes = []

    _apply_facts(extracted.get("facts", []), call_id, oracle_data, suspicions, changes)
    _apply_claims(extracted.get("claims", []), call_id, record.get("identity"), claims, changes)
    _apply_entities(extracted.get("entities", []), call_id, frontier, changes)

    store.save("oracle", oracle_data)
    store.save("claims", claims)
    store.save("suspicions", suspicions)
    store.save("frontier", frontier)
    return changes
