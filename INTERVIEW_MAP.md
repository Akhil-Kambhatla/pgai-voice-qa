# INTERVIEW_MAP.md

A working map of this repository: what every file does, why it exists, and where
the interesting decisions are. Written to be read cold, weeks after the code was
last touched.

Companion documents: `README.md` is the design argument, `BUGS.md` is the
findings against the clinic agent, `DEVLOG.md` is bugs found in our own harness.
This file is about the code.

---

## Section 1: System map

One call, end to end.

You start two processes. `src/server.py` is the FastAPI server on port 7860, with
ngrok tunnelling a public https URL to it. `scripts/run_campaign.py` is the loop
you drive from a second terminal.

The loop first preflights: it checks the server answers, checks ngrok is really
serving the URL in `.env`, and checks today's call count against the daily cap.
Then it plans. `src/scoring.py` picks a point in the eight axis scenario space by
arithmetic, and `src/planner.py` sends that tuple plus everything learned so far
to a text model, which writes a persona. `scripts/campaign_scenario.py` validates
that persona against six rules and regenerates up to three times if it fails.
The scenario is printed and you press enter to dial.

Dialling posts to `/start` on the server. `src/call_counter.py` reserves the call
id, `src/telnyx_client.py` places the outbound TeXML call, and a `call.json`
record is written. Telnyx answers and fetches `/answer`, which returns TeXML
pointing at the websocket. Telnyx opens that socket and `src/bot.py` builds the
Pipecat pipeline: a Telnyx serializer, a websocket transport, an OpenAI realtime
speech to speech model, and a turn logger. `src/persona.py` assembles the prompt
the caller model is given. During the call `src/bot_tools.py` serves the caller's
three private tools, `src/goal_judge.py` decides whether the caller is allowed to
hang up, `src/call_exit.py` handles every way a call can end, and
`src/event_tap.py` records the raw wire traffic. The server writes status
callbacks into `call.json` as Telnyx reports them.

When the call completes, the loop runs `scripts/fetch_and_transcribe.py`, which
polls Telnyx for the stereo recording and hands it to `src/transcribe.py` for
Deepgram to transcribe per channel. Then `scripts/analyze_call.py` runs
`src/analyst.py`, which sorts what the agent said into five buckets and writes
them through `src/ledgers.py` into the campaign state files. Finally
`scripts/campaign_summary.py` prints a summary and offers another call.

Everything for one call lands in `data/campaign/calls/call-NN/`. Campaign wide
state lands in `data/campaign/*.json`. `scripts/judge_campaign.py` is run
separately at the end, over all thirteen calls at once.

---

## Section 2: File by file

Ordered by how likely an interviewer is to ask about it, not alphabetically.

### Tier 1: the call path

#### `src/bot.py`
**Job.** Builds and runs the Pipecat pipeline for one live call, from the moment
Telnyx opens the websocket to the moment the call ends.

**Why it exists.** This is the only place the voice stack is assembled: transport,
serializer, realtime model, turn logger, watchdog, and the three exit paths. Without
it there is no call, only a phone ringing into a socket that does nothing. It is
also where the three independent ways a call can end are wired together, so if it
is wrong the call either never hangs up or hangs up too early.

**Design decision.** The pipeline runs at 24kHz, not the 8kHz the phone line uses.
The alternative was to run everything at the telephony rate. That was tried and it
fails silently: OpenAI realtime wants PCM16 at 24kHz, so an 8kHz pipeline feeds it
audio at a third of the correct speed, voice activity detection never fires, and
the bot simply never speaks. The Telnyx serializer does the 8k to 24k conversion at
the wire instead.

#### `src/server.py`
**Job.** FastAPI app with four endpoints: `/start` places a call, `/answer` returns
the TeXML that connects the media stream, `/ws` hosts the websocket, and `/status`
records Telnyx call progress callbacks.

**Why it exists.** Telnyx needs a public HTTP surface to fetch call instructions
from and to report status to, and the media stream needs a websocket endpoint.
Without it Telnyx has nothing to call back into. It also owns the `call.json`
record for every call, which every later stage reads.

**Design decision.** Pipecat is imported at module load time, not lazily inside the
websocket handler. The obvious alternative, importing on first use to keep server
startup fast, was tried and broke calls: the import takes long enough that Telnyx
gives up on the websocket handshake and the call dies. The module docstring says
this explicitly so nobody undoes it. A second decision in the same file: the public
URL comes from the `PUBLIC_BASE_URL` environment variable, never from the request
`Host` header, because the header does not survive the tunnel reliably.

#### `src/realtime_llm.py`
**Job.** A subclass of Pipecat's OpenAI realtime service that does two things the
base class does not: it filters the model's reasoning commentary out of the audio,
and it stops our own code from creating extra conversational turns.

**Why it exists.** This is the fix for the single worst call quality bug in the
project. `gpt-realtime-2.1-mini` emits its internal reasoning as a real assistant
message carrying `"phase": "commentary"`, in the same response as the actual reply.
Pipecat has no concept of phase, so that commentary audio went out over the phone
and the bot said things like "let me think this through" to a receptionist. Without
this file the caller narrates its own reasoning aloud and stops sounding like a
patient.

**Design decision.** The phase tag is read from the raw server event, not from
Pipecat's parsed `ConversationItem`. The alternative would be to read the parsed
model object, which is cleaner, but Pipecat's model drops fields it does not know
about, so `phase` is gone by the time the object exists. A second decision: turning
reasoning off entirely was tested and measured, and it cuts tokens but does not
remove the commentary class, so the filter stays as the load bearing fix.

#### `src/bot_tools.py`
**Job.** Defines the caller's three tools, `silent_compare`, `silent_note` and
`hang_up`, and holds the logic that decides whether a hangup is allowed.

**Why it exists.** The caller needs a way to check a fact against what the agent has
said before, a way to park something odd without derailing the conversation, and a
way to end the call. Without the hangup gate the model ends calls the moment it
feels socially finished, which in early calls meant hanging up before the scenario
goal was reached.

**Design decision.** Tool results are bare codes, never sentences. The natural thing
is to return a helpful message like "you still need to confirm the appointment
time", and that was tried. The realtime model reads anything sentence shaped in a
tool result and says it out loud. So results are `{"verdict": "conflict"}` and
`{"hangup": "denied"}`, and `scripts/smoke_checks.py` has a test that fails if any
payload contains four consecutive English words.

#### `src/call_exit.py`
**Job.** Everything about how a call ends: a serializer subclass that logs and
handles the far end hanging up, an event tracker that records every exit decision,
and a retry object that nudges the model when a hangup was denied.

**Why it exists.** A call can end in at least four ways: the caller model asks to
hang up and is granted, the watchdog hits `MAX_CALL_SECONDS`, Telnyx sends a stop
because the far end went away, or the websocket just closes. Each needs to tear
down the pipeline exactly once and leave a record of which happened. Without this
the call either hangs open burning money or ends without anyone knowing why.

**Design decision.** When a hangup is denied, a nudge is scheduled 45 seconds later
rather than the denial simply being returned. The alternative, returning the denial
and trusting the model to keep going, was tried and failed: a single denial ended
the exit path, and the model would sit silent rather than retry. The nudge is a
system message with a JSON payload, and the payload is code shaped for the same
reason tool results are.

#### `src/turn_log.py`
**Job.** Four Pipecat frame processors: one that writes every turn to
`turns.jsonl` and detects stalls, one that taps the far end's transcript, one that
watches for our own goodbye, and one that truncates our reply when the far end says
goodbye.

**Why it exists.** `turns.jsonl` is the live view of the call, and it is what the
campaign runner streams to your terminal while the call is happening. The stall
detector is one of four conditions that let the caller hang up. The farewell
watcher exists because the clinic agent hangs up unilaterally and our bot would
keep talking into a dead line.

