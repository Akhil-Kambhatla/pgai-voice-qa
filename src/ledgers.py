from loguru import logger

from src import oracle, store

EMPTY_SLOT = {"value": None, "stated_in": None, "at": None, "times_stated": 0}
RECORD_CLAIM_MARKERS = ("profile", "account", "on file", "your record")


def identities_with_records():
    found = set()
    for claim in store.load("claims", []):
        haystack = f"{claim.get('action') or ''} {claim.get('text') or ''}".lower()
        if any(marker in haystack for marker in RECORD_CLAIM_MARKERS) and claim.get("identity"):
            found.add(claim["identity"])
    return found


def empty_oracle():
    return {slot: dict(EMPTY_SLOT) for slot in oracle.ORACLE_SLOTS}


def next_id(items, prefix):
    return f"{prefix}-{len(items) + 1:02d}"


def apply_facts(facts, call_id, oracle_data, suspicions, changes):
    skipped = []
    for fact in facts:
        slot, value, at = fact.get("slot"), fact.get("value"), fact.get("at")
        if slot not in oracle.ORACLE_SLOTS:
            logger.warning(f"{call_id}: dropped fact with unknown slot {slot!r}")
            skipped.append({"bucket": "facts", "reason": f"unknown slot {slot!r}", "item": fact})
            continue
        if not value:
            skipped.append({"bucket": "facts", "reason": "empty value", "item": fact})
            continue
        entry = oracle_data.setdefault(slot, dict(EMPTY_SLOT))
        if not entry["value"]:
            oracle_data[slot] = {
                "value": value, "stated_in": call_id, "at": at, "times_stated": 1,
            }
            changes.append(f"oracle: {slot} filled from {call_id} at {at}")
        elif oracle.compare_statements(value, str(entry["value"])) == "conflict":
            suspicion = {
                "id": next_id(suspicions, "susp"),
                "description": (
                    f"Contradiction on {slot}: said \"{entry['value']}\" in "
                    f"{entry['stated_in']} at {entry['at']}, but \"{value}\" in {call_id} at {at}"
                ),
                "axes_involved": {},
                "confidence": 0.6,
                "severity": "high",
                "seen_in": [entry["stated_in"], call_id],
                "status": "suspected",
            }
            suspicions.append(suspicion)
            changes.append(f"suspicion: {suspicion['id']} ({slot} contradiction)")
        elif oracle.is_more_specific(value, str(entry["value"])):
            entry.update({"value": value, "stated_in": call_id, "at": at})
            entry["times_stated"] += 1
            changes.append(f"oracle: {slot} sharpened from {call_id} at {at} to \"{value}\"")
        else:
            entry["times_stated"] += 1
            changes.append(f"oracle: {slot} restated consistently (times_stated={entry['times_stated']})")
    return skipped


def apply_claims(extracted, call_id, identity, claims, changes):
    for item in extracted:
        claim = {
            "id": next_id(claims, "claim"),
            "text": item.get("text"),
            "action": item.get("action"),
            "identity": identity,
            "call_id": call_id,
            "at": item.get("at"),
            "status": "unverified",
        }
        claims.append(claim)
        changes.append(f"claim: {claim['id']} unverified ({claim['action']})")


def apply_promises(extracted, call_id, identity, promises, changes):
    for item in extracted:
        promise = {
            "id": next_id(promises, "promise"),
            "text": item.get("text"),
            "action": item.get("action"),
            "identity": identity,
            "call_id": call_id,
            "at": item.get("at"),
        }
        promises.append(promise)
        changes.append(f"promise: {promise['id']} at {promise['at']} ({promise['action']})")


def apply_capabilities(extracted, call_id, capabilities, changes):
    for item in extracted:
        capability = {
            "id": next_id(capabilities, "cap"),
            "text": item.get("text"),
            "ability": item.get("ability"),
            "can": bool(item.get("can")),
            "call_id": call_id,
            "at": item.get("at"),
        }
        capabilities.append(capability)
        changes.append(
            f"capability: {capability['id']} {capability['ability']} can={capability['can']}"
        )


def apply_entities(entities, call_id, frontier, changes):
    skipped = []
    known = {e["name"].lower() for e in frontier}
    for entity in entities:
        name = (entity.get("name") or "").strip()
        if not name:
            skipped.append({"bucket": "entities", "reason": "no name", "item": entity})
            continue
        if name.lower() in known:
            skipped.append({"bucket": "entities", "reason": "already on the frontier", "item": entity})
            continue
        frontier.append(
            {"name": name, "kind": entity.get("kind", "other"), "mentioned_in": call_id, "probed": False}
        )
        known.add(name.lower())
        changes.append(f"frontier: {name} ({entity.get('kind')}) unprobed")
    return skipped
