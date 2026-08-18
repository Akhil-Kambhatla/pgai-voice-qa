import itertools
import math
import random

TOTAL_CALLS = 20
CANDIDATES = 200
SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
DISCOVERY_FORCED = {
    "identity": "akhil",
    "cooperation": "full",
    "register": "neutral",
    "curveball": "none",
}


def usage_counts(history, axes):
    counts = {axis: {value: 0 for value in values} for axis, values in axes.items()}
    for call in history:
        for axis, value in (call.get("axes") or {}).items():
            if axis in counts and value in counts[axis]:
                counts[axis][value] += 1
    return counts


def covered_pairs(history):
    pairs = set()
    for call in history:
        call_axes = call.get("axes") or {}
        for (a1, v1), (a2, v2) in itertools.combinations(sorted(call_axes.items()), 2):
            pairs.add((a1, v1, a2, v2))
    return pairs


def uncovered_pair_fraction(candidate, prior_pairs):
    pairs = list(itertools.combinations(sorted(candidate.items()), 2))
    uncovered = sum(
        1 for (a1, v1), (a2, v2) in pairs if (a1, v1, a2, v2) not in prior_pairs
    )
    return uncovered / len(pairs)


def novelty(candidate, counts):
    total = sum(
        1.0 / math.sqrt(1 + counts[axis][value]) for axis, value in candidate.items()
    )
    return total / len(candidate)


def relevance(candidate, suspicion):
    involved = suspicion.get("axes_involved") or {}
    if isinstance(involved, list):
        involved = dict(pair.split(":", 1) for pair in involved if ":" in pair)
    if not involved:
        return 0.0
    matched = sum(1 for axis, value in involved.items() if candidate.get(axis) == value)
    return matched / len(involved)


def lead_score(candidate, suspicions):
    total = 0.0
    for suspicion in suspicions:
        if suspicion.get("status") not in ("suspected", "confirming"):
            continue
        weight = SEVERITY_WEIGHT.get(suspicion.get("severity"), 0.25)
        confidence = float(suspicion.get("confidence") or 0.0)
        total += relevance(candidate, suspicion) * (1 - confidence) * weight
    return min(max(total, 0.0), 1.0)


def is_valid(candidate, call_index, unverified_claims):
    if candidate["continuity"] == "verifies_claim" and not unverified_claims:
        return False
    if candidate["continuity"] == "references_prior" and call_index <= 2:
        return False
    if call_index <= 2:
        for axis, value in DISCOVERY_FORCED.items():
            if candidate[axis] != value:
                return False
    return True


def score(candidate, counts, prior_pairs, suspicions, call_index, total_calls):
    w = call_index / total_calls
    explore = (novelty(candidate, counts) + uncovered_pair_fraction(candidate, prior_pairs)) / 2
    return (1 - w) * explore + w * lead_score(candidate, suspicions)


def select_scenario_axes(axes, history, suspicions, unverified_claims, call_index,
                         total_calls=TOTAL_CALLS, seed=None):
    rng = random.Random(seed)
    counts = usage_counts(history, axes)
    prior_pairs = covered_pairs(history)
    best, best_score = None, -1.0
    for _ in range(CANDIDATES):
        candidate = {axis: rng.choice(values) for axis, values in axes.items()}
        if call_index <= 2:
            candidate.update(DISCOVERY_FORCED)
        if not is_valid(candidate, call_index, unverified_claims):
            continue
        s = score(candidate, counts, prior_pairs, suspicions, call_index, total_calls)
        if s > best_score:
            best, best_score = candidate, s
    if best is None:
        best = dict(DISCOVERY_FORCED)
        for axis, values in axes.items():
            best.setdefault(axis, values[0])
        best["continuity"] = "fresh"
    return best, best_score