**Design decision.** Stall detection compares content word overlap between the last
two agent turns and everything before them, and it explicitly does not fire if the
recent turns introduce a new time, weekday, month or number. The simpler
alternative, firing on repeated phrasing alone, was written first and fired on the
wrong call: an agent reading back a new appointment time uses very similar words
each time but is not stalling.

#### `src/goal_judge.py`
**Job.** Asks a text model, mid call, whether the caller's goal has been met, is
unachievable, or is still open.

**Why it exists.** The hangup gate needs a judgment that the model playing the
caller cannot make for itself, because that model wants to be polite and end
early. Without it the caller hangs up on the first natural pause.

**Design decision.** A hard two second timeout, and it fails closed. Any exception
or timeout returns `not_yet`, which denies the hangup. The alternative, failing open
so a slow judge does not trap the caller on the line, is worse: a slow judge would
then end a live call for no reason. The `MAX_CALL_SECONDS` watchdog is the backstop
that guarantees the call still ends.

#### `src/session_config.py`
**Job.** Builds the OpenAI realtime session properties, in particular the turn
detection block.

**Why it exists.** Turn taking is the single biggest lever on whether the caller
sounds human, and it is configurable through four environment variables. This file
is the one place that translates those variables into the API's shape. It also
exposes `resolved_turn_detection()`, which is written into `call.json` so you can
tell after the fact which settings a given call actually ran with.

**Design decision.** Semantic voice activity detection is the default, rather than
a fixed silence timer. Semantic detection lets the model decide when a speaker has
finished a thought, which handles the clinic agent's habit of pausing between
sentences. Server side fixed threshold detection is still supported for comparison
and is exercised by the smoke suite.

#### `src/event_tap.py`
**Job.** Records every message in both directions on the OpenAI realtime websocket
to `events.jsonl`, and writes side artifacts like `instructions.txt`.

**Why it exists.** Almost every hard bug in `DEVLOG.md` was diagnosed from this
file. Without it you are guessing about what the model was sent and what it sent
back. It is also what makes the replay tests possible: two of the smoke checks
replay real recorded events through current code.

**Design decision.** Audio payload events are counted and only every two hundredth
is kept, with the base64 audio stripped out. The alternative, recording everything,
produces a file too large to read and mostly full of audio bytes. The alternative
of dropping them entirely loses the timing information that latency analysis needs,
so the count is preserved in an `elided_payload_count` field.

#### `src/persona.py`
**Job.** Assembles the live prompt from the static conversation prompt plus the
scenario, and rewrites any planner text that slipped into the third person.

**Why it exists.** The caller model is told who it is in exactly one place, and this
is it. It also decodes the base64 body Telnyx passes through the answer URL, which
is how the scenario id and call id reach the websocket handler.

**Design decision.** Third to second person rewriting is regex based over pronouns
and verb forms, and when it finds a sentence that mixes both persons it warns and
leaves the text exactly as written. The alternative, sending the text to a model to
rewrite, adds a network call to the call setup path. The real protection is upstream
in the validator, which rejects third person scenarios before they are dialled; this
is a safety net, and its limits are stated in the README.

#### `src/telnyx_client.py`
**Job.** Places outbound TeXML calls, finds the recording afterwards, and downloads
it.

**Why it exists.** Telephony and recording retrieval both live here so nothing else
needs to know the Telnyx API shape. Without it there are no calls and no audio to
analyse.

**Design decision.** Recordings are matched to calls by start time, not by id. This
looks wrong and the module docstring explains why it is not: on this account
recordings are produced at the trunk level with `call_sid` set to null and no phone
numbers in the metadata, so there is no id to match on. The rule used is the
earliest completed recording whose start time is at or after the call was placed,
with 30 seconds of slack for clock skew.

#### `src/transcribe.py`
**Job.** Sends the stereo mp3 to Deepgram Nova-3 in multichannel mode and writes
`transcript.json` and `transcript.txt`.

**Why it exists.** Every finding in `BUGS.md` is quoted from the text this file
produces. Without it there is audio and nothing readable.

**Design decision.** Speaker attribution comes from the stereo channel, not from
diarisation. Channel 1 is our bot and channel 0 is the agent under test, verified
empirically on a test call and asserted by a smoke check. Diarisation guesses who
is speaking from the audio; channels know. Getting this backwards would attribute
every finding in the report to the wrong party, which is why it is a test and not a
comment.

#### `src/config.py`
**Job.** Loads and validates every environment variable at import time, and derives
the paths and the websocket URL.

**Why it exists.** A missing key or a bad VAD setting should stop the process at
startup, not halfway through a paid phone call. It also defines the two call trees,
`campaign` and `roleplay`, and picks which one new calls are written to.

**Design decision.** Invalid combinations are rejected, not just invalid values. If
you set `VAD_THRESHOLD` while `TURN_DETECTION` is `semantic_vad`, the process exits
and tells you the setting does not apply in that mode. The alternative, ignoring
settings that do not apply, silently leaves you believing you tested something you
did not.

### Tier 2: planning a call

#### `src/scoring.py`
**Job.** Chooses the eight axis tuple for the next call by sampling 200 random
candidates and scoring each one.

**Why it exists.** The scenario space is about 200,000 tuples and the budget was
thirteen calls, so which tuples get used is the whole coverage story. Without a
scorer the choice is either a fixed list, which cannot react, or a model's opinion,
which drifts.

**Design decision.** Coverage is computed, not asked for. The alternative was to
ask an LLM what to test next, and that was rejected because coverage is a counting
problem and a model asked "what next" drifts toward whatever it just read. The score
interpolates from exploration to exploitation as the campaign advances, using
`w = call_index / total_calls`. Explore is novelty plus uncovered pair fraction,
which is standard all pairs test coverage. Note that `TOTAL_CALLS` is 20 in this
file while the campaign actually ran thirteen calls, so the weight never reached
the exploitation end.

#### `src/planner.py`
**Job.** Turns the chosen axis tuple into a written scenario by calling a text
model, then stamps it with an id and saves it.

**Why it exists.** A tuple is a set of constraints, not a person. This is where
constraints become someone with a lunch break and a shift rota. It is also where
the campaign's accumulated state, the oracle, the frontier, the open suspicions and
the unverified claims, is gathered and handed to the model.

**Design decision.** Axes can be pinned from the command line, and pinned axes are
excluded from the scoring arithmetic. The simple alternative, pinning after scoring,
would let a pin distort the coverage numbers for the axes you did not pin. It also
strips any `facts_to_elicit` entry that is not one of the ten real oracle slot
names and logs a warning, rather than trusting the model's output.

#### `src/oracle.py`
**Job.** The in call fact checker behind `silent_compare`. Matches a spoken claim
to one of ten fact slots and reports whether it agrees with, conflicts with, or is
new against what the agent has said before.

**Why it exists.** The caller needs to notice a contradiction while it is still on
the phone, fast enough not to leave a gap in the conversation. This is a local
keyword and token comparison, which is why it returns in milliseconds. It also
suppresses repeats, so the caller does not chase the same topic three times.

**Design decision.** Comparison is category based, not semantic. It extracts times,
weekdays, months and numbers from both statements and reports a conflict only when
both statements mention the same category and share no value in it. The alternative,
asking a model whether two statements conflict, cannot run inside a live turn
without an audible pause. The cost is that it only catches conflicts expressed in
those four categories.

#### `scripts/run_campaign.py`
**Job.** The one command that runs the whole loop: preflight, plan, validate,
confirm, dial, stream, wait, fetch, transcribe, analyse, summarise, repeat.

