import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.judge_checks import check


def test_capability_pair_is_found(judgments):
    print("\n--- the past-hours capability pair is reported mechanically")
    pairs = judgments["capability_pairs_exact"]
    found = [p for p in pairs if {p["affirmed"]["id"], p["denied"]["id"]} == {"cap-01", "cap-02"}]
    check(bool(found), "cap-01 against cap-02 on 'past hours lookup' is reported",
          f"cap-01/cap-02 pair missing from {len(pairs)} exact pair(s)")
    for pair in found:
        check(pair["affirmed"]["call_id"] and pair["denied"]["at"],
              f"pair carries both call ids and timestamps "
              f"({pair['affirmed']['call_id']} {pair['affirmed']['at']} vs {pair['denied']['at']})",
              "pair is missing a call id or timestamp")


def test_phone_recital_contradiction(judgments):
    print("\n--- reciting the number on file against saying it cannot be seen")
    recital_calls = set(judgments["phone_recitals"])
    for call in ("campaign/call-08", "campaign/call-09"):
        check(call in recital_calls, f"{call}: recital of the caller's number detected",
              f"{call}: no recital detected")
    findings = judgments["phone_findings"]
    denials = {f["denial"]["id"] for f in findings}
    check("cap-25" in denials,
          f"cap-25 is paired against {sum(len(f['recitals']) for f in findings)} recital(s)",
          f"cap-25 not among the paired denials {sorted(denials)}")
    for finding in findings:
        check(bool(finding.get("caveat")),
              f"{finding['denial']['id']}: the finding states what it cannot tell apart",
              f"{finding['denial']['id']}: mechanical finding carries no caveat")


def test_model_findings_are_quoted(judgments):
    print("\n--- model-proposed findings are labelled and quote a real utterance")
    for finding in judgments["proposed_findings"]:
        check(finding["detection"] == "model_proposed" and bool(finding["evidence"]),
              f"{finding['capability']['id']} vs {finding['evidence_call_id']} "
              f"at {finding['evidence_at']}: labelled and quoted",
              f"{finding.get('capability', {}).get('id')}: unlabelled or unquoted")
    for pair in judgments["capability_pairs_clustered"]:
        check(pair["detection"] == "model_clustered" and bool(pair.get("rationale")),
              f"{pair['affirmed']['id']}/{pair['denied']['id']}: clustered pair says why",
              f"{pair['affirmed']['id']}/{pair['denied']['id']}: clustered pair has no rationale")
