import json
import re

from openai import OpenAI

from src import call_transcript, config, contradictions, store


def _normalise(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def agent_index(call_ids):
    index = {}
    for call_id in call_ids:
        call_dir = store.resolve_call_dir(call_id)
        lines = call_transcript.read_transcript(call_dir)
        index[call_id] = [
            {"at": call_transcript.clock(block["at_seconds"]), "text": block["text"]}
            for block in contradictions.agent_blocks(lines)
        ]
    return index


def _ask_model(capabilities, index):
    described = [
        {
            "id": c["id"], "call_id": c["call_id"], "at": c.get("at"),
            "ability": c.get("ability"), "can": c.get("can"), "text": c.get("text"),
        }
        for c in capabilities
    ]
    user_content = (
        f"Capability ledger:\n{json.dumps(described, indent=2)}\n\n"
        f"Everything the agent said, by call:\n{json.dumps(index, indent=2)}"
    )
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.PLANNER_MODEL,
        messages=[
            {"role": "system", "content": store.load_prompt("contradiction_review")},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _capability_by_id(capabilities):
    return {c["id"]: c for c in capabilities}


def _check_synonym_pairs(returned, by_id, exact_handles):
    findings = []
    for item in returned.get("synonym_pairs") or []:
        affirmed = by_id.get(item.get("affirmed_id"))
        denied = by_id.get(item.get("denied_id"))
        if not affirmed or not denied:
            continue
        if not affirmed.get("can") or denied.get("can"):
            continue
        if affirmed.get("ability") == denied.get("ability"):
            continue
        if (affirmed.get("ability"), denied.get("ability")) in exact_handles:
            continue
        findings.append({
            "kind": "capability_pair",
            "detection": "model_clustered",
            "ability": item.get("shared_power"),
            "affirmed": affirmed,
            "denied": denied,
            "same_call": affirmed.get("call_id") == denied.get("call_id"),
            "rationale": item.get("rationale"),
        })
    return findings


def _check_behaviour_pairs(returned, by_id, index):
    findings = []
    for item in returned.get("statement_against_behaviour") or []:
        capability = by_id.get(item.get("capability_id"))
        quote = (item.get("evidence") or "").strip()
        call_id = item.get("evidence_call_id")
        spoken = " ".join(block["text"] for block in index.get(call_id, []))
        if not capability or not quote or _normalise(quote) not in _normalise(spoken):
            continue
        findings.append({
            "kind": "statement_against_behaviour",
            "detection": "model_proposed",
            "capability": capability,
            "evidence_call_id": call_id,
            "evidence_at": item.get("evidence_at"),
            "evidence": quote,
            "rationale": item.get("rationale"),
        })
    return findings


def review(capabilities, call_ids, ask=_ask_model):
    index = agent_index(call_ids)
    returned = ask(capabilities, index)
    by_id = _capability_by_id(capabilities)
    exact_handles = {
        (pair["affirmed"].get("ability"), pair["denied"].get("ability"))
        for pair in contradictions.capability_pairs(capabilities)
    }
    return (
        _check_synonym_pairs(returned, by_id, exact_handles),
        _check_behaviour_pairs(returned, by_id, index),
    )
