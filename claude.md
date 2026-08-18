# CLAUDE.md

## What this project is

An autonomous voice QA agent. It phone-calls a company's patient-facing AI voice
agent, holds a natural conversation as a patient, records and transcribes both
sides, and reports bugs in the company agent's behaviour.

Target number for all calls: `+18054398008`
Caller ID for all calls: `+12078048142` (Telnyx)
Company demo clinic: Pivot Point Orthopedics (fictional, no public website)

This is a take-home assessment. It is graded on: whether the bot holds a coherent
voice conversation, the quality of bugs found, whether the code actually makes
real calls, and how clearly the architecture is reasoned about. It is explicitly
NOT graded on production infrastructure or perfect code.

## Hard rules

1. **No comments in code.** No inline comments, no block comments, no docstrings.
   Use descriptive names instead. This is not negotiable.
2. **No emoji anywhere.** Not in code, not in output, not in commit messages.
3. **Never guess a library API.** Before writing code against `pipecat`, `telnyx`,
   `deepgram`, or `openai`, grep the installed package in `.venv/lib/python3.12/site-packages/`
   to confirm the class name, constructor signature, and import path. A wrong import
   costs more than a grep.
4. **Never commit secrets.** `.env` stays in `.gitignore`. `.env.example` has keys
   with empty values only.
5. **Keep files under 150 lines.** Split before that.
6. **Do not add features that were not asked for.** No retry frameworks, no logging
   abstractions, no config validation layers beyond what the task specifies.
7. **Never call the target number during development.** Test against a personal
   number passed on the command line. Calls to `+18054398008` are only made when
   explicitly instructed.

## Closed-loop iteration protocol

This is how every task in this project is executed. Follow it without being asked.

Every task has a **verification command** stated in the prompt, or one you state
explicitly before starting if the prompt does not give one.

```
1. State the verification command.
2. Write or change code.
3. Run the verification command.
4. Read the actual output. Not what you expected, what it printed.
5. If it passed, stop. Report in two lines: what changed, what verified.
6. If it failed, fix and go to 3. Do not ask permission between attempts.
7. After 5 failed attempts, stop. Report: the last error verbatim, each fix you
   tried, and your best hypothesis. Do not keep going.
```

Do not ask "should I proceed?" mid-loop. Do not narrate each attempt. Iterate
silently and report once at the end.

## Token discipline

- Do not re-read a file already in context this session.
- Use targeted `grep` instead of printing whole files.
- Edit files in place. Do not rewrite a file to change three lines.
- Do not summarise what you just did in more than two sentences.
- Do not restate the task back before starting it.
- Do not print code you just wrote back into the chat.

## Environment facts (verified, do not re-derive)

- macOS. Python 3.12 via `uv`, in a venv at `.venv`. Conda `(base)` may be active
  in the shell; it must not be used. If `.venv` was built on Anaconda Python,
  rebuild with `uv venv --python 3.12`.
- Pipecat 1.7.0.
- ngrok free tier forwards to port 7860. The forwarding URL changes on every
  restart and lives in `.env` as `PUBLIC_BASE_URL`.
- The local machine cannot reach `*.ngrok-free.dev` over TLS. Telnyx can.
  Trigger calls against `http://localhost:7860` and never depend on fetching the
  public URL from this machine.
- The server must read its public URL from `PUBLIC_BASE_URL`, never from the
  request `Host` header.
- Pipecat must be imported at module load time, not inside a websocket handler.
  Lazy import blocks long enough that Telnyx closes the stream and the call fails.
- The pipeline runs at 24kHz, not 8kHz. OpenAI realtime requires PCM16 at 24kHz,
  and `TelnyxFrameSerializer` handles the 8k to 24k conversion at the wire. Running
  the pipeline at 8k feeds OpenAI 3x-slowed audio: VAD never fires and the bot is
  silent.
- Reference example: `~/Desktop/pgai-reference/telnyx-chatbot/outbound/`. Its server
  may still hold port 7860; check before starting ours.

## Telnyx facts (verified)

- TeXML app is configured, number assigned, outbound voice profile attached.
- Outbound calls are created with `POST https://api.telnyx.com/v2/texml/Accounts/{account_sid}/Calls`
  using form or JSON fields `ApplicationSid`, `To`, `From`, `Url`, `StatusCallback`.
- Server-side recording is enabled on the outbound voice profile and produces a
  **stereo 8kHz MP3** containing both parties, one per channel. Do not implement
  local audio capture.
- Transcribe channel map (verified on the 2026-08-17 test call): channel 1 is our
  bot (the caller), channel 0 is the callee (the agent under test).
- Recordings are trunk-level dual-channel with `call_sid` null and no phone numbers
  in the metadata, so a recording cannot be matched to a call by ID. Match by the
  most recent completed recording whose start time is at or after call placement.
- TeXML served on answer must be:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://HOST/ws" bidirectionalMode="rtp"></Stream>
  </Connect>
  <Pause length="40"/>
</Response>
```

  The `<Pause>` is required. Without it the call terminates the moment the stream
  ends.

## Spend guards (never remove these)

- `MAX_CALL_SECONDS` (default 240) enforced by a timer in code that hangs the call
  up. Not a prompt instruction to the model.
- `MAX_CALLS_PER_RUN` (default 6) enforced by a counter that refuses to dial past it.
- Telnyx side already has: channel limit 2, max destination rate $0.10, daily
  spend limit $3.

## Commit convention

Small, single-purpose commits. Imperative subject line, no body unless the change
is non-obvious. No emoji. Example: `add telnyx outbound call client`.