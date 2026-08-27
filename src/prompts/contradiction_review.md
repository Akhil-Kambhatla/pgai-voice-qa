# Contradiction Review

You are given a capability ledger extracted from thirteen phone calls to one medical clinic's AI receptionist, and everything that agent said across all of them. Each capability entry records a sentence in which the agent said it can or cannot do something, an `ability` handle naming that power, and `can` as true or false.

An exact-match pass has already reported every pair of entries that share an `ability` handle and disagree on `can`. You are here for the two things exact matching cannot do.

## Job one: the same power under two handles

The handles were written call by call, so one power can appear as `access record`, `view record details`, `find record` and `locate record`. Two entries that name the same power under different handles and disagree on `can` are a contradiction the exact pass missed.

Report a pair only when the two entries are about the same power in the same sense. `check insurance` and `confirm coverage` are not the same power if one means looking up whether the clinic takes an insurer and the other means validating a specific member's plan. A pair you report loosely costs someone a trip through a recording to disprove it.

Ignore pairs whose handles already match exactly. Ignore agreeing pairs.

## Job two: a statement against a behaviour

The agent asserting it cannot do something it demonstrably did somewhere in these calls, or asserting it can do something it demonstrably failed at. The demonstration and the assertion may be in different calls; the agent is the same system throughout.

The demonstration must be something the agent actually did in the transcript, not something it said it would do and not something it claimed to have done elsewhere. Announcing a transfer is not a demonstration of transferring.

Reciting a detail aloud is a demonstration of access only when the caller never supplied that detail on this call. Read back the call before you rely on a recitation. If the caller gave their name and date of birth two turns earlier and the agent repeated them to confirm, the agent demonstrated nothing but listening, and a finding built on it is false. A detail the caller never gave and the agent produced anyway is the real signal.

Quote the demonstrating utterance in `evidence`, copied character for character from the text you were given for that call, and name the call in `evidence_call_id` and its timestamp in `evidence_at`. A quote that is not found verbatim in that call is discarded, so copy, do not paraphrase, and do not merge two utterances.

Precision matters more than coverage here. A false contradiction sends someone to check a recording for something that is not there. Report nothing rather than something you are talking yourself into.

## Output

Emit only JSON, no preamble, no code fences. Either list may be empty.

```
{
  "synonym_pairs": [
    {"affirmed_id": "cap-01", "denied_id": "cap-02",
     "shared_power": "looking up the clinic's past hours",
     "rationale": "One sentence on why these name the same power."}
  ],
  "statement_against_behaviour": [
    {"capability_id": "cap-25",
     "evidence_call_id": "campaign/call-08",
     "evidence_at": "1:16",
     "evidence": "I have your number as (207) 804-8142.",
     "rationale": "One sentence on what the utterance demonstrates."}
  ]
}
```
