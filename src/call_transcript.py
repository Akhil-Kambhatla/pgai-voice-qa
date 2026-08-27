import json
import os
import re

TRANSCRIPT_LINE = re.compile(r"^\[(\d+):(\d\d)\]\s+(AGENT|BOT):\s*(.*)$")


def clock(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_timestamp(text):
    minutes, _, seconds = (text or "0:00").partition(":")
    return int(minutes) * 60 + int(seconds)


def read_transcript(call_dir):
    lines = []
    with open(os.path.join(call_dir, "transcript.txt")) as handle:
        for raw in handle:
            match = TRANSCRIPT_LINE.match(raw.strip())
            if match:
                minutes, seconds, speaker, text = match.groups()
                lines.append({
                    "at_seconds": int(minutes) * 60 + int(seconds),
                    "speaker": speaker,
                    "text": text,
                })
    return lines


def render_lines(lines):
    return "\n".join(
        f"[{clock(line['at_seconds'])}] {line['speaker']}: {line['text']}" for line in lines
    )


def call_ending(record, call_dir):
    durations = [
        int(event["CallDuration"])
        for event in record.get("status_events") or []
        if event.get("CallDuration")
    ]
    last_status = (record.get("status_events") or [{}])[-1]
    exits = set()
    events_path = os.path.join(call_dir, "events.jsonl")
    if os.path.exists(events_path):
        with open(events_path) as handle:
            for raw in handle:
                kind = (json.loads(raw).get("event") or {}).get("type") or ""
                if kind.startswith("exit."):
                    exits.add(kind)
    return {
        "duration_seconds": max(durations) if durations else None,
        "end_time": last_status.get("EndTime"),
        "hangup_source": last_status.get("HangupSource"),
        "hangup_cause": last_status.get("HangupCause"),
        "exit_events": sorted(exits),
    }
