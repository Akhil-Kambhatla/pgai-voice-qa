"""Fetch a finished call's recording and transcribe it. Usage: fetch_and_transcribe.py <call_id>"""

import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, store, telnyx_client, transcribe


async def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: fetch_and_transcribe.py <call_id>")
    call_id = sys.argv[1]

    call_dir = store.resolve_call_dir(call_id)
    record_path = os.path.join(call_dir, "call.json")
    if not os.path.exists(record_path):
        sys.exit(f"No call record at {record_path}")

    with open(record_path) as f:
        record = json.load(f)
    placed_at = datetime.fromisoformat(record["placed_at"])

    print("Polling for recording (they appear a minute or two after the call ends)...")
    recording = await telnyx_client.find_recording(call_id, placed_at)
    print(f"Found recording {recording['sid']} ({recording['duration']}s, "
          f"{recording['channels']} channels)")

    mp3_path = os.path.join(call_dir, "recording.mp3")
    await telnyx_client.download_recording(recording["media_url"], mp3_path)
    print(f"Downloaded {mp3_path}")

    record["recording"] = {k: recording[k] for k in ("sid", "start_time", "duration", "channels")}
    with open(record_path, "w") as f:
        json.dump(record, f, indent=2)

    txt_path = transcribe.transcribe_recording(mp3_path)
    print(txt_path)


if __name__ == "__main__":
    asyncio.run(main())
