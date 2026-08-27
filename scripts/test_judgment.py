import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import test_contradictions
from scripts.judge_checks import check, failures, load_judgments, normalise
from src import call_transcript, promise_gate, store

TRANSFER_CALLS = ("call-01", "call-05", "call-06", "call-08", "call-09")
TRANSFER_ACTION = re.compile(r"transfer|connect", re.IGNORECASE)


def test_transfer_promises_are_unfulfilled(judgments):
    print("\n--- the promised warm transfer never happened")
    for call in TRANSFER_CALLS:
        call_id = f"campaign/{call}"
        broken = [
            r for r in judgments["resolutions"]
            if r["call_id"] == call_id and r["outcome"] == "unfulfilled"
            and TRANSFER_ACTION.search(f"{r['action']} {r['text']}")
        ]
        names = ", ".join(f"{r['promise_id']} at {r['at']}" for r in broken)
        check(bool(broken), f"{call}: transfer unfulfilled ({names})",
              f"{call}: no transfer or connect promise resolved unfulfilled")


def test_unresolvable_carries_the_right_reason(judgments):
    print("\n--- unresolvable promises say why, and the why holds up")
    unresolvable = [r for r in judgments["resolutions"] if r["outcome"] == "unresolvable"]
    check(bool(unresolvable), f"{len(unresolvable)} promise(s) resolved unresolvable",
          "no promise resolved unresolvable")
    for resolution in unresolvable:
        reason = resolution["unresolvable_reason"]
        check(reason in promise_gate.UNRESOLVABLE_REASONS,
              f"{resolution['promise_id']}: reason {reason}",
              f"{resolution['promise_id']}: unusable reason {reason!r}")
        left, turns = resolution["seconds_after_promise"], resolution["remaining_agent_turns"]
        too_soon = turns == 0 or (left is not None and left < judgments["too_soon_seconds"])
        if reason == "call_ended_too_soon":
            check(too_soon,
                  f"{resolution['promise_id']}: {left}s and {turns} turns left, too soon holds",
                  f"{resolution['promise_id']}: called too soon with {left}s and {turns} turns left")
        if reason == "not_observable_on_call":
            check(resolution["kind"] == "out_of_band" and bool(resolution["kind_why"]),
                  f"{resolution['promise_id']}: out of band because {resolution['kind_why']}",
                  f"{resolution['promise_id']}: not_observable_on_call with no out-of-band reason")
        if reason in ("evidence_not_found", "reason_not_supported"):
            check(bool(resolution["gate_notes"]),
                  f"{resolution['promise_id']}: the gate says why it refused the model",
                  f"{resolution['promise_id']}: {reason} with no gate note")


def test_the_too_soon_gate_is_arithmetic():
    print("\n--- the too-soon rule is decided by the clock, not by the model")
    stub = {"promise": {"id": "promise-stub", "call_id": "campaign/call-01",
                        "at": "2:50", "action": "transfer call", "text": "Transferring you now."},
            "at_seconds": 170, "seconds_after_promise": 4,
            "remaining_agent_turns": 0, "remainder": []}
    gated = promise_gate.apply_gate(stub, {"outcome": "unresolvable", "unresolvable_reason": None})
    check(gated["unresolvable_reason"] == "call_ended_too_soon",
          "4s and no remaining turns is forced to call_ended_too_soon",
          f"too-soon gate did not fire: {gated['unresolvable_reason']!r}")

    invented = promise_gate.apply_gate(
        stub, {"outcome": "unfulfilled", "evidence": "not in the remainder"}
    )
    check(invented["outcome"] == "unresolvable" and invented["gate_notes"],
          "an outcome resting on a quote that is not there is refused",
          f"invented evidence survived the gate: {invented}")

    late = dict(stub, seconds_after_promise=90, remaining_agent_turns=6)
    refuted = promise_gate.apply_gate(
        late, {"outcome": "unresolvable", "unresolvable_reason": "call_ended_too_soon"}
    )
    check(refuted["unresolvable_reason"] == "reason_not_supported",
          "call_ended_too_soon with 90s and 6 turns left is refused",
          f"an unsupported too-soon claim survived: {refuted['unresolvable_reason']!r}")

    poached = promise_gate.apply_gate(late, {"outcome": "vacuous"})
    check(poached["outcome"] != "vacuous" and poached["gate_notes"],
          "the resolver cannot overrule the classifier by calling a promise vacuous",
          f"the resolver was allowed to return vacuous: {poached['outcome']!r}")


def test_vacuous_is_its_own_outcome(judgments):
    print("\n--- vacuous promises are not forced into fulfilled or unfulfilled")
    vacuous = [r for r in judgments["resolutions"] if r["outcome"] == "vacuous"]
    names = ", ".join(f"{r['promise_id']} \"{r['text']}\"" for r in vacuous)
    check(bool(vacuous), f"{len(vacuous)} vacuous: {names}", "no promise resolved vacuous")
    check(all(r["unresolvable_reason"] is None for r in vacuous),
          "no vacuous promise carries an unresolvable reason",
          "a vacuous promise carries an unresolvable reason")


def test_every_settled_promise_quotes_the_remainder(judgments):
    print("\n--- fulfilled and unfulfilled are backed by a quote from after the promise")
    for resolution in judgments["resolutions"]:
        if resolution["outcome"] not in ("fulfilled", "unfulfilled"):
            continue
        lines = call_transcript.read_transcript(store.resolve_call_dir(resolution["call_id"]))
        at_seconds = call_transcript.parse_timestamp(resolution["at"])
        remainder = normalise(
            call_transcript.render_lines([l for l in lines if l["at_seconds"] > at_seconds])
        )
        check(bool(resolution["evidence"]) and normalise(resolution["evidence"]) in remainder,
              f"{resolution['promise_id']}: evidence is verbatim in the remainder",
              f"{resolution['promise_id']}: evidence not found after {resolution['at']}: "
              f"{resolution['evidence']!r}")


def main():
    judgments = load_judgments()
    test_transfer_promises_are_unfulfilled(judgments)
    test_unresolvable_carries_the_right_reason(judgments)
    test_the_too_soon_gate_is_arithmetic()
    test_vacuous_is_its_own_outcome(judgments)
    test_every_settled_promise_quotes_the_remainder(judgments)
    test_contradictions.test_capability_pair_is_found(judgments)
    test_contradictions.test_phone_recital_contradiction(judgments)
    test_contradictions.test_model_findings_are_quoted(judgments)
    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)
    print("\nall judgment checks passed")


if __name__ == "__main__":
    main()