**Why it exists.** Without it the operator runs six scripts in order and gets the
order wrong under pressure. It is also where the human confirmation gate lives.

**Design decision.** Every call stops and waits for a human to press enter. For a
system described as autonomous this looks like a contradiction, and the reasoning is
economic: each call is real money on a metered line and one of a small number of
daily slots, and a bad scenario is cheaper to catch by eye in five seconds than by
spending a call on it. The README lists this as one of three things that would
change for continuous testing.

#### `scripts/campaign_scenario.py`
**Job.** Validates a planned scenario against six rules and returns a list of
failures, and can also load a scenario written by hand.

**Why it exists.** A rejected scenario costs one model call. A bad scenario that
gets dialled costs a graded call and a day's slot. Every one of the six rules is a
lesson paid for with a wasted call, including the two that check whether the persona
matches whether that identity actually has a record in the clinic's system.

**Design decision.** Validation is rule based and mechanical, not a second model
pass judging quality. The alternative, an LLM critic, gives softer and less
repeatable answers. These rules encode specific known failure modes and each one
names the failure it prevents.

#### `scripts/campaign_detectors.py`
**Job.** The regex detectors the validator uses: does the persona stonewall
identification, does it assert a record that does not exist, is the caller unsure
about their own life, does it create a profile.

**Why it exists.** Kept separate from the validator so the pattern lists can be read
and edited on their own. Without these, the four subtlest scenario failures pass
validation.

**Design decision.** `unsure_of_own_life` tracks the last grammatical subject before
the uncertainty marker and only fires when the subject is the caller and the thing
they are unsure about is theirs. The alternative, flagging every "not sure" in the
persona, would reject legitimate scenarios: a caller unsure whether the clinic takes
their insurance is exactly right, a caller unsure which day they work is not.

#### `scripts/campaign_call.py`
**Job.** Preflight checks, the dial call to the server, and the wait loop that polls
for call completion while streaming new turns.

**Why it exists.** Three things go wrong before a call more often than anything else:
the server is not running, ngrok restarted and `PUBLIC_BASE_URL` is stale, and the
daily cap is already spent. This checks all three and refuses to dial otherwise.

**Design decision.** The ngrok check queries ngrok's local agent API and compares
the live tunnel URL against `.env`, rather than trying to fetch the public URL. This
machine cannot reach `*.ngrok-free.dev` over TLS even though Telnyx can, so fetching
the public URL as a health check would fail on a perfectly good tunnel.

#### `scripts/campaign_render.py`
**Job.** Formats a scenario for the terminal so a human can read it in five seconds
before deciding to dial.

**Why it exists.** The confirmation gate is only worth having if the thing being
confirmed is legible. It also extracts and displays the dates and provider names the
persona actually contains, under headings like "says when asked which date".

**Design decision.** It surfaces what the persona will answer when asked, rather than
just printing the persona text. That line is what catches a scenario where the agent
will ask which day and the caller has nothing to say, which is the failure that
produces a useless call.

#### `scripts/campaign_summary.py`
**Job.** Prints the post call summary: duration, how it ended, turn counts, tool
calls, barge ins, response latency, and what the extraction added to the ledgers.

**Why it exists.** It is the immediate feedback after each call, and it is how you
tell a call that worked from a call that ended for a reason you did not intend.

**Design decision.** Latency is measured from `speech_stopped` to the first
transcript delta, read out of `events.jsonl`. The alternative, timing our own code,
measures the wrong thing: what matters is the gap the other party hears.

### Tier 3: after the call

#### `src/analyst.py`
**Job.** Reads a finished call's transcript, sends it to a text model for
extraction, and writes the results through the ledgers into campaign state.

**Why it exists.** This is the bridge from one call's transcript to campaign wide
knowledge. Without it every call is an isolated recording and nothing accumulates.

**Design decision.** It writes an `extraction.json` next to the call holding the raw
model output, what was applied, and what was skipped and why. The alternative,
applying changes and keeping only the result, makes it impossible to tell later
whether a missing fact was never said or was dropped by a ledger rule.

#### `src/ledgers.py`
**Job.** Applies extracted facts, claims, promises, capabilities and entities to the
campaign state files, and raises a suspicion when two stated facts conflict.

**Why it exists.** It is the only writer of campaign state, so all the rules about
what is allowed into the oracle live in one place. Without it the analyst would
write whatever the model returned.

**Design decision.** A new fact that conflicts with a stored one raises a suspicion
rather than overwriting. A new fact that is strictly more specific sharpens the
stored one. A fact naming a slot that is not one of the ten known slots is dropped
with a warning. The alternative, last write wins, would erase the evidence that the
agent said two different things, which is the strongest class of finding this system
produces.

#### `src/resolver.py`
**Job.** Settles every promise the agent made against the part of the transcript
that came after it.

**Why it exists.** "I'll connect you to our support team" is checkable, and this is
what checks it. It assembles, for each promise, the remainder of the transcript, the
seconds of call left, and the number of agent turns left, then asks a model for an
outcome plus a quote.

**Design decision.** Promises are classified before they are resolved, and only the
in call ones reach the resolver. Vacuous promises and out of band promises are
settled without a model opinion, because asking a model whether a text message
arrived invites it to guess about something no recording can show.

#### `src/promise_gate.py`
**Job.** Checks the resolver's verdict before it is accepted, and records every
disagreement.

**Why it exists.** A fluent model will happily resolve a promise against a sentence
it invented. This is the check that stops that. Without it the promise findings in
`BUGS.md` would be a model's opinion rather than evidence.

**Design decision.** The evidence quote must appear verbatim in the remainder, after
normalising punctuation and case. If it does not, the verdict is thrown out as
`evidence_not_found`. If the model claims the call ended too soon, that reason is
checked against the actual seconds and turns remaining, and an unsupported reason
becomes `reason_not_supported`. Every override is written into the judgment record,
so the gate's disagreements with the model are themselves auditable.

#### `src/promise_kind.py`
**Job.** Sorts each promise into `vacuous`, `out_of_band` or `in_call`.

**Why it exists.** These three need completely different treatment, and mixing them
produces bad work. Filing a promise as a claim, or an out of band callback as an in
call action, sends a human off to check something the recording either already
answers or can never answer.

**Design decision.** The classifier is deliberately not given the call. The prompt
says so and explains why: knowing how the call turned out would tempt the model to
answer a different question, namely whether the promise was kept, instead of what
kind of promise it is.

#### `src/contradictions.py`
**Job.** The mechanical contradiction detectors. Pairs every affirmation of an
ability against every denial of the same ability, and separately detects the agent
reciting the caller's phone number.

**Why it exists.** These findings need no model at all. If the ledger says the agent
affirmed X in one call and denied X in another, that is a contradiction by
construction. Without this the strongest findings would depend on a model noticing
them.

**Design decision.** The phone detector ships with its own caveat attached to the
finding, in the code, and that caveat is reproduced verbatim in `BUGS.md`: it cannot
tell a number read off caller ID from a number read out of a stored record. Stating
what a detector cannot distinguish is what turns an overclaim into a reportable
observation.

#### `src/contradiction_review.py`
**Job.** The model assisted contradiction pass, for the two things exact matching
cannot do: the same power under two different ability handles, and a statement
contradicted by observed behaviour.

**Why it exists.** Ability handles were written call by call, so one power can appear
as "access record", "find record" and "locate record". Exact matching misses those.

**Design decision.** Every model output is checked before it is kept. A synonym pair
is dropped if the exact pass already found it, if the handles are identical, or if
the `can` values do not actually disagree. A behaviour finding is dropped if its
quote is not found verbatim in the named call. Findings from this pass are labelled
`model_clustered` or `model_proposed` and are treated as a worklist for a human, and
nothing from this tier reached `BUGS.md` on its own authority.

