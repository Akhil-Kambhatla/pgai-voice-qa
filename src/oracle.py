import re
from collections import defaultdict

from src import store

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
SLOT_KEYWORDS = {
    "hours": ["hours", "open", "opens", "close", "closes", "closed", "until"],
    "closed_days": ["closed", "weekend", "weekends", "days off"],
    "locations": ["location", "locations", "office", "address", "branch", "downtown"],
    "providers": ["doctor", "dr", "provider", "physician", "specialist", "surgeon", "pa"],
    "services": ["service", "services", "imaging", "x-ray", "mri", "physical therapy", "surgery"],
    "insurers": ["insurance", "insurer", "plan", "coverage", "accept", "network"],
    "refill_policy": ["refill", "prescription", "medication", "pharmacy"],
    "cancel_window": ["cancel", "cancellation", "notice", "fee", "no-show"],
    "appointment_length": ["long", "minutes", "duration", "appointment length"],
    "holiday_schedule": ["holiday", "holidays", "labor day", "memorial day", "thanksgiving", "christmas"],
}

_probe_counts = defaultdict(int)
_topics_checked = defaultdict(set)
_claims_checked = defaultdict(list)


def _tokens(text):
    return set(re.findall(r"[a-z0-9':-]+", text.lower()))


def _category_tokens(text):
    lowered = text.lower()
    return {
        "weekday": {d for d in WEEKDAYS if d in lowered},
        "month": {m for m in MONTHS if m in lowered},
        "time": set(re.findall(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)\b", lowered)),
        "number": set(re.findall(r"\b\d+\b", lowered)),
    }


def _match_slot(claim_text, oracle):
    claim_tokens = _tokens(claim_text)
    best, best_hits = None, 0
    for slot, keywords in SLOT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in claim_text.lower())
        value = oracle.get(slot, {}).get("value")
        if value:
            hits += len(claim_tokens & _tokens(str(value))) * 0.1
        if hits > best_hits:
            best, best_hits = slot, hits
    return best if best_hits >= 1 else None


def compare_statements(claim_text, value_text):
    claim_cats = _category_tokens(claim_text)
    value_cats = _category_tokens(value_text)
    for category in ("weekday", "month", "time"):
        claim_set, value_set = claim_cats[category], value_cats[category]
        if claim_set and value_set and not (claim_set & value_set):
            return "conflict"
    return "consistent"


def _fixated_suspicion(claim_text, call_id, suspicions):
    claim_tokens = _tokens(claim_text)
    for suspicion in suspicions:
        overlap = claim_tokens & _tokens(suspicion.get("description", ""))
        if len(overlap) < 3:
            continue
        if suspicion.get("status") == "confirmed":
            return suspicion
        key = (call_id, suspicion.get("id"))
        _probe_counts[key] += 1
        if _probe_counts[key] > 2:
            return suspicion
    return None


def _is_compound(claim_text):
    return ";" in claim_text or len(re.findall(r"\band\b", claim_text.lower())) > 1


def topics_checked(call_id):
    return set(_topics_checked[call_id])


def claim_addressed(call_id, target_text):
    target_tokens = _tokens(target_text)
    return any(len(target_tokens & _tokens(c)) >= 3 for c in _claims_checked[call_id])


def check_fact(claim_text, call_id="live"):
    if _is_compound(claim_text):
        return {"status": "invalid", "instruction": "ask about one fact at a time"}

    oracle_data = store.load("oracle", {})
    topic = _match_slot(claim_text, oracle_data)
    if topic and topic in _topics_checked[call_id]:
        return {"status": "already_asked", "instruction": "you already asked this. do not ask again."}
    if topic:
        _topics_checked[call_id].add(topic)
    _claims_checked[call_id].append(claim_text)

    suspicions = store.load("suspicions", [])
    if _fixated_suspicion(claim_text, call_id, suspicions):
        return {"status": "already_confirmed", "instruction": "acknowledge and move on"}

    if not topic:
        return {"status": "unknown"}
    entry = oracle_data[topic]
    if not entry.get("value"):
        return {"status": "unknown"}

    status = compare_statements(claim_text, str(entry["value"]))
    return {
        "status": status,
        "rule": entry["value"],
        "stated_in": entry.get("stated_in"),
        "at": entry.get("at"),
    }
