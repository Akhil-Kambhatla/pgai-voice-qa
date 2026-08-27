import re

from src.call_transcript import render_lines

TOO_SOON_SECONDS = 15
OUTCOMES = ("fulfilled", "unfulfilled", "unresolvable", "vacuous")
UNRESOLVABLE_REASONS = (
    "call_ended_too_soon", "not_observable_on_call", "evidence_not_found", "reason_not_supported",
)


def normalise(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def ends_too_soon(context):
    seconds_left = context["seconds_after_promise"]
    return context["remaining_agent_turns"] == 0 or (
        seconds_left is not None and seconds_left < TOO_SOON_SECONDS
    )


def settled(context, outcome, reason, kind, notes):
    return {
        "promise_id": context["promise"]["id"],
        "call_id": context["promise"]["call_id"],
        "at": context["promise"].get("at"),
        "action": context["promise"].get("action"),
        "text": context["promise"].get("text"),
        "outcome": outcome,
        "unresolvable_reason": reason,
        "evidence": "",
        "rationale": kind.get("why"),
        "kind": kind.get("kind"),
        "kind_why": kind.get("why"),
        "seconds_after_promise": context["seconds_after_promise"],
        "remaining_agent_turns": context["remaining_agent_turns"],
        "gate_notes": notes,
    }


def apply_gate(context, verdict, kind=None):
    kind = kind or {"kind": "in_call", "why": None, "note": None}
    outcome = verdict.get("outcome")
    reason = verdict.get("unresolvable_reason")
    evidence = (verdict.get("evidence") or "").strip()
    too_soon = ends_too_soon(context)
    notes = [kind["note"]] if kind.get("note") else []
    rejected = None
    if outcome == "vacuous" or reason == "not_observable_on_call":
        notes.append(
            f"resolver returned {outcome}/{reason}, which is the classifier's call, not its own"
        )
        outcome, reason = None, None
    if outcome not in OUTCOMES:
        notes.append(f"model returned an unusable outcome {outcome!r}")
        outcome, rejected = "unresolvable", "evidence_not_found"
    if outcome in ("fulfilled", "unfulfilled"):
        remainder = normalise(render_lines(context["remainder"]))
        if not evidence or normalise(evidence) not in remainder:
            notes.append(f"evidence quote is not verbatim in the remainder: {evidence!r}")
            outcome, rejected = "unresolvable", "evidence_not_found"
    if outcome != "unresolvable":
        reason = None
    elif too_soon:
        reason = "call_ended_too_soon"
    elif rejected:
        reason = rejected
    else:
        notes.append(
            f"model reason {reason!r} is refuted by {context['seconds_after_promise']}s and "
            f"{context['remaining_agent_turns']} agent turn(s) of call left after the promise"
        )
        reason = "reason_not_supported"
    resolved = settled(context, outcome, reason, kind, notes)
    resolved["evidence"] = evidence
    resolved["rationale"] = verdict.get("rationale")
    return resolved