#### `src/call_transcript.py`
**Job.** Parses `transcript.txt` back into timestamped lines, renders lines back to
text, and reads how a call ended out of `call.json` and `events.jsonl`.

**Why it exists.** Shared plumbing for the resolver, the contradiction detectors and
the review pass. Without it three files would each parse the transcript format their
own way and drift apart.

**Design decision.** The transcript text file is the canonical form for analysis, not
`transcript.json`. The text file is what a human reads and what quotes in `BUGS.md`
come from, so verifying a quote against the same artifact a human would read keeps
evidence and analysis on the same footing.

#### `src/store.py`
**Job.** Reads and writes every JSON state file and scenario file, and resolves a
call id to a directory.

**Why it exists.** One place knows where things live. It also implements the split
between shared state, meaning identities and axes, and per tree state, meaning the
ledgers.

**Design decision.** An unqualified call id that exists in both the campaign and
roleplay trees is a hard error naming both options, not a silent pick. The
alternative, preferring one tree, would eventually attribute a development call to
the graded campaign, which is a data integrity problem in the submission itself.

#### `src/call_counter.py`
**Job.** Reserves a call id and enforces the daily call cap.

**Why it exists.** It is one of the two spend guards. It is enforced by a counter in
code that refuses to dial, not by an instruction in a prompt.

**Design decision.** The count is summed across both call trees, so a development
call and a graded call draw from the same daily budget. The alternative, per tree
counters, means switching trees silently doubles the day's spending limit.

#### `scripts/judge_campaign.py`
**Job.** The end of campaign analysis pass: resolves every promise across all calls,
runs the contradiction detectors, prints the report, and writes `judgments.json`.

**Why it exists.** Promise resolution and contradiction detection are campaign wide,
not per call, so they cannot run in the per call loop. This is where the raw material
for `BUGS.md` is produced.

**Design decision.** It writes a machine readable `judgments.json` as well as
printing. That file is what `scripts/test_judgment.py` and
`scripts/test_contradictions.py` assert against, so the specific findings in
`BUGS.md` have regression tests behind them.

#### `scripts/judge_render.py`
**Job.** Formats the judge output for the terminal: promises by call, capability
pairs, phone findings, and model proposed candidates.

**Why it exists.** `judge_campaign.py` produces a large amount of structured data and
this keeps the presentation out of the logic.

**Design decision.** Model proposed findings are printed under a heading that says in
plain words that the quote was verified but the judgment is the model's opinion and
wants a human eye. The alternative, printing all findings in one list, invites
someone to copy a weak finding into a bug report.

#### `scripts/judge_checks.py`
**Job.** Shared helpers for the judgment tests: a pass or fail printer, a text
normaliser, and a loader for `judgments.json`.

**Why it exists.** Two test files need the same three helpers and the same failure
collection.

**Design decision.** It exits with a clear message if `judgments.json` is missing,
telling you to run `judge_campaign.py` first, rather than failing on a missing file.

#### `scripts/fetch_and_transcribe.py`
**Job.** Polls Telnyx for a finished call's recording, downloads it, and transcribes
it.

**Why it exists.** Recordings appear a minute or two after the call ends, so this
cannot be part of the call handler. It also writes the recording metadata back into
`call.json`.

**Design decision.** It runs as a subprocess from the campaign loop rather than as an
imported function. That keeps a failure here from taking down the loop, and the loop
surfaces the last few lines of its output as the error.

#### `scripts/analyze_call.py`
**Job.** Thin command line wrapper around `src/analyst.py` for one call id.

**Why it exists.** Lets extraction be re-run against a call by hand, and gives the
campaign loop a subprocess to call.

**Design decision.** No logic of its own. It prints the list of ledger changes and
nothing else.

### Tier 4: development and verification tools

#### `scripts/smoke.py`
**Job.** Runs nine checks before any call is placed and prints a table saying which
bug each one guards.

**Why it exists.** Every check exists because something broke on a real call. It is
the thing you run after touching anything on the call path and before spending a
call slot.

**Design decision.** Each check is listed with the failure it protects against, not
just a name. The planner contract sampling runs separately at the end and is marked
advisory, because it makes real model calls and a wobble there should not read as a
regression.

#### `scripts/smoke_checks.py`
**Job.** Five of the nine checks: prompt assembly, tool payload hygiene, the oracle
slot guard, the transcript channel mapping, and call tree resolution.

**Why it exists.** These are the assertions that are cheap and mechanical. The
channel mapping check in particular is what stops the entire bug report being
attributed to the wrong speaker.

**Design decision.** The payload hygiene check tests that no tool result or nudge
payload contains four consecutive English words, and separately that no payload
shares a four word sequence with the scenario goal. The alternative, checking against
a list of forbidden phrases, only catches the phrasings you already thought of.

#### `scripts/smoke_config.py`
**Job.** Runs the config module in a subprocess against a scratch `.env` for every
valid and invalid VAD combination.

**Why it exists.** `src/config.py` validates at import time and exits the process on
a bad value, which cannot be tested in process. This spawns a real Python for each
combination.

**Design decision.** It builds a throwaway `.env` in a temp directory and strips the
VAD variables from the inherited environment, so your real shell settings cannot make
the test pass or fail.

#### `scripts/smoke_planner.py`
**Job.** Draws real scenarios from the planner and checks them against a contract:
required fields, second person, goal shape, valid slots, no volunteered identity
details, no invented clinic facts, no service side follow ups.

**Why it exists.** It is the only check on planner output quality that runs against
live model calls rather than fixtures. It also owns `learned_not_achieved`, which the
production validator imports.

**Design decision.** Advisory, not blocking. It costs real model calls and any single
draw can be unlucky, so it prints a hit rate rather than failing the suite. The
blocking version of the same idea is `campaign_scenario.validate`, which runs on
every real scenario.

#### `scripts/smoke_replay.py`
**Job.** Replays two recorded calls' events through the current commentary filter and
asserts it catches exactly the tagged items and nothing else.

**Why it exists.** The commentary bug took three rounds to fix and each round could
have broken speech. Replaying real recorded events is the only way to test it without
placing a call.

**Design decision.** It builds the service with `__new__` and sets only the two
attributes the filter needs, rather than constructing a real service. The alternative
would need an API key and a websocket. It asserts in both directions: everything
tagged is caught, and nothing untagged is suppressed, because over-suppressing made
the bot mute once already.

#### `scripts/replay_gate.py`
**Job.** Replays a recorded call's events through the response creation gate and
prints how many client side responses the old code would have created against the
new gate.

**Why it exists.** Diagnostic for the double response bug, where our own code created
a turn on top of the one the server's turn detection already created. It shows the
before and after against a real call.

**Design decision.** It monkeypatches the Pipecat base class methods to count calls
instead of making them. That is fine for a diagnostic script and would not be
acceptable in the test suite, which is why this is a tool you run by hand and not one
of the nine smoke checks.

#### `scripts/analyze_events.py`
**Job.** Deep diagnostic over one call's `events.jsonl`: response ownership, tool
forced speech, narration inside tool turns, latency, tool round trip, deletions, and
speech quality including receptionist voice drift.

**Why it exists.** This is the tool that found most of `DEVLOG.md`. When a call
sounds wrong and you cannot say why, this is what you run.

**Design decision.** It keeps two hardcoded phrase lists, one for internal reasoning
leaks and one for receptionist voice drift. Those lists are specific to failures seen
on real calls, which makes the tool blunt but immediately useful, and it is a
diagnostic rather than a gate so false positives cost nothing.

#### `scripts/dump_session.py`
**Job.** Prints every `session.update` sent on the wire for a call, with the
instruction length, the first and last 400 characters, and every tool description,
plus any model visible text our code injected.

