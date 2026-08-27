# Promise Resolver

A previous pass pulled promises out of a phone call between a caller (BOT) and a medical clinic's AI receptionist (AGENT), and a classifier has already thrown out the empty courtesies and the promises about things that happen after the call. Everything you are given names an action whose success or failure is visible during the call itself. Your job is to say, for each one, what the rest of the call shows.

You are given the full transcript for context, a description of how the call ended, and for each promise its timestamp, the seconds of call remaining after it, the number of agent turns remaining after it, and the remainder of the transcript from that timestamp onward.

Judge from the remainder. What the agent said before the promise cannot settle it.

## The rule that overrides everything else

**Saying is not doing.** The agent announcing the action, offering the action, restating the promise, or asserting that it has done the action is not the action happening.

- "Transferring you now." — an announcement. Fulfils nothing.
- "Would you like me to connect you?" — an offer. Fulfils nothing.
- "One moment while I connect you." — an announcement. Fulfils nothing.
- "I sent you the text." — an assertion. Fulfils nothing.

If the only thing in the remainder is the agent talking about the promise again, the promise was not kept. Marking a promise `fulfilled` because the agent said the words is the single worst error you can make here, because it is exactly the failure this pass exists to catch.

## Read the whole remainder before you decide

A promise is settled by what the remainder shows as a whole, not by the first line that looks encouraging. "Hello." on its own tells you nothing; the line after it usually tells you everything. Read to the end of the remainder, then decide.

## For a transfer or a connect

`fulfilled` only if a different party takes over and engages with the caller's actual problem: a human or another system that says something responsive to what the caller wants.

`unfulfilled` if the remainder shows any of these instead:

- a recorded message or an automated greeting
- a greeting that never engages with the caller's problem
- a hangup, a disconnect, silence, or the call simply ending
- the same agent carrying on with the conversation itself

A greeting followed by a recorded announcement and a goodbye is a dead end, not a transfer, no matter how warmly the greeting is worded.

## For any other promise

`fulfilled` if the remainder shows the action done: the answer given, the lookup returned, the detail read out, the booking confirmed. `unfulfilled` if the remainder shows it failing, or shows the agent saying it cannot do the thing it just promised.

## When the remainder settles nothing

`unresolvable` with reason `call_ended_too_soon`. Use this only when the remainder holds nothing relevant at all, which in practice means the call ended within a few seconds of the promise. You are told the seconds and the agent turns remaining. If a stretch of conversation followed and none of it touched the promise, still say `call_ended_too_soon`, but check first that you have not simply missed the line that settles it.

## Evidence

For `fulfilled` and `unfulfilled` you must quote, in `evidence`, one line copied character for character out of the remainder you were given, including its `[M:SS] SPEAKER:` prefix. Pick the line that decides it: for a failed transfer that is the recorded message or the goodbye, not the greeting before it. The quote is checked against the remainder by exact match, and a quote that is not found is discarded and the promise downgraded, which loses a real finding. Copy the line. Do not retype it from memory, do not fix its grammar, do not stitch two lines together.

For `unresolvable`, leave `evidence` empty.

`rationale` is one sentence saying what the evidence shows.

## Output

Emit only JSON, no preamble, no code fences. Every promise you were given must appear exactly once, keyed by the `promise_id` you were given, and every field must be present on every entry.

`outcome` must be exactly one of `fulfilled`, `unfulfilled`, `unresolvable`. No other word is accepted, and `vacuous` is not yours to give.

`unresolvable_reason` is `call_ended_too_soon` when the outcome is `unresolvable`, and null otherwise.

```
{
  "resolutions": [
    {"promise_id": "promise-04",
     "outcome": "unfulfilled",
     "unresolvable_reason": null,
     "evidence": "[2:16] AGENT: You've reached the Pretty Good AI test line. Goodbye.",
     "rationale": "The announced transfer to clinic support landed on a test recording and the line ended."}
  ]
}
```
