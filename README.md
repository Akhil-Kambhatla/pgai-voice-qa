# pgai — voice QA agent scaffold

Places an outbound phone call through Telnyx, holds a conversation with an OpenAI
realtime speech-to-speech model over Pipecat, then fetches the stereo call
recording and transcribes both sides with Deepgram.

## Setup

```
uv venv --python 3.12 && uv sync
cp .env.example .env   # then fill in keys; PUBLIC_BASE_URL is your ngrok https URL
```

ngrok must be forwarding the `PUBLIC_BASE_URL` domain to `localhost:7860`.

## Run

Start the server:

```
uv run python src/server.py
```

Place a call (prints the `call_id`):

```
uv run python scripts/place_call.py +1XXXXXXXXXX
```

After the call ends, fetch the recording and transcript:

```
uv run python scripts/fetch_and_transcribe.py <call_id>
```

Output lands in `data/calls/<call_id>/`: `call.json`, `recording.mp3`,
`transcript.json`, `transcript.txt`.