**Why it exists.** It answers "what did the model actually receive", which is
different from what you think you sent. It found the bug where the model had no tools
for the first nineteen seconds of a call.

**Design decision.** It prints the head and tail of the instructions rather than the
whole thing, because the full prompt is several thousand characters and the parts
that go wrong are at the ends.

#### `scripts/plan_call.py`
**Job.** Plans one scenario and prints it without dialling.

**Why it exists.** Lets you look at planner output, including with pinned axes, for
the cost of one model call and no phone call.

**Design decision.** It prints the command to dial the scenario it just made, so
planning and dialling stay separate actions.

#### `scripts/place_call.py`
**Job.** Posts a scenario id and a phone number to the server's `/start`.

**Why it exists.** The minimal way to dial a known scenario, used during development
against a personal number.

**Design decision.** No dependency on the project modules at all, just urllib. It
works even when the rest of the environment does not.

#### `scripts/test_exit_path.py`
**Job.** Tests the hangup gate end to end with fakes: the serializer terminating on
end and cancel frames, each grant condition, unelicited facts not blocking a hangup,
stall detection, and the end frame routing.

**Why it exists.** The hangup gate is the most intricate logic in the call path and
it took a long stretch of `DEVLOG.md` to get right. It is one of the nine smoke
checks.

**Design decision.** It uses hand written fake logger, tracker, retry and params
objects rather than a mocking library. The fakes are small enough to read, and a
reader can see exactly what the gate is being given.

#### `scripts/test_goal_judge.py`
**Job.** Tests the goal judge against a client that returns, a client that sleeps
past the timeout, and a client that raises.

**Why it exists.** The failure mode that matters is a slow or broken judge ending a
live call. This proves it fails closed instead.

**Design decision.** It asserts on the recorded round trip source, so the test can
tell a real model verdict from a timeout from an exception, not just the outcome.

#### `scripts/test_commentary_filter.py`
**Job.** Drives the commentary filter with synthetic events and counts how many audio
and transcript deltas pass through.

**Why it exists.** The counterpart to `smoke_replay.py`. That one replays real calls,
this one constructs the specific event shapes by hand.

**Design decision.** Not clear from the file whether this is intended to stay
alongside `smoke_replay.py` permanently or was the earlier of the two. Only
`smoke_replay.py` is wired into the smoke suite.

#### `scripts/test_far_end_disconnect.py`
**Job.** Checks the recorded timing of far end disconnects on two real calls and
proves a Telnyx stop event tears down the pipeline.

**Why it exists.** The clinic agent hangs up unilaterally, and before this our bot
kept talking, which leaked lines like "part of the test" into the recording after the
far end was gone.

**Design decision.** It asserts against real call fixtures rather than synthetic
ones, so the timing being checked is timing that actually happened.

#### `scripts/test_farewell_truncation.py`
**Job.** Tests the farewell watcher: that it fires inside the window on two calls
where the agent said goodbye, stays quiet on a call that continued, and fires only
once.

**Why it exists.** A watcher that truncates our reply on any farewell shaped phrase
would cut the caller off mid conversation. The quiet case matters as much as the
firing case.

**Design decision.** The negative fixture, a call that continued after a farewell
shaped line, is treated as a first class test rather than an afterthought.

#### `scripts/test_judgment.py`
**Job.** Asserts specific findings hold in `judgments.json`: transfer promises are
unfulfilled on five named calls, unresolvable carries the right reason, the too soon
gate is arithmetic, vacuous is its own outcome, and every settled promise quotes the
remainder.

**Why it exists.** These are regression tests on the report itself. If a change to the
resolver or the gate would quietly alter a finding in `BUGS.md`, this fails.

**Design decision.** It names calls and outcomes explicitly rather than checking
aggregate counts. That makes it brittle to a rerun of the campaign and precise about
the submission as it stands, which is the right trade for a graded artifact.

#### `scripts/test_contradictions.py`
**Job.** Asserts the capability pair on past hours lookup is found mechanically, the
phone recital contradiction is reported, and every model finding carries a verified
quote.

**Why it exists.** Same reason as `test_judgment.py`, for the contradiction half of
the report.

**Design decision.** It asserts that model findings carry quotes, which is a check on
the verification layer rather than on the finding, so it stays meaningful even if the
model's output changes.

#### `scripts/test_scenario_rules.py`
**Job.** Tests the six validator rules with a known good scenario and a list of
deliberately broken variants.

**Why it exists.** The validator is what protects graded calls, so it needs its own
tests. It also exports the `GOOD` fixture that three other test files build on.

**Design decision.** Each bad shape is a one field mutation of the same good
scenario, so a failure names exactly which rule broke.

#### `scripts/test_profile_rules.py`
**Job.** Tests that profile creation validation depends on whether the identity has a
record: the same persona is rejected for an identity with a record and accepted for
one without.

**Why it exists.** This rule is conditional on campaign state, which makes it the
easiest of the six to get backwards.

**Design decision.** It passes `record_identities` in explicitly rather than reading
real campaign state, so the test does not change meaning as the campaign progresses.

#### `scripts/test_written_scenario.py`
**Job.** Tests the hand written scenario path: that a scenario file loads, that the
planner is not called when one is given, and that a bad hand written scenario is
rejected without regeneration.

**Why it exists.** The `--scenario` path bypasses the planner, and the risk is that it
also bypasses validation.

**Design decision.** It stubs the planner with a function that fails if called, which
proves the bypass rather than merely testing the happy path.

#### `scripts/test_axis_pin.py`
**Job.** Tests that two pinned axes hold across draws, that free axes still vary, and
that an unknown axis name fails loudly.

**Why it exists.** Pinning is how you steer the campaign by hand, and a pin that
silently does nothing wastes a call.

**Design decision.** It draws repeatedly and checks the distribution, because a
sampler bug can produce the right answer once by luck.

#### `scripts/test_identity_pin.py`
**Job.** The same for identity pinning, plus a check that a pinned axis is excluded
from the coverage scoring.

**Why it exists.** Identity is the axis most often pinned by hand, and the scoring
exclusion is the non-obvious half of the feature.

**Design decision.** It asserts the pinned axis does not appear in the scoring
arithmetic, not just that the pin holds, which is the property a reader would not
think to check.

#### `scripts/test_campaign_loop.py`
**Job.** Tests completion detection against fake call directories and runs the loop
with dialling stubbed out.

**Why it exists.** The loop is the piece you cannot test by running it, because
running it places calls.

**Design decision.** It builds fake call directories with real shaped status events
in a temp directory, so the completion detector is tested against the actual JSON
shape Telnyx sends.

#### `scripts/test_run_campaign.py`
**Job.** Tests that the planner retry gives up after three attempts, and that the
summary renders correctly against real call 05.

**Why it exists.** An unbounded retry loop against a model that keeps producing
invalid scenarios would burn tokens indefinitely.

**Design decision.** The summary test runs against a real recorded call rather than a
fixture, which catches format drift in the artifacts themselves.

#### `scripts/test_exit_summary.py`
**Job.** Tests that the summary tells the three call endings apart, and that the
recordings on disk survived.

**Why it exists.** Reporting the wrong ending makes every other number in the summary
misleading.

**Design decision.** It includes a check that the recording files still exist, which
is a check on the submission's evidence rather than on the code.

#### `scripts/__init__.py` and `src/__init__.py`
**Job.** Empty files that make the two directories importable packages.

**Why it exists.** Scripts import from each other as `from scripts import ...`, which
needs the package. Without them the cross imports fail.

**Design decision.** None. They are empty.

### Tier 5: configuration and documents

#### `pyproject.toml`
**Job.** Declares the Python version, the six direct dependencies, and the ruff line
length.

