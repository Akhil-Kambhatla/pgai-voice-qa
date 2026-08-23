import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _wrapped(text, indent="    ", width=76):
    words = (text or "").split()
    lines, current = [], indent
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            lines.append(current)
            current = indent
        current += word + " "
    if current.strip():
        lines.append(current)
    return "\n".join(line.rstrip() for line in lines)


def _answers_when_asked(scenario):
    persona_text = scenario.get("persona_block") or ""
    opening = scenario.get("opening_situation") or ""
    dates = re.findall(
        r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\b\d{1,2}(?:st|nd|rd|th)?\s+"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\b"
        r"|\b(?:january|february|march|april|may|june|july|august|september|october|november|december)"
        r"\s+\d{1,2}\b|\btomorrow\b|\bnext week\b|\bthis week\b",
        f"{persona_text} {opening}", re.IGNORECASE,
    )
    providers = re.findall(r"\bDr\.?\s+[A-Z][a-z]+|\b[A-Z][a-z]+ Hauser\b", f"{persona_text} {opening}")
    return sorted(set(d.lower() for d in dates)), sorted(set(providers))


def render(scenario):
    probe = scenario.get("primary_probe") or {}
    dates, providers = _answers_when_asked(scenario)
    axes = scenario.get("axes") or {}
    lines = [
        "=" * 78,
        f"SCENARIO  {scenario.get('scenario_id')}",
        "=" * 78,
        f"  identity   {scenario.get('identity')}",
        f"  intent     {axes.get('intent')}   axes: {', '.join(f'{k}={v}' for k, v in axes.items() if k != 'intent')}",
        "",
        "  persona",
        _wrapped(scenario.get("persona_block"), indent="    "),
        "",
        "  opening",
        _wrapped(scenario.get("opening_situation"), indent="    "),
        "",
        "  goal",
        _wrapped(scenario.get("goal"), indent="    "),
        "",
        f"  probe      {probe.get('name')}",
        _wrapped(probe.get("what_happens"), indent="    "),
        "  expected",
        _wrapped(probe.get("expected_correct_behavior"), indent="    "),
        "",
        f"  says when asked which date:     {', '.join(dates) if dates else 'NOTHING IN THE PERSONA'}",
        f"  says when asked which provider: {', '.join(providers) if providers else 'no preference stated'}",
        "",
        f"  facts_to_elicit   {scenario.get('facts_to_elicit')}",
        f"  follow-up         {scenario.get('opportunistic_follow_up')}",
        "=" * 78,
    ]
    return "\n".join(lines)
