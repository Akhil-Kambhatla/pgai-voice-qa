# Promise Classifier

You are given promises an AI receptionist made during phone calls to a medical clinic. You are **not** given the calls. That is deliberate. Your question is about the promise itself, and knowing how the call turned out would only tempt you to answer a different question.

Sort each promise into exactly one kind.

## `vacuous`

The promise names no specific action, so no event in the world would count as keeping it and none would count as breaking it.

- "I'll help you with that."
- "I'll provide the information."
- "Let me assist you."
- "I'll take care of it."

The test: name the event that would count as fulfilment. If the only answer you can give is a restatement of the promise, it is vacuous. A promise is vacuous because of what it fails to say, not because it is hard to check. "I'll book you for Thursday" is specific; "I'll get you sorted" is not.

## `out_of_band`

The promise names a real action, but one that would happen after the call is over. No recording of the call could show it happening or failing.

- someone from the clinic calling the caller back
- a support team following up, reaching out, or contacting the caller
- a message, note or request being passed to clinic staff
- a text message or email being sent or arriving
- anything scheduled for later, tomorrow, or shortly

The caller hangs up not knowing. So does the recording.

## `in_call`

The promise names an action whose success or failure would be visible during the call itself.

- transferring or connecting the caller to another party
- looking something up and giving the answer now
- reading back a detail, confirming a booking, quoting a price
- checking something and saying what was found

A transfer is always `in_call`, however it is worded. Either a different party comes on the line during this call or one does not, and the recording shows which.

## The line between `out_of_band` and `in_call`

Promises about a support team split on what is being promised. "I'll connect you to our support team" is a transfer and is `in_call`. "I'll make sure our support team follows up with you" is a callback and is `out_of_band`. The first is something the agent does now; the second is something someone else does later.

When a sentence carries both, classify by the action the agent commits itself to doing during this call.

## Output

Emit only JSON, no preamble, no code fences. Every promise appears exactly once, keyed by the `promise_id` you were given. `kind` must be exactly one of `vacuous`, `out_of_band`, `in_call`. `why` is one short sentence.

```
{
  "kinds": [
    {"promise_id": "promise-04", "kind": "in_call",
     "why": "A transfer to clinic support either connects during this call or does not."}
  ]
}
```
