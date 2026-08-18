import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, store

INTERNAL_TOOL_MARKERS = ("status", "instruction", "noted")
LEAK_PHRASES = [
    "let me check", "let me look", "look that up", "looking that up", "pull that up",
    "one moment", "for a moment", "give me a second", "bear with me", "on my end",
    "our records", "my records", "in the system", "i'll check", "let me verify",
    "wrap up here", "actual question", "do not ask", "already asked", "still need",
]
RECEPTIONIST_PHRASES = [
    "how can i help", "how may i help", "for you", "anything else for you",
    "i can get that", "let me get that", "i'll take care of", "we're open", "we are open",
    "our hours are", "thanks for calling",
]


def load_jsonl(call_id, name):
    path = os.path.join(config.CALLS_DIR, call_id, name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def response_ownership(events):
    created = [e for e in events if e["source"] == "server" and e["type"] == "response.created"]
    client_created = [e for e in events if e["source"] == "client" and e["type"] == "response.create"]
    user_turns = [e for e in events if e["source"] == "server" and e["type"] == "input_audio_buffer.committed"]
    print("RESPONSE OWNERSHIP")
    print(f"  distinct user turns (buffer committed): {len(user_turns)}")
    print(f"  response.created total:                 {len(created)}")
    print(f"  response.create sent by our code:       {len(client_created)}")
    print(f"  server-turn-detection responses:        {len(created) - len(client_created)}")
    print(f"  ratio responses per user turn:          {len(created) / max(len(user_turns), 1):.2f}")
    return len(created), len(user_turns), len(client_created)


def tool_forced_speech(events):
    print("TOOL-FORCED SPEECH")
    results = [
        e for e in events
        if e["source"] == "client" and e["type"] == "conversation.item.create"
        and (e["event"].get("item") or {}).get("type") == "function_call_output"
    ]
    created = [e for e in events if e["source"] == "server" and e["type"] == "response.created"]
    forced = 0
    for r in results:
        following = [c for c in created if 0 <= c["t"] - r["t"] <= 0.5]
        if following:
            forced += 1
            print(f"  t={r['t']:.2f} tool result -> response.created at t={following[0]['t']:.2f}")
    print(f"  internal tool results: {len(results)}")
    print(f"  responses created within 500ms of a tool result: {forced}")
    return forced


def narration_in_tool_turns(events):
    print("TOOL-TURN NARRATION")
    count = 0
    for e in events:
        if e["type"] != "response.done":
            continue
        output = [o.get("type") for o in (e["event"].get("response") or {}).get("output", [])]
        if "message" in output and "function_call" in output:
            count += 1
            print(f"  t={e['t']:.2f} response spoke AND called a tool: {output}")
    print(f"  responses mixing speech with a tool call: {count}")
    return count


def latency(events):
    stops = [e["t"] for e in events if e["type"] == "input_audio_buffer.speech_stopped"]
    audio = [e["t"] for e in events if e["type"] in
             ("response.output_audio_transcript.delta", "response.output_audio.delta")]
    gaps = []
    for stop in stops:
        after = [a for a in audio if a >= stop]
        if after:
            gaps.append(after[0] - stop)
    print("LATENCY")
    for stop, gap in zip(stops, gaps):
        print(f"  speech_stopped t={stop:.2f} -> first audio +{gap:.2f}s")
    median = statistics.median(gaps) if gaps else 0.0
    print(f"  median speech-stopped to first-audio: {median:.2f}s")
    print(f"  max: {max(gaps):.2f}s" if gaps else "  max: n/a")
    return median


def tool_roundtrip(events):
    print("TOOL ROUND-TRIP")
    calls = [e for e in events if e["type"] == "response.function_call_arguments.done"]
    outs = [e for e in events if e["source"] == "client" and e["type"] == "conversation.item.create"
            and (e["event"].get("item") or {}).get("type") == "function_call_output"]
    trips = []
    for c in calls:
        after = [o for o in outs if o["t"] >= c["t"]]
        if after:
            trips.append(after[0]["t"] - c["t"])
            print(f"  {c['event'].get('name')} args_done t={c['t']:.2f} -> result sent +{trips[-1]:.2f}s")
    if trips:
        print(f"  median tool round-trip: {statistics.median(trips):.2f}s")
    return trips


def deletions(events):
    dels = [e for e in events if e["source"] == "client" and e["type"] == "conversation.item.delete"]
    print(f"DELETIONS\n  conversation.item.delete sent: {len(dels)}")
    for e in dels:
        print(f"  t={e['t']:.2f} item_id={e['event'].get('item_id')}")
    return len(dels)


def speech_quality(events, call_id, scenario_id):
    said = [(e["t"], e["event"].get("transcript") or "")
            for e in events if e["type"] == "response.output_audio_transcript.done"]
    print("SPEECH QUALITY")
    longest = max((len(t.split()) for _, t in said), default=0)
    print(f"  bot utterances: {len(said)}   longest turn (words): {longest}")
    leaks = [(t, x) for t, x in said if any(p in x.lower() for p in LEAK_PHRASES)]
    drift = [(t, x) for t, x in said if any(p in x.lower() for p in RECEPTIONIST_PHRASES)]
    print(f"  utterances with internal/tool/refusal phrasing: {len(leaks)}")
    for t, x in leaks:
        print(f"    t={t:.2f} {x!r}")
    print(f"  utterances in receptionist voice: {len(drift)}")
    for t, x in drift:
        print(f"    t={t:.2f} {x!r}")
    seen = {}
    dupes = 0
    for t, x in said:
        key = " ".join(sorted(w for w in x.lower().split() if len(w) > 3))[:60]
        if key in seen:
            dupes += 1
            print(f"    near-duplicate utterance t={t:.2f} of t={seen[key]:.2f}: {x!r}")
        seen[key] = t
    print(f"  near-duplicate utterances: {dupes}")
    goal_completion(call_id, scenario_id)
    return len(leaks), len(drift), dupes, longest


def goal_completion(call_id, scenario_id):
    if not scenario_id:
        return
    scenario = store.load_scenario(scenario_id)
    required = scenario.get("facts_to_elicit", [])
    tools = [json.loads(t["text"]) for t in load_jsonl(call_id, "turns.jsonl") if t["speaker"] == "tool"]
    ended = [t for t in tools if t["result"].get("hangup") == "ok" or t["result"].get("status") == "ending"]
    refused = [t for t in tools if t["result"].get("hangup") == "denied" or t["result"].get("status") == "refused"]
    blocked = [t for t in tools if t["result"].get("status") == "already_asked"]
    print(f"  required fact slots: {required}")
    print(f"  hangup accepted: {len(ended)}   denied: {len(refused)}   repeat-guard blocks: {len(blocked)}")
    print(f"  scenario goals completed before hangup: {bool(ended)}")


def main():
    call_id = sys.argv[1]
    scenario_id = sys.argv[2] if len(sys.argv) > 2 else ""
    events = load_jsonl(call_id, "events.jsonl")
    print(f"=== {call_id}: {len(events)} recorded events ===")
    response_ownership(events)
    tool_forced_speech(events)
    narration_in_tool_turns(events)
    latency(events)
    tool_roundtrip(events)
    deletions(events)
    speech_quality(events, call_id, scenario_id)


main()
