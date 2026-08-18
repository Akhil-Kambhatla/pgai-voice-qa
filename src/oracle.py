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


def check_fact(claim_text, call_id="live"):
    suspicions = store.load("suspicions", [])
    if _fixated_suspicion(claim_text, call_id, suspicions):
        return {"status": "already_confirmed", "instruction": "acknowledge and move on"}

    oracle = store.load("oracle", {})
    slot = _match_slot(claim_text, oracle)
    if not slot:
        return {"status": "unknown"}
    entry = oracle[slot]
    if not entry.get("value"):
        return {"status": "unknown"}

    status = compare_statements(claim_text, str(entry["value"]))
    return {
        "status": status,
        "rule": entry["value"],
        "stated_in": entry.get("stated_in"),
        "at": entry.get("at"),
    }
