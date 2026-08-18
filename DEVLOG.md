# Development log

Bugs hit while building this system, and how they were resolved.
This is about my system. Defects found in the clinic agent are in BUGS.md.

## 1. Silent bot: sample rate mismatch
Symptom: call connected, both sides silent, bot never spoke.
Cause: pipeline ran at 8kHz because Telnyx media streaming is 8kHz at the wire.
The OpenAI realtime API requires PCM16 at 24kHz, so speech arrived as slowed
garble and the model's voice activity detection never fired.
Fix: run the pipeline at 24kHz. TelnyxFrameSerializer converts 8k to 24k at the
wire. This overrode my own written instruction, which was wrong.

## 2. Call never ended after the conversation finished
Symptom: bot said goodbye, call stayed open until the 240s cap.
Cause: nothing terminated the call except the timer.
Fix: added an end_call tool the model invokes deliberately. A transcript watcher
matching the word "goodbye" was kept only as a backstop, since string matching
misfires when a persona says "goodbye for now" mid-conversation.

## 3. First call after every server restart failed
Symptom: websocket accepted, then closed before the telephony handshake.
Cause: Pipecat was imported lazily inside the websocket handler. The import
blocked long enough that Telnyx gave up and hung up.
Fix: import at module load time so the server is warm before any call arrives.

## 4. Telnyx served a localhost callback URL
Symptom: call connected, Telnyx played "sorry, there has been some error".
Cause: the reference server built the TeXML URL from the incoming request's Host
header. Triggering calls against localhost meant Telnyx was told to fetch
instructions from localhost, which it cannot reach.
Fix: read the public URL from PUBLIC_BASE_URL instead of the request header.

## 5. Local machine cannot reach the ngrok domain
Symptom: curl and browser both fail against *.ngrok-free.dev with a TLS protocol
alert, while api.telnyx.com works fine over the same stack.
Cause: network-level interference specific to the tunnel domain.
Workaround: POST to http://localhost:7860 with a Host header spoofing the ngrok
domain. Telnyx reaches the tunnel from its own servers, so only local access is
affected. Fix 4 makes this cosmetic rather than load-bearing.

## 6. uv built the venv on Anaconda Python 3.13
Symptom: conda (base) active by default, venv inherited its interpreter.
Fix: uv venv --python 3.12 for a standalone interpreter.

## 7. Port 7860 held by a stale process
Cause: the reference example's server was still running.
Fix: kill it before starting the project server.

## 8. Spend guard reset on every restart
Cause: MAX_CALLS_PER_RUN lived in process memory, and the server restarts often.
Fix: persist to data/call_counter.json, keyed by UTC date, so it is a daily cap.

## 9. Scaffold calls inflated the call index
Fix: archived prompt-1 test calls to data/calls_scaffold/.

## 10. Bot spoke for ten seconds after end_call resolved
Symptom: end_call returned "ending" at 76.7s; bot still speaking at 81.3s, and the
speech was incoherent because two half-finished thoughts were spliced.
Cause: EndFrame did not cancel in-flight or queued speech.

## 11. Bot behaved as the scheduler rather than the caller
Symptom: asked the receptionist when they would like to set the appointment.
Cause: instructions described conversational behaviour without establishing that
the caller is the one who needs something.

## 12. Bot narrated its own comprehension
Symptom: "I caught most of what you said", "I want to be sure my understanding
matches". No human says this on a phone call.

## 13. Bot repeated a question the same call
Symptom: asked whether the clinic was open right now at 9.7s and again at 55.7s.
Cause: the anti-fixation guard lived in the oracle's already_confirmed branch,
which cannot fire while the oracle is empty, which is exactly when discovery
calls run.

## 14. end_call fired before the scenario goal was met
Symptom: scenario required hours and closed_days; bot obtained hours and hung up.

## 15. check_fact received compound claims
Symptom: three assertions in one claim string, which cannot map to an oracle slot.
## 16. Duplicate opening line, 1.8s apart
Symptom: bot spoke the opening at 19.1s and again at 20.9s.
Cause: two response owners. Semantic VAD on the server creates a response when
the caller's turn ends, and pipecat's `_handle_context` calls `_create_response()`
the first time an LLMContextFrame reaches the service. The first context frame
only arrives once the user transcript lands, which is after the server already
answered. events.jsonl shows resp at 17.61 (server) and resp at 19.50 (ours), and
11 response.created against 6 committed user turns.

## 17. Every tool result forced the bot to speak
Symptom: an utterance at the exact timestamp of every tool call.
Cause: `_process_completed_function_calls` ends with `if sent_new_result:
await self._create_response()`, so delivering a result and creating a turn were
the same action. All four tool results in call-05 produced a response within
160ms. Delivery is still required, because a realtime service reads tool results
out of the pushed context and not from FunctionCallResultFrame, so the fix gates
the response rather than the delivery: a response is created only when the
response that issued the tool call did not already speak.

## 18. Tool narration spoken aloud
Symptom: "let me check that detail for you for a moment" at 63.9s, "No, that
helps. I'll wrap up here" at 82.4s.
Cause: not the tool result. Both responses had output ['message',
'function_call'] - the model narrated the call inside the same response, before
any result existed, so the 82.4s line was not contradicting the refusal, it
preceded it. The vocabulary came from the runtime prompt itself, which said
"Never say you are checking something, looking something up, or that you need a
moment" and exposed a tool literally named check_fact described as "Check one
single fact". The prohibition supplied the exact words it forbade.

## 19. Bot drifted into receptionist voice
Symptom: "let me check that detail for you" - offering to look something up on
the other party's behalf.
Cause: the live session.update never used the words patient or receptionist. It
said "You are a real person making a real phone call" and left the rest to
inference, against the realtime API's structural framing in which our bot is the
assistant and the clinic is the user. Nothing counteracted the assistant's
default posture of holding records and helping the caller.

## 20. Model had no tools for the first 19 seconds
Symptom: the first session.update on the wire carried instructions but no tools;
tools appeared only in a second update at 19.4s.
Cause: `_send_session_update` reads tools from `self._context`, which is None
until the first context frame. That second update also re-seeded the caller's
transcript as an input_text item, duplicating audio the model already had.
Tools now ship in session_properties at connect, and handlers are registered
explicitly so they do not depend on a context frame arriving.

## 21. Required slot never credited, so the call could not end
Symptom: check_fact returned already_asked at 94.9s for a question about closed
days; scenario required closed_days and never obtained it, so end_call stayed
refused.
Cause: SLOT_KEYWORDS matched substrings, so the single word "closed" scored two
hits against the hours list ("close" and "closed") and cleared the >= 2
threshold, while scoring only one against closed_days and failing it. The claim
was credited to a slot already held and blocked as a repeat. Matching is now on
word boundaries with a threshold of one, and the repeat guard cannot fire on a
claim covering a still-missing required slot.

## 22. Latency: the event tap was not the cause
Measured rather than assumed. Median speech-stopped to first-audio in call-05 was
0.96s, max 1.30s, already inside budget. The tap's cost over the whole call is
~6.3ms of json.loads across ~1000 audio appends plus ~8ms of file appends across
461 events, about 15ms in 112 seconds. The real dead air was tool round-trip:
2.84s and 2.04s on the two tool calls whose response also spoke, against 0.01s on
the two that did not. `_maybe_push_context_after_function_result` defers the
context push until BotStoppedSpeakingFrame, so the result is held for exactly as
long as the narration lasts. The stall is a symptom of #18, not of the tap, and
event_tap.py was left alone.