**Why it exists.** `uv sync` reads it. Notable that Pipecat is pulled with a specific
set of extras: `websocket`, `openai`, `silero`, `deepgram`, `runner`.

**Design decision.** Dependencies are floors, not pins, except that Pipecat is
required at 1.7.0 or above. The lock file `uv.lock` holds the exact versions.

#### `.env.example`
**Job.** Every environment variable with empty values, plus comments explaining the
optional ones.

**Why it exists.** `src/config.py` exits listing what is missing, and this is where
you find out what each one means. It is also the file that keeps real secrets out of
the repository.

**Design decision.** It carries real defaults for the non-secret values,
`MAX_CALL_SECONDS=240`, `MAX_CALLS_PER_RUN=6`, and the two model names, so a reader
can see the spend guards without reading code.

#### `.gitignore`
**Job.** Keeps `.env`, the virtual environment, generated scenarios, and Python
caches out of the repository.

**Why it exists.** The first line is the one that matters: `.env` holds live API keys
for three paid services and a phone number.

**Design decision.** `scenarios/` is ignored, so the twenty six scenario files present
on disk are not in git. This is worth knowing before an interview, because the
scenario that produced a given graded call is not in the repository, though the
assembled prompt for every call is, as `instructions.txt`.

#### `claude.md`
**Job.** Project instructions for the AI coding assistant used to build this:
verified environment facts, hard rules, an iteration protocol, and the spend guards.

**Why it exists.** It is the working memory of the build, and the reason the same
mistake was not made twice. It records things like the 24kHz requirement and the
Telnyx recording behaviour so they never had to be rediscovered.

**Design decision.** It records verified facts with the date they were verified, and
says not to re-derive them. Note it is lowercase `claude.md` on disk, and it is
committed.

#### `README.md`
**Job.** The design argument: the problem, why the architecture is what it is, how a
call is planned, what happens after, how to run it, what was found, and the
limitations.

**Why it exists.** The assessment is graded partly on how clearly the architecture is
reasoned about, and this is that reasoning.

**Design decision.** It has a limitations section that names four things that did not
work, including that the exploit half of the scoring never engaged because the
suspicion ledger stayed empty.

#### `BUGS.md`
**Job.** Thirteen defects in the clinic agent, with timestamped quotes, severity, and
what a correct agent would have done.

**Why it exists.** It is the deliverable.

**Design decision.** Each finding is tagged with its provenance, `[verified]`,
`[resolver]` or `[detector]`, and there is a section called "Not reported, and why"
listing things that looked like defects but could not be separated from 8kHz
transcription error.

#### `DEVLOG.md`
**Job.** Thirty five numbered entries on bugs in our own harness, each with symptom,
cause and fix.

**Why it exists.** Kept deliberately separate from `BUGS.md` so our bugs and their
bugs are never confused. It is also where the reasoning behind several odd looking
pieces of code is recorded.

**Design decision.** Entries record what was wrong about an earlier conclusion, not
just the final fix. Entry 28 is an example: an early sample suggested disabling
reasoning removed the commentary class, and the entry says plainly that the sample
was too small and the conclusion was wrong.

#### `pgai_voice_qa_architecture_flow.png`
**Job.** An architecture diagram in three bands, Plan, Call and Learn, showing state
files into scoring into the planner into a scenario file, then Telnyx between the
clinic agent and the realtime model, then recording into Deepgram into the analyst,
with a note that the analyst writes back to the state files.

**Why it exists.** A one image version of the loop.

**Design decision.** Worth knowing before an interview: the diagram labels the in call
tool `check_fact`, which is its old name. The tool is now `silent_compare`, and it was
renamed because the old name supplied the model with the exact vocabulary it then said
out loud. The diagram is stale on that one label.

#### `.claude/RESUME.md`
**Job.** A checkpoint file written by the coding assistant when a session neared its
limit.

**Why it exists.** Not part of the system. It is a build artifact.

**Design decision.** None. It is untracked and can be deleted.

### Tier 6: data and scenarios

#### `data/` overall shape
Two parallel call trees plus shared inputs.

- **Shared inputs, at `data/`.** `axes.json` defines the eight axes and their values.
  `identities.json` defines the four callers with fixed name, date of birth, phone,
  address, insurer, member id, and a `test_purpose` note saying what each one is for.
  These two are read by both trees.
- **`data/campaign/`** is the graded tree. It holds `calls/` with one directory per
  call, plus the campaign wide ledgers: `oracle.json`, `claims.json`, `promises.json`,
  `capabilities.json`, `suspicions.json`, `frontier.json`, `call_counter.json`, and
  `judgments.json` written by the judge pass. This tree is committed.
- **`data/calls/`** is the roleplay tree, used for development calls to a personal
  number. It has the same per call shape but is missing `extraction.json`, because the
  analyst was written later. Its ledgers live at `data/` root level, which is why
  `data/oracle.json` and `data/frontier.json` exist next to the shared inputs.
- **`data/calls_scaffold/`** holds four early call records from 2026-08-17, named by
  Telnyx call session id rather than by call number, from before the call id scheme
  existed. They were infrastructure tests to a personal number. It is untracked and
  is not part of the system.

A note on the split: the state file naming is the one place where the two trees are
asymmetric, and it is why `src/store.py` has to know which files are shared and which
are per tree.

#### `scenarios/`
One JSON file per planned scenario, named `NN-slug.json`, holding the axes, the
identity, the persona block, the opening situation, the goal, the primary probe with
its expected correct behaviour, the opportunistic follow up, `facts_to_elicit`,
`claims_to_verify`, the caller id cover line, the call index and the axis score.
Twenty six files are on disk for thirteen graded calls, because scenarios were also
planned and skipped. The directory is gitignored.

One observable detail worth knowing: several of these files have the caller facing
fields in the third person, for example `13-insurance-fast-followup.json` whose goal
begins "She has a clear answer". Those are the cases `src/persona.py` rewrites to
second person at call time.

---

## Section 3: The prompt files

These are components, not documentation. Each one is the entire behaviour of one
stage, and each is loaded by name through `store.load_prompt`.

### `src/prompts/conversation.md`
**Responsible for.** How the caller behaves on the phone: what it is, how it talks,
what it does when an answer does not answer, and how it treats its own tools.

**Constraints it encodes.**
- The caller is a patient who dialled from outside. Everything about the clinic comes
  from the other voice; everything about the caller's own life is theirs to know and
  they answer when asked.
- Short turns, most under fifteen words. No restating what was heard, no flagging
  uncertainty, no describing its own understanding.
- One line it never crosses: it never speaks as the clinic. If a sentence would sound
  normal from the person answering the phone, it is the wrong sentence.
- A precedence rule for the three competing pressures: having the answer ends the
  topic, not having it earns exactly one more ask, and the third raising of the same
  thing is nagging.
- Recordings, hold music and menus are not people and get no answer.
- The three tools happen inside its head, make no sound, and return codes that are
  never spoken or paraphrased.

**Why those constraints.** Every one is a fix for something heard on a real call. The
"never speaks as the clinic" line is `DEVLOG` 19, where the bot drifted into
receptionist voice and offered to look something up for the other party. The
precedence rule is `DEVLOG` 13, where it asked the same question twice in one call.
The "no describing your own understanding" line is `DEVLOG` 12. The word choice
matters too: an earlier version of this prompt said "never say you are checking
something", and the prohibition supplied the model with the exact words it then used.

**Not in it, deliberately.** There is not one word about testing, evaluation, defects,
or AI. The caller does not know it is a QA agent. That is the single most important
design decision in the project and this file is where it is enforced.

### `src/prompts/planner.md`
**Responsible for.** Turning an eight axis tuple into a specific human being with a
motive, a situation, and hard constraints.

