import collections

BANNER = "=" * 78


def _wrap(text, indent, width=76):
    words = (text or "").split()
    lines, current = [], indent
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            lines.append(current.rstrip())
            current = indent
        current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines


def _label(resolution):
    outcome = resolution["outcome"].upper()
    if resolution["unresolvable_reason"]:
        return f"{outcome} ({resolution['unresolvable_reason']})"
    return outcome


def promises(resolutions, endings):
    print(f"\n{BANNER}\nPART 1  PROMISE RESOLUTION\n{BANNER}")
    by_call = collections.defaultdict(list)
    for resolution in resolutions:
        by_call[resolution["call_id"]].append(resolution)
    for call_id in sorted(endings):
        ending = endings[call_id]
        found = sorted(by_call.get(call_id, []), key=lambda r: r["at"])
        header = (
            f"\n{call_id}  duration {ending['duration_seconds']}s  "
            f"hangup {ending['hangup_source']}/{ending['hangup_cause']}  "
            f"{len(found)} promise(s)"
        )
        print(header)
        if ending["exit_events"]:
            print(f"  lifecycle: {', '.join(ending['exit_events'])}")
        for resolution in found:
            print(f"  {resolution['promise_id']}  at {resolution['at']}  {_label(resolution)}")
            print(f"      action: {resolution['action']}   kind: {resolution['kind']}")
            for line in _wrap(f"said: \"{resolution['text']}\"", "      "):
                print(line)
            print(
                f"      {resolution['seconds_after_promise']}s of call left after it, "
                f"{resolution['remaining_agent_turns']} agent turn(s) remaining"
            )
            if resolution["evidence"]:
                for line in _wrap(f"evidence: {resolution['evidence']}", "      "):
                    print(line)
            for line in _wrap(f"why: {resolution['rationale']}", "      "):
                print(line)
            for note in resolution["gate_notes"]:
                for line in _wrap(f"gate: {note}", "      "):
                    print(line)
    tally = collections.Counter(_label(r) for r in resolutions)
    print(f"\n  tally over {len(resolutions)} promises")
    for label, count in sorted(tally.items()):
        print(f"    {count:>3}  {label}")


def _capability_line(capability):
    return (
        f"{capability['id']}  {capability['call_id']} at {capability['at']}  "
        f"can={capability['can']}  ability={capability['ability']!r}"
    )


def capability_pairs(pairs, heading):
    print(f"\n-- {heading}: {len(pairs)} pair(s)")
    for pair in pairs:
        scope = "same call" if pair["same_call"] else "across calls"
        print(f"\n  power: {pair['ability']!r}  ({scope})")
        print(f"    AFFIRMED  {_capability_line(pair['affirmed'])}")
        for line in _wrap(f"\"{pair['affirmed']['text']}\"", "        "):
            print(line)
        print(f"    DENIED    {_capability_line(pair['denied'])}")
        for line in _wrap(f"\"{pair['denied']['text']}\"", "        "):
            print(line)
        if pair.get("rationale"):
            for line in _wrap(f"why the model grouped them: {pair['rationale']}", "    "):
                print(line)


def phone_findings(findings, recitals):
    total = sum(len(found) for found in recitals.values())
    print(f"\n-- statement against behaviour, mechanical: {len(findings)} finding(s) "
          f"from {total} recital(s) of the caller's number")
    for call_id in sorted(recitals):
        for recital in recitals[call_id]:
            minutes, seconds = divmod(recital["at_seconds"], 60)
            print(f"    recital  {call_id} at {minutes}:{seconds:02d}  ({recital['form']})")
            for line in _wrap(f"\"{recital['text']}\"", "        "):
                print(line)
    for finding in findings:
        print(f"\n  DENIED    {_capability_line(finding['denial'])}")
        for line in _wrap(f"\"{finding['denial']['text']}\"", "        "):
            print(line)
        print(f"    contradicted by the {len(finding['recitals'])} recital(s) above")
        for line in _wrap(f"caveat: {finding['caveat']}", "    "):
            print(line)


def proposed_findings(findings):
    print(f"\n-- statement against behaviour, model proposed: {len(findings)} candidate(s)")
    print("   Each quote below was checked to appear verbatim in the named call. Whether it")
    print("   contradicts the statement is the model's opinion and wants your eye.")
    for finding in findings:
        print(f"\n  DENIED    {_capability_line(finding['capability'])}")
        for line in _wrap(f"\"{finding['capability']['text']}\"", "        "):
            print(line)
        print(f"    BEHAVIOUR {finding['evidence_call_id']} at {finding['evidence_at']}")
        for line in _wrap(f"\"{finding['evidence']}\"", "        "):
            print(line)
        for line in _wrap(f"why: {finding['rationale']}", "    "):
            print(line)


def contradictions(exact, phone, clustered, proposed, recitals):
    print(f"\n{BANNER}\nPART 2  CONTRADICTION DETECTION\n{BANNER}")
    capability_pairs(exact, "capability pairs, exact ability handle, mechanical")
    capability_pairs(clustered, "capability pairs, model clustered handles")
    phone_findings(phone, recitals)
    proposed_findings(proposed)
