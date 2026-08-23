import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import store

AUDIO_START_TYPES = ("response.output_audio_transcript.delta", "response.output_audio.delta")
LEDGER_PREFIXES = ("oracle", "claim", "promise", "capability", "suspicion", "frontier")


def _load_jsonl(call_dir, name):
    path = os.path.join(call_dir, name)
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _load_json(call_dir, name, default):
    path = os.path.join(call_dir, name)
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        return json.load(handle)


def latencies(events):
    stops = [e["t"] for e in events if e.get("type") == "input_audio_buffer.speech_stopped"]
    audio = sorted(e["t"] for e in events if e.get("type") in AUDIO_START_TYPES)
    gaps = []
    for stop in stops:
        after = [t for t in audio if t >= stop]
        if after:
            gaps.append(after[0] - stop)
    return gaps


def ending(events, completion):
    granted = [e for e in events if (e.get("event") or {}).get("type") == "exit.hangup_granted"]
    denied = [e for e in events if (e.get("event") or {}).get("type") == "exit.hangup_denied"]
    watchdog = [e for e in events if (e.get("event") or {}).get("type") == "exit.watchdog_terminated"]
    if granted:
        condition = granted[-1]["event"].get("grant_condition")
        return f"hang_up granted at {granted[-1]['t']:.1f}s", condition, len(denied)
    if watchdog:
        return "watchdog terminated the call at MAX_CALL_SECONDS", "watchdog", len(denied)
    source = (completion or {}).get("hangup_source")
    if source == "callee":
        return "far end hung up first", "none, the agent dropped the call", len(denied)
    return "ended without a recorded grant", "none", len(denied)


def summarise(call_id, completion=None):
    call_dir = store.resolve_call_dir(call_id)
    events = _load_jsonl(call_dir, "events.jsonl")
    turns = _load_jsonl(call_dir, "turns.jsonl")
    record = _load_json(call_dir, "call.json", {})
    extraction = _load_json(call_dir, "extraction.json", {})

    if completion is None:
        for event in record.get("status_events", []):
            if event.get("CallStatus") == "completed":
                completion = {
                    "duration": int(event.get("CallDuration") or 0),
                    "hangup_source": event.get("HangupSource"),
                }
                break

    how, condition, denials = ending(events, completion)
    gaps = latencies(events)
    speakers = {"bot": 0, "agent": 0, "tool": 0}
    for turn in turns:
        speakers[turn.get("speaker", "tool")] = speakers.get(turn.get("speaker", "tool"), 0) + 1
    tool_calls = [json.loads(t["text"])["name"] for t in turns if t.get("speaker") == "tool"]
    truncations = len([e for e in events if e.get("type") == "conversation.item.truncated"])
    barge_ins = len([e for e in events if e.get("type") == "conversation.item.truncate"])

    applied = extraction.get("applied", [])
    ledger_counts = {prefix: 0 for prefix in LEDGER_PREFIXES}
    for line in applied:
        head = line.split(":", 1)[0]
        if head in ledger_counts:
            ledger_counts[head] += 1

    duration = (completion or {}).get("duration")
    lines = [
        "=" * 78,
        f"CALL SUMMARY  {call_id}   scenario {record.get('scenario_id')}   identity {record.get('identity')}",
        "=" * 78,
        f"  duration        {duration if duration is not None else 'unknown'}s",
        f"  ended           {how}",
        f"  grant condition {condition}",
        f"  hangup source   {(completion or {}).get('hangup_source') or 'unknown'}",
        f"  hang_up denials {denials}",
        "",
        f"  turns           {speakers.get('agent', 0)} agent, {speakers.get('bot', 0)} bot, "
        f"{speakers.get('tool', 0)} tool",
        f"  tool calls      {', '.join(tool_calls) if tool_calls else 'none'}",
        f"  barge-ins       {barge_ins} sent, {truncations} confirmed truncations",
        "",
    ]
    if gaps:
        lines.append(
            f"  latency         min {min(gaps):.2f}s   median {statistics.median(gaps):.2f}s   "
            f"max {max(gaps):.2f}s   over {len(gaps)} turns"
        )
        lines.append("                  measured speech_stopped to first transcript delta")
    else:
        lines.append("  latency         no paired speech_stopped and audio events")
    lines.append("")
    lines.append("  extraction added")
    if applied:
        for prefix in LEDGER_PREFIXES:
            if ledger_counts[prefix]:
                lines.append(f"    {prefix:12} {ledger_counts[prefix]}")
        for line in applied:
            lines.append(f"      {line}")
    else:
        lines.append("    nothing")
    skipped = extraction.get("skipped", [])
    if skipped:
        lines.append(f"  extraction skipped {len(skipped)}")
        for item in skipped:
            lines.append(f"      {item.get('bucket')}: {item.get('reason')}")
    lines.append("=" * 78)
    return "\n".join(lines)
