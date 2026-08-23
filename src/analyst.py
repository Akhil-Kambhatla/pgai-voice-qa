import json
import os
from datetime import datetime, timezone

from openai import OpenAI

from src import config, ledgers, store


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


def _write_extraction_record(call_id, extracted, changes, skipped):
    record = {
        "call_id": call_id,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "model": config.PLANNER_MODEL,
        "returned_counts": {bucket: len(items) for bucket, items in extracted.items()},
        "raw": extracted,
        "applied": changes,
        "skipped": skipped,
    }
    path = os.path.join(store.resolve_call_dir(call_id), "extraction.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2)


def analyze_call(call_id):
    record, transcript, turns = _read_call_inputs(call_id)
    extracted = _extract(transcript, turns)

    oracle_data = store.load("oracle", ledgers.empty_oracle())
    claims = store.load("claims", [])
    promises = store.load("promises", [])
    capabilities = store.load("capabilities", [])
    suspicions = store.load("suspicions", [])
    frontier = store.load("frontier", [])
    identity = record.get("identity")
    changes = []

    skipped = ledgers.apply_facts(extracted.get("facts", []), call_id, oracle_data, suspicions, changes)
    ledgers.apply_claims(extracted.get("claims", []), call_id, identity, claims, changes)
    ledgers.apply_promises(extracted.get("promises", []), call_id, identity, promises, changes)
    ledgers.apply_capabilities(extracted.get("capabilities", []), call_id, capabilities, changes)
    skipped += ledgers.apply_entities(extracted.get("entities", []), call_id, frontier, changes)
    _write_extraction_record(call_id, extracted, changes, skipped)

    store.save("oracle", oracle_data)
    store.save("claims", claims)
    store.save("promises", promises)
    store.save("capabilities", capabilities)
    store.save("suspicions", suspicions)
    store.save("frontier", frontier)
    return changes
