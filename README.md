# Autonomous Voice QA Agent

This system places real phone calls to a company's patient-facing AI voice agent,
holds a natural conversation with it as a patient, records and transcribes both
sides, and reports defects in that agent's behaviour.

The target is Pivot Point Orthopedics, a fictional demo clinic reachable at
+1 805 439 8008. Thirteen graded calls were placed between 2026-08-20 and
2026-08-27. Thirteen defects are written up in [BUGS.md](BUGS.md), three of them
critical. Bugs we found in our *own* harness while building it are in
[DEVLOG.md](DEVLOG.md), kept separate on purpose so the two are never confused.

---

## 1. The problem, and the constraint that shaped everything

Ordinary QA compares behaviour against a specification. A clinic's real hours are
published, so an agent that says "we're open Sunday" is wrong and you can prove
it.

Pivot Point Orthopedics does not exist. There is no website, no published hours,
no provider list, no insurance panel, no cancellation policy. There is nothing to
check any answer against. If the agent says it opens at 8am, that statement is
neither true nor false in any way an outsider can establish.

That single constraint decided the architecture. If there is no external
specification, then **the agent's own statements become the specification**. Every
sentence it says about the clinic is recorded as an assertion, and the system
looks for places where those assertions do not hold together, or where the agent's
behaviour contradicts them. A fact is not checked against the world. It is checked
against the agent's own earlier words, against what it claims it can and cannot do,
and against what it actually did on the call.

This gives a natural ordering of how strong a finding is, and every entry in
BUGS.md is tagged with which tier it came from:

| Tier | What it is | Why it is strong or weak |
|---|---|---|
| **Self-contradiction** | The agent said A, then said not-A | Strongest. Needs no outside knowledge. Whichever statement is true, one of them is a defect. |
| **Statement against behaviour** | It said it could not do X, then did X (or the reverse) | Strong, but needs care about whether the two really refer to the same thing. |
| **Verified by hand** | A quote read against the call, judged on its face | Strong for things that are wrong on any reading: inventing a date of birth, naming a patient to a stranger. |
| **Model-proposed** | An LLM pass suggested a contradiction | Weakest. Treated as a worklist for a human, never as a finding. Nothing from this tier is in BUGS.md unless the quoted evidence stands alone. |

The transcription floor matters too, and BUGS.md has a section called *Not
reported, and why* listing things that looked like defects but could not be
separated from 8kHz transcription error. Discarding a plausible finding is part of
the job, not a failure of it.

---

## 2. Architecture, and why each piece is what it is

```
  scenario space  ──►  planner  ──►  validator  ──►  live call  ──►  recording
  (8 axes, ~200k)      (LLM)        (6 rules)      (realtime      (Telnyx,
        ▲                                            speech)       stereo mp3)
        │                                                              │
        │                                                              ▼
        │                                                         transcript
        │                                                         (Deepgram)
        │                                                              │
        └──────────  ledgers  ◄─── analyst extraction  ◄───────────────┘
                        │            (facts, capabilities,
                        │             claims, promises, entities)
                        ▼
              promise resolver + contradiction detector  ──►  BUGS.md
```

### Speech-to-speech, not a cascaded pipeline

A cascaded pipeline runs speech-to-text, then a text LLM, then text-to-speech.
It is easier to debug because every stage is inspectable text. It also adds
roughly a second of latency per turn, and it throws away everything that is not
words: the hesitation, the half-started sentence, the overlap when someone starts
talking before you finish.

The first thing this system is evaluated on is whether the bot holds a coherent
voice conversation. A caller that pauses a beat too long before every reply does
not sound like a patient, and an agent under test behaves differently towards
something that does not sound like a patient. So the in-call model is OpenAI's
`gpt-realtime-2.1-mini` speech-to-speech, running over Pipecat 1.7.0. Audio goes
in, audio comes out, and turn-taking is handled by the model's own semantic voice
activity detection rather than a fixed silence timer.

