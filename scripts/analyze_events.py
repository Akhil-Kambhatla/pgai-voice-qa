import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

RECEPTIONIST_PHRASES = [
    "let me check",
    "let me look",
    "one moment",
    "that makes sense",
    "thanks for the answer",
    "how can i help",
    "bear with me",
    "i'll pull that up",
]


def load_events(call_id):
    path = os.path.join(config.CALLS_DIR, call_id, "events.jsonl")
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_turns(call_id):
    path = os.path.join(config.CALLS_DIR, call_id, "turns.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def q1_responses_vs_turns(events):
    created = [e for e in events if e["source"] == "server" and e["type"] == "response.created"]
    client_creates = [e for e in events if e["source"] == "client" and e["type"] == "response.create"]
    committed = [e for e in events if e["source"] == "server" and e["type"] == "input_audio_buffer.committed"]
    transcripts = [
        e
        for e in events
        if e["source"] == "server"
        and e["type"] == "conversation.item.input_audio_transcription.completed"
    ]
    print("Q1 duplicate generation")
    print(f"  response.created (server): {len(created)}")
    print(f"  response.create (sent by our code): {len(client_creates)}")
    print(f"  server-auto responses (created minus client-sent): {len(created) - len(client_creates)}")
    print(f"  input_audio_buffer.committed (user turns): {len(committed)}")
    print(f"  user transcriptions completed: {len(transcripts)}")
    for e in created:
        print(f"    t={e['t']} response_id={e['event'].get('response', {}).get('id')}")
    for e in client_creates:
        print(f"    t={e['t']} CLIENT response.create event_id={e['event'].get('event_id')}")


def q2_item_roles(events):
    print("Q2 conversation item roles")
    counts = {}
    for e in events:
        if e["source"] != "server" or e["type"] not in ("conversation.item.added", "conversation.item.created"):
            continue
        item = e["event"].get("item", {})
        role = item.get("role")
        item_type = item.get("type")
        content_types = [c.get("type") for c in (item.get("content") or [])]
        counts[(role, item_type)] = counts.get((role, item_type), 0) + 1
        print(f"  t={e['t']} id={item.get('id')} role={role} type={item_type} content={content_types}")
    print(f"  totals: {counts}")


def q3_opening_line(events, scenario_id):
    print("Q3 opening line path")
    opening = ""
    scenario_path = os.path.join(config.SCENARIOS_DIR, f"{scenario_id}.json")
    if os.path.exists(scenario_path):
        with open(scenario_path) as f:
            opening = json.load(f).get("opening_line", "")
    updates = [e for e in events if e["source"] == "client" and e["type"] == "session.update"]
    for e in updates:
        instructions = e["event"].get("session", {}).get("instructions") or ""
        print(f"  t={e['t']} session.update instructions_len={len(instructions)} contains_opening={opening[:30] in instructions}")
    seeds = [e for e in events if e["source"] == "client" and e["type"] == "conversation.item.create"]
    for e in seeds:
        item = e["event"].get("item", {})
        print(f"  t={e['t']} CLIENT conversation.item.create role={item.get('role')} type={item.get('type')}")
    firsts = [e for e in events if e["type"] == "response.output_audio_transcript.done"][:3]
    for e in firsts:
        print(f"  t={e['t']} bot transcript: {e['event'].get('transcript')!r}")


def q4_deletions(events):
    print("Q4 history deletions")
    deletes = [e for e in events if e["source"] == "client" and e["type"] == "conversation.item.delete"]
    if not deletes:
        print("  0 deletions")
        return
    in_flight = False
    windows = []
    for e in events:
        if e["type"] == "response.created":
            in_flight = True
        elif e["type"] == "response.done":
            in_flight = False
        elif e["source"] == "client" and e["type"] == "conversation.item.delete":
            windows.append((e["t"], e["event"].get("item_id"), in_flight))
    for t, item_id, flight in windows:
        print(f"  t={t} deleted item_id={item_id} response_in_flight={flight}")


def conversation_quality(turns):
    print("Conversation quality")
    bot_turns = [t for t in turns if t["speaker"] == "bot"]
    longest = max((len(t["text"].split()) for t in bot_turns), default=0)
    print(f"  bot turns: {len(bot_turns)}")
    print(f"  longest bot turn (words): {longest}")
    asked = {}
    for t in bot_turns:
        key = tuple(sorted(w for w in re.findall(r"[a-z]{4,}", t["text"].lower())))[:6]
        asked[key] = asked.get(key, 0) + 1
    print(f"  repeated topic signatures: {sum(1 for v in asked.values() if v > 1)}")
    flagged = [t["text"] for t in bot_turns if any(p in t["text"].lower() for p in RECEPTIONIST_PHRASES)]
    print(f"  receptionist-side utterances: {len(flagged)}")
    for text in flagged:
        print(f"    {text!r}")


def main():
    call_id = sys.argv[1]
    scenario_id = sys.argv[2] if len(sys.argv) > 2 else ""
    events = load_events(call_id)
    print(f"=== {call_id}: {len(events)} recorded events ===")
    q1_responses_vs_turns(events)
    q2_item_roles(events)
    q3_opening_line(events, scenario_id)
    q4_deletions(events)
    conversation_quality(load_turns(call_id))


main()
