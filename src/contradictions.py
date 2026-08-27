import re

AGENT_BLOCK_GAP_SECONDS = 8
PHONE_DENIAL_MARKERS = ("phone number", "number on file", "number is on file", "your number")
ENDING_IN = re.compile(r"ending(?:\s+in)?\s+(\d{4})")


def capability_pairs(capabilities):
    by_handle = {}
    for capability in capabilities:
        by_handle.setdefault(capability.get("ability"), []).append(capability)
    pairs = []
    for handle, entries in sorted(by_handle.items()):
        affirmed = [e for e in entries if e.get("can")]
        denied = [e for e in entries if not e.get("can")]
        for yes in affirmed:
            for no in denied:
                pairs.append({
                    "kind": "capability_pair",
                    "detection": "mechanical",
                    "ability": handle,
                    "affirmed": yes,
                    "denied": no,
                    "same_call": yes.get("call_id") == no.get("call_id"),
                })
    return pairs


def agent_blocks(lines):
    blocks = []
    for line in lines:
        if line["speaker"] != "AGENT":
            continue
        if blocks and line["at_seconds"] - blocks[-1]["end_seconds"] <= AGENT_BLOCK_GAP_SECONDS:
            blocks[-1]["text"] += " " + line["text"]
            blocks[-1]["end_seconds"] = line["at_seconds"]
        else:
            blocks.append({
                "at_seconds": line["at_seconds"],
                "end_seconds": line["at_seconds"],
                "text": line["text"],
            })
    return blocks


def caller_digits(record):
    digits = re.sub(r"\D", "", record.get("from") or "")
    return digits[-10:] if len(digits) >= 10 else digits


def phone_recitals(call_id, record, lines):
    digits = caller_digits(record)
    if len(digits) != 10:
        return []
    found = []
    for block in agent_blocks(lines):
        spoken = re.sub(r"\D", "", block["text"])
        ending = ENDING_IN.search(block["text"].lower())
        if digits in spoken:
            form = "full number"
        elif ending and ending.group(1) == digits[-4:]:
            form = "last four digits"
        else:
            continue
        found.append({
            "call_id": call_id,
            "at_seconds": block["at_seconds"],
            "form": form,
            "text": block["text"],
        })
    return found


def phone_denials(capabilities):
    denials = []
    for capability in capabilities:
        if capability.get("can"):
            continue
        haystack = f"{capability.get('ability') or ''} {capability.get('text') or ''}".lower()
        if any(marker in haystack for marker in PHONE_DENIAL_MARKERS):
            denials.append(capability)
    return denials


def phone_findings(capabilities, recitals_by_call):
    recitals = [r for found in recitals_by_call.values() for r in found]
    if not recitals:
        return []
    findings = []
    for denial in phone_denials(capabilities):
        findings.append({
            "kind": "statement_against_behaviour",
            "detection": "mechanical",
            "datum": "the caller's phone number",
            "denial": denial,
            "recitals": sorted(recitals, key=lambda r: (r["call_id"], r["at_seconds"])),
            "caveat": (
                "The detector matches the number the call was placed from. It cannot tell a number "
                "read off caller ID from a number read out of a stored record, and the denial is "
                "specifically about what is on file. Confirm against the recording before filing."
            ),
        })
    return findings