The cost of this choice is that the model's internal reasoning can leak into the
audio channel, which took several rounds to fix (DEVLOG #27, #28, #31). That was
worth paying.

### Telnyx, because it deleted a component

The bot needs a phone line, and it needs a recording of both sides to analyse
afterwards. Telnyx does server-side recording on the outbound voice profile and
produces a **stereo 8kHz MP3 with one party per channel**: channel 0 is their
agent, channel 1 is ours.

That is worth more than it sounds. Recording locally would mean capturing our own
outbound audio, capturing the inbound stream, aligning them, and dealing with the
fact that neither side's timestamps are trustworthy. Server-side dual-channel
recording removes that component entirely, and it removes the class of bug where
the analysis blames the wrong speaker. The channel mapping was verified
empirically on a test call and is asserted by a check in the smoke suite, because
getting it backwards would mean every finding in the report is attributed to the
wrong party.

Deepgram Nova-3 transcribes the stereo file in multichannel mode, so speaker
attribution comes from the wire rather than from diarisation.

### The most important design decision: the caller does not know it is testing

The in-call model is **never told it is hunting for bugs**. Its prompt
(`src/prompts/conversation.md`) tells it that it is a patient who dialled a clinic,
what it needs, and what it knows about its own life. There is not one word in it
about testing, evaluation, defects, or AI.

The reason is behavioural. A caller that interrogates gets treated as an
interrogation. If the caller says "can you confirm you would never schedule
outside your posted hours", the agent shifts into a careful, hedged, defensive
register and stops doing the ordinary thing that would have exposed the bug. The
richest failures showed up when the agent believed it was talking to a person with
a problem.

So bug-hunting lives entirely **before** the call, in scenario selection. The
planner knows the mission. The caller only knows it has a shoulder strain and
eight minutes of lunch break left. The pressure that finds the defect is built
into the situation, not into the questions.

The same logic applies to the caller's three tools. They are described to the
model as private thoughts: `silent_compare` "records one checkable fact the
receptionist has just asserted", `silent_note` is "a private thought",
and their results come back as bare codes, never sentences, because anything
resembling prose in a tool result gets read aloud (DEVLOG #17, #18).

---

## 3. How one call gets planned

### The scenario space: eight axes

Every call is a point in an eight-dimensional space defined in `data/axes.json`:

| Axis | Values |
|---|---|
| `intent` | book, reschedule, cancel, refill, insurance, hours, out_of_scope |
| `identity` | akhil, dana, elena, robert |
| `temporal` | explicit, relative, ambiguous, past, holiday, after_hours |
| `cooperation` | full, partial, self_correcting, contradictory, distracted |
| `delivery` | clean, fast_digits, spelled_name, interrupting, trailing_off |
| `register` | neutral, rushed, confused, frustrated |
| `continuity` | fresh, references_prior, verifies_claim |
| `curveball` | none, second_intent, urgency_mention, out_of_scope_ask |

That is about 200,000 tuples, against a budget of thirteen calls. The axes are
chosen so that each one independently stresses a different part of a receptionist
agent: `temporal` stresses date resolution, `delivery` stresses capture accuracy,
`cooperation` stresses state tracking, `continuity` stresses memory.

The four identities are fixed people with fixed details (`data/identities.json`),
never invented per call, so the same name and date of birth arrive on every call
that identity makes. One of them, Akhil, is the identity the Telnyx caller ID
belongs to; the other three are calling from a number that is not theirs, which is
itself a test surface, and each carries a `caller_id_cover` line for when the agent
addresses them by the wrong name.

### Choosing a tuple by arithmetic, not by asking a model

`src/scoring.py` samples 200 random candidate tuples and scores each one, rather
than asking an LLM which scenario to run next. Arithmetic was chosen deliberately:
coverage is a counting problem, and a model asked "what should we test next?"
drifts toward whatever it just read about instead of toward what has not been
tried.

The score interpolates between exploration and exploitation as the campaign
progresses. With `w = call_index / total_calls`:

```
score = (1 - w) * explore + w * exploit
```

`explore` is the mean of two terms. **Novelty** rewards axis values that have been
used rarely, as `1/sqrt(1 + times_used)` averaged over the tuple, so the fifth use
of a value is worth much less than the first. **Uncovered pair fraction** is the
share of this tuple's 28 axis-value pairs that no previous call has produced,
which is standard pairwise (all-pairs) test coverage: most interaction bugs come
from a pair of conditions, so covering pairs buys most of the value of covering
whole tuples at a tiny fraction of the cost.

`exploit` is a lead score over open suspicions. For each unconfirmed suspicion it
adds `relevance * (1 - confidence) * severity_weight`, where relevance is the
fraction of the suspicion's implicated axis values this candidate reproduces. The
`(1 - confidence)` term means a maybe is worth more to chase than a near-certainty,
and the severity weight means a critical maybe outranks a low one.

Three validity rules run before scoring. A tuple asking to verify a prior claim is
rejected when there are no unverified claims. A tuple referencing a prior call is
rejected in the first two calls. And the first two calls are pinned to a
discovery tuple (akhil / full cooperation / neutral / no curveball), because the
system needs to know how the agent behaves at rest before it can recognise a
deviation.

Any axis can be pinned by hand for a run: `--identity dana`, or
`--axis temporal=holiday --axis register=frustrated`. The sampler chooses the rest,
and the scoring only ever considers the free axes so a pin does not distort the
coverage arithmetic.

### The planner turns a tuple into a person

A tuple is a set of constraints, not a scenario. `src/planner.py` sends the tuple,
the chosen identity, the oracle (everything the agent has already said about
itself), the unprobed frontier, open suspicions and unverified claims to a text
model with the prompt in `src/prompts/planner.md`, and gets back a person.

The prompt's core instruction is *give the motive, never the behaviour*. Given
`cooperation: self_correcting`, the wrong output is "the caller changes their mind
twice", which produces a model performing a personality. The right output is a
caller reading a shift rota that keeps updating, which produces a person whose mind
genuinely changes because their situation does. The persona carries hard
constraints tight enough that the obvious appointment slot fails, because a caller
who accepts the first offer cannot find a scheduling bug.

It also carries what the campaign has already learned. When the oracle is empty the
mission is elicitation. When the frontier has entries, the agent named something
nobody followed up on and the planner builds a caller with an ordinary reason to
care about that specific thing, which is how the system finds tests nobody
designed. The prompt also carries a block of observed facts about this particular
agent, so scenarios do not waste a call on a path already known to die in thirty
seconds.

### The validator rejects bad scenarios before they cost a graded call

Each graded call costs money and one of a small number of daily slots, so
`scripts/campaign_scenario.py` checks the planner's output before anything is
dialled, and a rejected scenario is regenerated up to three times. The six rules
are all lessons paid for with a wasted call:

1. `facts_to_elicit` must name real oracle slots, not invented ones.
2. The caller-facing fields must be in the second person. A stray "he" leaves the
   caller reading about themselves in the third person.
3. The `goal` must be an outcome achieved, not a fact learned. "You know their
   opening hours" is not a reason a person picks up a phone.
4. The persona must not make the caller unsure of a fact about their own life.
   Their dates and shifts are theirs to know; uncertainty belongs to things the
   clinic owns.
5. The persona must not have the caller stonewall identification. That ends the
   call in under a minute, and it has already been recorded as a defect twice.
6. The persona's record status must match reality: a caller with a record must not
   be written as creating a profile, and a caller without one must not assert a
   record that does not exist. Both mismatches killed early calls inside a minute.

### During the call

The pipeline runs at 24kHz, which is what the realtime API requires; the Telnyx
serializer handles conversion to and from 8kHz at the wire. Three guards run
alongside the conversation. A watchdog hangs up at `MAX_CALL_SECONDS` (240). A
persisted counter refuses to dial past `MAX_CALLS_PER_RUN` (6) per day, across both
call trees. And the caller's `hang_up` tool is gated: it is granted only when a
goal judge says the goal is met or unachievable, or the conversation has stalled,
or the caller has been nudged twice, or the time override is close. The judge runs
on a 2 second timeout and fails closed, so a slow judge denies the hangup rather
than ending a live call. Getting this right took a long stretch of DEVLOG (#23,
#24, #33, #34, #35).

Everything is recorded as it happens: raw OpenAI realtime events to
`events.jsonl`, our own turn log to `turns.jsonl`, and the exact assembled prompt
to `instructions.txt`, so any finding can be traced back to what the caller was
actually told to be.

---

## 4. What happens after a call

### Extraction into four categories with different verification timescales

`src/analyst.py` reads the transcript and sorts **only what the agent said** into
five buckets, using the prompt in `src/prompts/analyst.md`. Its job is strictly
extraction: sorting a sentence by its tense and its subject. Deciding whether what
it described actually happened is judgment, and it happens in a later pass with
different evidence available.

The split is not arbitrary. Each category can be verified on a different timescale,
and that is the whole reason they are separate:

- **Facts** ("we're at Pivot Point Orthopaedics") go into the oracle, ten fixed
  slots. Verified **across calls**: a new value that conflicts with a stored one
  raises a suspicion automatically, and a value that is strictly more specific
  sharpens the stored one instead.
- **Capabilities** ("I'm not able to see which phone number is on file") are
  verified **across the whole campaign**, by pairing every affirmation of an ability
  against every denial of the same ability.
- **Claims** ("you're booked for Tuesday at 11:15") assert a completed action.
  These can *only* be verified on a **later call**, by ringing back and asking. The
  recording of this call cannot show whether the booking exists.
- **Promises** ("I'll connect you to our support team") assert a coming action.
  These are usually settled **inside this same call**, in the transcript that
  follows the promise.
- **Entities** are proper nouns the agent volunteered. They go on the frontier and
  feed back into planning.

Keeping promises and claims apart is the load-bearing distinction. Filing a promise
as a claim sends a human off to make a phone call to check something this
recording already answers.

Crucially, the categories are not mutually exclusive. "You're booked for Tuesday,
August 25 at 11:15AM with Judy Hauser at Pivot Point Orthopedic" is a claim, a
providers fact, and a locations fact, and it is recorded as all three. The most
informative thing an agent says is usually the sentence doing two jobs at once.

### The promise resolver

`src/resolver.py` settles every promise against the part of the transcript that
came after it. First a classifier sorts each promise into three kinds. **Vacuous**
promises assert nothing checkable. **Out-of-band** promises ("I'll have someone
call you tomorrow") cannot be observed on this recording at all and are marked
unresolvable for that stated reason rather than being guessed at. Only **in-call**
promises go to the resolver model.

The resolver is then given the promise, the transcript remainder after it, how many
seconds of call were left, and how many agent turns were left, and asked for an
outcome plus a verbatim quote as evidence. `src/promise_gate.py` then refuses to
take its word for it:

- The quote must appear **verbatim** in the remainder. If it does not, the verdict
  is thrown out as `evidence_not_found`. This is the check that stops a fluent
  model from resolving a promise against a sentence it imagined.
- If the resolver claims it could not tell because the call ended too soon, that
  reason is checked against the actual seconds and turns remaining. An unsupported
  reason is replaced with `reason_not_supported` and the disagreement is recorded.
- A promise made with under 15 seconds or zero agent turns remaining is
  `call_ended_too_soon` regardless of what the model said.
- The resolver is not allowed to overrule the classifier on kind.

Every override is written into the judgment record, so the gate's disagreements
with the model are themselves auditable. This mattered: the resolver initially
scored BUG-13 as fulfilled, and that verdict was overruled by hand.

### The contradiction detector

`src/contradictions.py` runs mechanically first. It groups the capability ledger by
ability handle and reports every pair where the same ability is affirmed in one
place and denied in another. It also runs a specific detector for the phone-number
case: the caller's number recited by the agent, matched against any statement that
it cannot see a number on file.

That detector ships with its own caveat attached to the finding, and the caveat is
in BUGS.md verbatim: it cannot tell a number read off caller ID from a number read
out of a stored record. Stating what a detector cannot distinguish is what makes
BUG-06 a reportable observation rather than an overclaim.

`src/contradiction_review.py` then runs a model pass for the cases mechanics
cannot reach: two capability statements about the same power under different
wording, and statements contradicted by observed behaviour rather than by another
statement. Its output is quote-verified against the transcript and labelled
`model_clustered` or `model_proposed`. That pass is a worklist for a human. One of
its three proposals argued a contradiction while its own stated reasoning said the
two statements agreed, which is exactly why nothing from that tier reaches BUGS.md
on its own authority.

---

## 5. Running it

### Setup

```
conda deactivate                       # conda's python must not be used
uv venv --python 3.12 && uv sync
cp .env.example .env                   # then fill it in
ngrok http 7860                        # copy the https URL into PUBLIC_BASE_URL
```

You need accounts with Telnyx (a number, a TeXML application, an outbound voice
profile with recording enabled), OpenAI, and Deepgram.

### Environment

| Variable | What it is |
|---|---|
| `TELNYX_API_KEY`, `TELNYX_ACCOUNT_SID`, `TELNYX_APPLICATION_SID` | Telnyx credentials and TeXML app |
| `TELNYX_PHONE_NUMBER` | Caller ID for outbound calls |
| `OPENAI_API_KEY`, `DEEPGRAM_API_KEY` | Realtime and planning models; transcription |
| `PUBLIC_BASE_URL` | The ngrok https URL, no trailing slash. Changes on every ngrok restart. The server reads its public URL from here and never from the request `Host` header. |
| `TARGET_NUMBER` | The agent under test |
| `MAX_CALL_SECONDS` | Hard per-call timer, default 240 |
| `MAX_CALLS_PER_RUN` | Daily call cap, default 6 |
| `REALTIME_MODEL`, `PLANNER_MODEL` | In-call speech model; text model for planning and analysis |
| `CALL_TREE` | `campaign` (graded, default) or `roleplay` (development) |
| `TURN_DETECTION`, `VAD_EAGERNESS`, `VAD_THRESHOLD`, `VAD_SILENCE_MS` | Turn-taking. Config validates on import and refuses combinations that do not apply to the selected mode. |

### The one command

```
uv run python src/server.py            # terminal 1
uv run python scripts/run_campaign.py  # terminal 2
```

`run_campaign.py` is the whole loop. It preflights the server, checks ngrok is
serving the URL in `.env`, and checks the daily cap; plans and validates a
scenario, retrying up to three times; prints it and waits for you to confirm
before dialling anything; dials, streams the live transcript to the terminal as it
happens, waits for Telnyx to report completion; then fetches the recording,
transcribes it, extracts it into the ledgers, and prints a summary. Then it offers
to do it again.

The confirmation gate is deliberate. Each call is real money on a real phone line,
and a bad scenario is better caught by a human reading it for five seconds than by
spending a call slot on it.

Other entry points:

```
uv run python scripts/plan_call.py --identity dana     # plan only, do not dial
uv run python scripts/run_campaign.py --axis temporal=holiday
uv run python scripts/run_campaign.py --scenario path/to/scenario.json
uv run python scripts/judge_campaign.py                # resolve promises, detect contradictions
uv run python scripts/smoke.py                         # pre-call regression suite
```

`smoke.py` runs nine checks before any call is placed, each one guarding a bug that
was found the expensive way: prompt assembly, VAD configuration, the hangup gate,
the goal judge timeout, tool-payload hygiene, the commentary filter replayed
against two calls it took three rounds to fix, the oracle slot guard, the
transcript channel mapping, and the check that a graded call cannot land in the
roleplay tree.

---

## 6. What we found

Thirteen calls produced thirteen defects, written up in [BUGS.md](BUGS.md) with
timestamped quotes and, for each, what a correct agent would have done.

The headline finding is that **the agent cannot serve any caller who has an
existing record**. In eight of thirteen calls it never reached the caller's actual
request: the call was consumed by identity verification, verification failed, and
the agent announced a transfer that landed on a recorded dead end. The only two
calls that completed their task were ones where a profile was created fresh and
there was nothing to check against.

Three findings are critical, and all three are about identity. The agent invented a
patient's date of birth and stored it, which then became the baseline that later
callers were authenticated against. It detected an identity mismatch, announced
which field had failed, and waived it. And it used inbound caller ID to look up a
record and spoke a patient's name aloud to a caller who had not yet identified
themselves at all.

The remainder are failures of honesty about its own state: claiming to have sent a
text that never arrived, reciting a phone number it elsewhere said it could not
see, four consecutive hold messages covering a lookup that never returned anything,
and asking the caller whether they would like to be transferred and then
transferring regardless of the answer.

---

## 7. Limitations, and what we would build next

**The exploit half of the scoring never engaged.** Suspicions are raised
automatically only when two stated facts about the same oracle slot conflict, and
across thirteen calls that never happened — the agent was too consistent about the
handful of facts it would state at all. So the suspicion ledger stayed empty, the
lead score was always zero, and scenario selection was pure exploration for the
whole campaign. The contradictions that were found came from the capability and
promise ledgers, which currently feed the report but not the planner. Wiring the
contradiction detector's output back into the suspicion ledger is the single
highest-value change to the loop, and it is the difference between a system that
covers a space and a system that closes in on something.

**Cross-call claim verification never resolved anything.** The design has calls
that ring back to verify a claim from an earlier call. The agent has no memory
across calls, so every such attempt hit a fresh identity check and died there. The
mechanism is built and the `continuity: verifies_claim` axis exists; it has not
been shown to work against an agent that would actually remember.

**Out-of-band actions are invisible.** The resolver can settle a promise that
resolves in the transcript. It cannot see whether a text was sent or a callback
happened. BUG-05 required a human to check a phone and confirm no message arrived,
and the eight callback promises across the campaign remain unresolvable in
principle. Closing this needs a receiving number the system can poll.

**One open question is unresolved for want of a phone number.** BUG-06 cannot
distinguish the agent reading caller ID from the agent reading a stored record,
because every call was placed from the same Telnyx number. A single call placed
from a number that is on no patient record would settle it, and that is the first
call we would place next.

**Transcription is the evidence floor.** Everything is analysed from an 8kHz
recording via Deepgram. Name-level findings are not reportable at that quality: we
have direct proof the transcriber mangles the clinic's provider name on a channel
where we know the ground truth, which is why an apparent provider-name
inconsistency is in the *Not reported* section rather than the findings. A pass
that listens to the recordings would settle several of these.

**Scale.** Thirteen calls, one target agent, one campaign, no repeat runs. There is
no regression mode that re-dials a fixed scenario to check whether a fix held, no
parallelism, and a human confirmation gate on every call. Those are the right
trade-offs for a graded assessment on a metered phone line and the wrong ones for
continuous testing. The pieces that would need to change are the confirmation gate,
the daily cap, and a stable scenario-replay path — all three are small next to what
already exists.

**The persona rewriter is regex-based.** Planner output that slips into the third
person is rewritten to second person by pattern matching over pronouns and verb
forms. It handles the cases seen so far and warns when it finds mixed person rather
than guessing. It would not survive an unusual sentence, and the validator catching
the problem upstream is what actually protects the call.
