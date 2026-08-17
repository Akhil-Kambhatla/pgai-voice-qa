"""Transcribe a stereo call recording with Deepgram Nova-3, multichannel."""

import json
import os

from deepgram import DeepgramClient

from src import config

# Which stereo channel carries which side of the call. Verified empirically on the
# 2026-08-17 test call (recording 6cbbb209): channel 1 carries our bot (the caller),
# channel 0 carries the callee (the agent under test).
BOT_CHANNEL = 1
AGENT_CHANNEL = 0

_LABELS = {BOT_CHANNEL: "BOT", AGENT_CHANNEL: "AGENT"}


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def transcribe_recording(mp3_path: str) -> str:
    """Transcribe a stereo mp3; write transcript.json and transcript.txt next to it.

    Returns the path to transcript.txt.
    """
    client = DeepgramClient(api_key=config.DEEPGRAM_API_KEY)
    with open(mp3_path, "rb") as f:
        audio = f.read()

    response = client.listen.v1.media.transcribe_file(
        request=audio,
        model="nova-3",
        multichannel=True,
        punctuate=True,
        smart_format=True,
        utterances=True,
    )
    raw = response.dict()

    out_dir = os.path.dirname(os.path.abspath(mp3_path))
    json_path = os.path.join(out_dir, "transcript.json")
    txt_path = os.path.join(out_dir, "transcript.txt")

    with open(json_path, "w") as f:
        json.dump(raw, f, indent=2, default=str)

    utterances = (raw.get("results") or {}).get("utterances") or []
    lines = []
    for u in sorted(utterances, key=lambda u: u.get("start", 0.0)):
        text = (u.get("transcript") or "").strip()
        if not text:
            continue
        label = _LABELS.get(u.get("channel"), f"CH{u.get('channel')}")
        lines.append(f"[{_fmt_ts(u.get('start', 0.0))}] {label}: {text}")

    with open(txt_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return txt_path
