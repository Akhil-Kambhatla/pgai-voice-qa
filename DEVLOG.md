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