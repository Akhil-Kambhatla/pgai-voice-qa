import json
import os

from openai import OpenAI

from src import config, promise_kind, store
from src.call_transcript import call_ending, parse_timestamp, read_transcript, render_lines
from src.promise_gate import apply_gate, settled


def promise_contexts(promises, lines, duration_seconds):
    contexts = []
    for promise in promises:
        at_seconds = parse_timestamp(promise.get("at"))
        after = [line for line in lines if line["at_seconds"] > at_seconds]
        contexts.append({
            "promise": promise,
            "at_seconds": at_seconds,
            "seconds_after_promise": None if duration_seconds is None else duration_seconds - at_seconds,
            "remaining_agent_turns": sum(1 for line in after if line["speaker"] == "AGENT"),
            "remainder": after,
        })
    return contexts


def _ask_model(lines, contexts, ending):
    described = [
        {
            "promise_id": context["promise"]["id"],
            "at": context["promise"].get("at"),
            "action": context["promise"].get("action"),
            "text": context["promise"].get("text"),
            "seconds_after_promise": context["seconds_after_promise"],
            "remaining_agent_turns": context["remaining_agent_turns"],
            "remainder": render_lines(context["remainder"]),
        }
        for context in contexts
    ]
    user_content = (
        f"Full transcript:\n{render_lines(lines)}\n\n"
        f"How the call ended: {json.dumps(ending)}\n\n"
        f"Promises to resolve:\n{json.dumps(described, indent=2)}"
    )
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.PLANNER_MODEL,
        messages=[
            {"role": "system", "content": store.load_prompt("resolver")},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    returned = json.loads(response.choices[0].message.content).get("resolutions") or []
    return {item.get("promise_id"): item for item in returned}


def resolve_call(call_id, promises, ask=_ask_model, classify=promise_kind.classify):
    call_dir = store.resolve_call_dir(call_id)
    with open(os.path.join(call_dir, "call.json")) as handle:
        record = json.load(handle)
    lines = read_transcript(call_dir)
    ending = call_ending(record, call_dir)
    contexts = promise_contexts(promises, lines, ending["duration_seconds"])
    if not contexts:
        return [], ending
    kinds = classify(promises)
    in_call = [c for c in contexts if kinds[c["promise"]["id"]]["kind"] == "in_call"]
    verdicts = ask(lines, in_call, ending) if in_call else {}
    resolutions = []
    for context in contexts:
        kind = kinds[context["promise"]["id"]]
        notes = [kind["note"]] if kind.get("note") else []
        if kind["kind"] == "vacuous":
            resolutions.append(settled(context, "vacuous", None, kind, notes))
        elif kind["kind"] == "out_of_band":
            resolutions.append(
                settled(context, "unresolvable", "not_observable_on_call", kind, notes)
            )
        else:
            resolutions.append(
                apply_gate(context, verdicts.get(context["promise"]["id"], {}), kind)
            )
    return resolutions, ending