**Constraints it encodes.**
- Give the motive, never the behaviour. Given `cooperation: self_correcting`, the
  wrong output is "the caller changes their mind twice" and the right output is a
  caller reading a shift rota that keeps updating.
- One primary probe per call, at most one opportunistic follow up, and never two
  planned pressures at once. Sequence is allowed, simultaneity is not.
- Every persona carries at least two hard constraints tight enough that the obvious
  appointment slot fails.
- Never invent a clinic fact. The caller may only carry a fact about the clinic if it
  is already in the oracle, and only as the oracle states it.
- Never invent identity details, and never volunteer them. The caller gives its date
  of birth when asked and not before.
- The caller never takes the service side: never offers help, never asks what the
  clinic needs, never closes the call on the clinic's behalf.
- The goal must be an outcome achieved, not a fact learned.
- A block of observed facts about this specific agent: it gates everything behind a
  profile, it ends calls unilaterally, it has shown no cross call memory, and it
  answers in several sentences with pauses between them.

**Why those constraints.** The single pressure rule is evidential rather than
aesthetic: if two pressures overlap and the agent fails, nobody can say which caused
it, and an unattributable defect is one nobody will fix. The no invented clinic facts
rule prevents the worst kind of false finding, a caller contradicting the agent with
something the agent never said. The observed facts block exists because scenarios that
ignored them produced thirty second calls that proved nothing, and the profile
mismatch rules in particular killed two early calls inside a minute.

**Shape.** It ends with the exact JSON schema and two fully worked examples including
the reasoning behind each one.

### `src/prompts/goal_judge.md`
**Responsible for.** Deciding, mid call, whether there is any reason for the caller to
still be on the line.

**Constraints it encodes.**
- Three outcomes only: `goal_met`, `unachievable`, `not_yet`.
- A refusal and a referral are both outcomes. If the agent has sent the caller
  elsewhere or said the thing cannot be done, the caller has everything this call will
  give them.
- Judge only the goal in front of you, not everything that could have been asked.
- Politeness and whether the call felt complete are explicitly not the goal.
- A caller still being offered options has not been refused, and stays `not_yet`.

**Why those constraints.** Without the explicit `unachievable` branch, a call that has
clearly hit a wall keeps running to the four minute watchdog and burns a call slot.
Without the last rule the judge grants a hangup while the agent is still mid offer.
The prompt is short because it runs inside a two second timeout on a live call.

### `src/prompts/analyst.md`
**Responsible for.** Sorting what the agent said into five buckets: facts,
capabilities, claims, promises, entities.

**Constraints it encodes.**
- Extraction only, never judgment. Sorting a sentence by tense and subject is the job;
  deciding whether what it described actually happened is not.
- The categories are not mutually exclusive, and a sentence goes in every category it
  belongs to. There is a worked example showing one booking confirmation producing
  three entries.
- Facts map to exactly one of ten fixed slot names, and no other name.
- Capabilities use the same short `ability` handle for the same power every time,
  because two capability statements are only comparable if their handles match.
- A promise is not a claim. A claim is past tense and can only be checked on a later
  call; a promise is future and is usually settled before this call ends.
- One action, one entry. An agent taking three sentences over a transfer is one
  promise, not three. Imperatives to the caller are never recorded at all.
- Only the agent's speech, never the caller's.

**Why those constraints.** The claim and promise distinction is load bearing: filing a
promise as a claim sends a human to make a phone call to check something the recording
already answers. The ten slot restriction is what makes cross call comparison possible
at all, and `src/ledgers.py` drops anything else with a warning. The handle
consistency rule is what the mechanical contradiction detector depends on, and where
it fails is exactly what `contradiction_review.md` exists to catch. The closing line
says precision beats recall, because a fact in the wrong slot poisons every later
comparison.

### `src/prompts/promise_kind.md`
**Responsible for.** Sorting each promise into `vacuous`, `out_of_band` or `in_call`.

**Constraints it encodes.**
- The model is not given the calls, and the prompt says this is deliberate.
- A test for vacuous: name the event that would count as fulfilment, and if the only
  answer is a restatement of the promise, it is vacuous.
- A transfer is always `in_call`, however it is worded.
- The specific split on support teams: "I'll connect you to our support team" is a
  transfer and `in_call`, "I'll make sure our support team follows up" is a callback
  and `out_of_band`.
- When a sentence carries both, classify by what the agent commits to doing during
  this call.

**Why those constraints.** Withholding the transcript is the interesting one.
Knowing how the call turned out would tempt the model to answer whether the promise
was kept, which is a different question and is the resolver's job. The support team
split is here because it is the exact ambiguity this agent produces most often.

### `src/prompts/resolver.md`
**Responsible for.** Settling each in call promise against the transcript that
followed it.

**Constraints it encodes.**
- The rule that overrides everything: saying is not doing. Announcing, offering,
  restating, or asserting completion is not the action happening. It lists four
  example sentences that fulfil nothing.
- Judge from the remainder only. What came before the promise cannot settle it.
- Read the whole remainder before deciding, because the first encouraging line is
  usually not the one that decides.
- For a transfer, `fulfilled` only if a different party engages with the caller's
  actual problem. A recorded message, a greeting that never engages, a hangup, or the
  same agent carrying on are all `unfulfilled`.
- Evidence must be one line copied character for character out of the remainder,
  including its `[M:SS] SPEAKER:` prefix.
- `vacuous` is explicitly not an outcome this pass may return.

**Why those constraints.** The prompt says plainly that marking a promise fulfilled
because the agent said the words is the single worst error available here, because it
is exactly the failure this pass exists to catch. The verbatim quote requirement is
enforced downstream by `src/promise_gate.py`, and the prompt warns that a quote which
is not found gets the promise downgraded and loses a real finding, which gives the
model a reason to copy rather than paraphrase.

### `src/prompts/contradiction_review.md`
**Responsible for.** The two contradiction classes exact matching cannot reach.

**Constraints it encodes.**
- Job one, the same power under two different handles, but only when the two entries
  mean the same power in the same sense. It gives a counterexample: checking whether
  the clinic takes an insurer and validating one member's plan are not the same power.
- Job two, a statement against a behaviour, where the demonstration must be something
  the agent actually did, not something it announced or claimed.
- Reciting a detail is a demonstration of access only if the caller never supplied that
  detail on this call. Read the call back before relying on a recitation.
- Quotes must be verbatim and are discarded if not found.
- Precision matters more than coverage. Report nothing rather than something you are
  talking yourself into.

**Why those constraints.** The recitation rule is the sharp one. Without it, an agent
repeating back a date of birth the caller gave two turns earlier looks like proof of
record access, and a finding built on that is simply false. The prompt states the cost
of a loose report in human terms: it sends someone through a recording to disprove
something that is not there. In practice one of this pass's three proposals argued a
contradiction while its own reasoning said the two statements agreed, which is why
nothing from this tier reached `BUGS.md` unsupported.

---

## Section 4: Data artifacts

### What one call directory contains

`data/campaign/calls/call-NN/` holds eight files.

| File | Written by | What it is |
|---|---|---|
| `call.json` | `src/server.py` | The call record: call id, scenario id, the axes, the identity, the Telnyx call sid, from and to numbers, when it was placed, the resolved turn detection settings, every Telnyx status callback, and the recording metadata added later. |
| `instructions.txt` | `src/event_tap.py`, via `src/bot.py` | The exact assembled prompt the caller model was given for this call. |
| `events.jsonl` | `src/event_tap.py` | Every message in both directions on the OpenAI realtime websocket, plus our own lifecycle events, with a relative timestamp. Audio payloads are elided but counted. |
| `turns.jsonl` | `src/turn_log.py` | Our live view of the conversation: each bot turn, each agent turn as we heard it, and each tool call with its arguments and result, with elapsed seconds. |
| `recording.mp3` | `scripts/fetch_and_transcribe.py` | The stereo 8kHz recording from Telnyx, one party per channel. |
| `transcript.json` | `src/transcribe.py` | The full Deepgram response, including per word confidence scores. |
| `transcript.txt` | `src/transcribe.py` | The readable transcript, one line per utterance, `[MM:SS] AGENT:` or `[MM:SS] BOT:`. |
| `extraction.json` | `src/analyst.py` | What the analyst returned for this call, what was applied to the ledgers, and what was skipped with the reason. |

