import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner import plan_next_call


def main():
    scenario = plan_next_call()
    print(f"scenario_id: {scenario['scenario_id']}")
    print(f"call_index:  {scenario['call_index']} (axis score {scenario['axis_score']})")
    print(f"identity:    {scenario['identity']}")
    print("axes:")
    for axis, value in scenario["axes"].items():
        print(f"  {axis}: {value}")
    print(f"\npersona:\n{scenario.get('persona_block')}")
    print(f"\nopening line: {scenario.get('opening_line')}")
    print(f"goal: {scenario.get('goal')}")
    probe = scenario.get("primary_probe") or {}
    print(f"\nprimary probe: {probe.get('name')}")
    print(f"  what happens: {probe.get('what_happens')}")
    print(f"  expected:     {probe.get('expected_correct_behavior')}")
    print(f"\nopportunistic follow-up: {scenario.get('opportunistic_follow_up')}")
    print(f"facts to elicit: {json.dumps(scenario.get('facts_to_elicit'))}")
    print(f"claims to verify: {json.dumps(scenario.get('claims_to_verify'))}")
    print(f"caller id cover: {scenario.get('caller_id_cover')}")
    print(f"\nto dial: uv run python scripts/place_call.py {scenario['scenario_id']} <number>")


if __name__ == "__main__":
    main()
