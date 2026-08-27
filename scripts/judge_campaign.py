import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import judge_render
from src import call_transcript, config, contradiction_review, contradictions, promise_gate, resolver, store

CALL_DIR_NAME = re.compile(r"call-\d+")


def campaign_call_ids():
    calls_dir = config.CALL_TREES["campaign"][0]
    return [
        f"campaign/{name}"
        for name in sorted(os.listdir(calls_dir))
        if CALL_DIR_NAME.fullmatch(name)
        and os.path.exists(os.path.join(calls_dir, name, "call.json"))
    ]


def resolve_promises(call_ids, promises):
    by_call = collections.defaultdict(list)
    for promise in promises:
        by_call[promise["call_id"]].append(promise)
    resolutions, endings = [], {}
    for call_id in call_ids:
        found, ending = resolver.resolve_call(call_id, by_call.get(call_id, []))
        endings[call_id] = ending
        resolutions.extend(found)
    return resolutions, endings


def collect_recitals(call_ids):
    recitals = {}
    for call_id in call_ids:
        call_dir = store.resolve_call_dir(call_id)
        with open(os.path.join(call_dir, "call.json")) as handle:
            record = json.load(handle)
        found = contradictions.phone_recitals(
            call_id, record, call_transcript.read_transcript(call_dir)
        )
        if found:
            recitals[call_id] = found
    return recitals


def detect_contradictions(call_ids, capabilities):
    exact = contradictions.capability_pairs(capabilities)
    recitals = collect_recitals(call_ids)
    phone = contradictions.phone_findings(capabilities, recitals)
    clustered, proposed = contradiction_review.review(capabilities, call_ids)
    return exact, phone, clustered, proposed, recitals


def main():
    call_ids = campaign_call_ids()
    promises = store.load("promises", [])
    capabilities = store.load("capabilities", [])
    print(
        f"judging {len(call_ids)} calls, {len(promises)} promises, "
        f"{len(capabilities)} capability statements"
    )

    resolutions, endings = resolve_promises(call_ids, promises)
    exact, phone, clustered, proposed, recitals = detect_contradictions(call_ids, capabilities)

    judge_render.promises(resolutions, endings)
    judge_render.contradictions(exact, phone, clustered, proposed, recitals)

    judgments = {
        "call_ids": call_ids,
        "model": config.PLANNER_MODEL,
        "too_soon_seconds": promise_gate.TOO_SOON_SECONDS,
        "endings": endings,
        "resolutions": resolutions,
        "capability_pairs_exact": exact,
        "capability_pairs_clustered": clustered,
        "phone_recitals": recitals,
        "phone_findings": phone,
        "proposed_findings": proposed,
    }
    path = os.path.join(config.CALL_TREES["campaign"][1], "judgments.json")
    with open(path, "w") as handle:
        json.dump(judgments, handle, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