A ninth file, `observations.jsonl`, is created by `silent_note` when the caller uses
it. No campaign call directory has one, so that tool was never called during the
graded campaign. Across the thirteen graded calls the tool log shows twelve
`silent_compare` calls and eight `hang_up` calls.

### Evidence versus internal state

**Evidence for the bug report.**
- `recording.mp3` is the ground truth. Everything else about the far end derives from
  it.
- `transcript.txt` is what every quote in `BUGS.md` comes from, and what the resolver
  and the contradiction detectors verify quotes against.
- `transcript.json` is the evidence about the evidence. Its per word confidence scores
  are what let `BUGS.md` say that a provider name discrepancy could not be separated
  from transcription error, with actual numbers.
- `call.json` supplies the timing, the duration, who hung up and why, and the caller id
  the phone recital detector matches against.
- `data/campaign/judgments.json` is the assembled findings: every promise resolution
  with its gate notes, the capability pairs, the phone recitals and findings, and the
  model proposed candidates.

**Internal state, about our own system.**
- `instructions.txt` is what our caller was told to be. It is not evidence about the
  clinic agent, but it is what lets any finding be traced back to the situation that
  produced it.
- `turns.jsonl` is our side's view. Its agent lines came through the realtime model's
  own transcription, which is a different transcription from Deepgram's, so it is a
  working view and not the citable one.
- `events.jsonl` is diagnostic for our harness. It is where the `DEVLOG` bugs were
  found and where the latency numbers come from.
- `extraction.json` is an audit trail of the analyst, not a finding.

**Campaign wide state.** `oracle.json` holds ten fact slots with the call and
timestamp where each was stated. `capabilities.json`, `claims.json` and
`promises.json` are append only ledgers. `frontier.json` holds entities the agent
volunteered that nobody has followed up. `suspicions.json` is empty, and the README is
explicit that this is a limitation: suspicions are only raised automatically when two
stated facts about the same slot conflict, which never happened, so the exploitation
half of the scoring never engaged. `call_counter.json` is the spend guard's memory.

One thing to be able to say plainly: a claim can only be verified on a later call, and
the agent has no cross call memory, so `claims.json` being unverified is not an
oversight. It is the finding.

---

## Section 5: The five things most likely to be asked about

### 1. The caller is never told it is testing

**They will ask.** "Your caller agent is hunting for bugs. Why doesn't its prompt
mention that anywhere?"

**Say.** Because a caller that interrogates gets treated as an interrogation, and the
agent under test shifts into a careful hedged register and stops doing the ordinary
thing that would have exposed the bug. So the bug hunting lives entirely before the
call, in scenario selection: the planner knows the mission, and the caller only knows
it has a sore knee and eight minutes of lunch break left. The pressure that finds the
defect is built into the situation, not into the questions, and the richest failures
showed up when the agent believed it was talking to a person with a problem.

### 2. Scenario selection is arithmetic, not a model

**They will ask.** "You have models everywhere else. Why is `scoring.py` a hand
written scoring function?"

**Say.** Coverage is a counting problem, and a model asked "what should we test next"
drifts toward whatever it just read rather than toward what has not been tried. So the
sampler draws 200 random tuples and scores each on novelty, which is one over the
square root of one plus times used, and on uncovered pair fraction, which is standard
all pairs coverage on the grounds that most interaction bugs come from a pair of
conditions. The score interpolates toward chasing open suspicions as the campaign
advances, and I should be upfront that half never engaged: the suspicion ledger stayed
empty across thirteen calls, so selection was pure exploration throughout.

### 3. The promise gate refuses to take the model's word

**They will ask.** "You use an LLM to decide whether a promise was kept. How do you
know it isn't making that up?"

**Say.** Because `src/promise_gate.py` checks the model's answer before accepting it,
and every override is written into the judgment record. The evidence quote must appear
verbatim in the transcript after the promise, or the verdict is thrown out as
`evidence_not_found`, which is the check that stops a fluent model resolving a promise
against a sentence it imagined. If the model says it could not tell because the call
ended too soon, that reason is checked against the actual seconds and agent turns
remaining, and a promise made with under fifteen seconds or zero agent turns left is
`call_ended_too_soon` no matter what the model said. It mattered in practice: the
resolver initially scored BUG-13 as fulfilled and that verdict was overruled by hand.

### 4. Reasoning commentary leaking into the audio

**They will ask.** "What was the hardest bug you hit building this?"

**Say.** The bot kept saying things like "let me think this through" out loud, and it
looked like five separate prompt failures across five calls. It was one bug:
`gpt-realtime-2.1-mini` emits its reasoning as a real assistant message carrying
`"phase": "commentary"` in the same response as the actual reply, and Pipecat has no
concept of phase, so those audio deltas went out over the phone like any other. The fix
in `src/realtime_llm.py` tracks item ids whose phase is commentary, read from the raw
server event because Pipecat's parsed model drops unknown fields, and drops their audio
before it reaches the transport. The second order fix in the same change matters as
much: the response gate had been counting commentary as speech, so suppressing it made
the bot mute until the gate learned to ignore commentary items.

### 5. The hangup gate

**They will ask.** "How does the call know when to end?"

**Say.** Four conditions, checked in order, and only one of them involves a model. The
caller's `hang_up` tool is granted if the clock is within thirty seconds of
`MAX_CALL_SECONDS`, or the caller has already been nudged twice, or the conversation
has stalled by content word overlap, or a goal judge says the goal is met or
unachievable. The judge runs on a two second timeout and fails closed, so a slow or
broken judge denies the hangup rather than ending a live call, and the watchdog is the
backstop that guarantees the call ends anyway. A denial is not just returned either,
because a single denial used to leave the model silent, so a denial schedules a nudge
forty five seconds later carrying a code shaped payload the model will not read aloud.

---

## Things I could not determine from the code

Stated rather than guessed:

- **`scripts/test_commentary_filter.py` versus `scripts/smoke_replay.py`.** Both test
  the commentary filter, one with synthetic events and one by replaying real calls.
  Only `smoke_replay.py` is wired into the smoke suite. Whether the synthetic one is
  meant to stay is not clear from the code.
- **`claims_to_verify`.** The planner emits this field and `plan_call.py` prints it,
  but nothing reads it to drive behaviour. The `continuity: verifies_claim` axis is
  handled in `scoring.is_valid`, which checks whether unverified claims exist at all,
  not which ones. Consistent with the README's statement that cross call claim
  verification never resolved anything, but the field's intended consumer is not in the
  code.
- **`data/calls_scaffold/`.** Four call records from 2026-08-17 keyed by Telnyx session
  id, to a personal number, with no scenario id. They read as infrastructure test calls
  from before the call id scheme existed, and `DEVLOG` entry 9 refers to scaffold calls
  inflating the call index. Nothing in the code reads this directory.
- **`data/campaign/calls/smoke/` and `data/campaign/calls/exit-path-test/`.** Test
  artifacts written into the campaign tree by smoke checks that use real call ids.
  Harmless, and `campaign_call_ids()` filters them out by regex, but whether leaving
  them on disk is intentional is not clear.
