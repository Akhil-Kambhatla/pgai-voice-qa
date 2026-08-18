import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

MODEL_VISIBLE_TOOL_TEXT = ("conversation.item.create", "conversation.item.added")


def main():
    call_id = sys.argv[1]
    path = os.path.join(config.CALLS_DIR, call_id, "events.jsonl")
    events = [json.loads(line) for line in open(path) if line.strip()]

    updates = [e for e in events if e["source"] == "client" and e["type"] == "session.update"]
    print(f"=== {call_id}: {len(updates)} session.update events sent on the wire ===")
    for i, e in enumerate(updates):
        session = e["event"]["session"]
        print(f"\n--- session.update #{i + 1} at t={e['t']:.2f} keys={sorted(session)} ---")
        instructions = session.get("instructions") or ""
        print(f"instructions length: {len(instructions)}")
        if instructions:
            print(f"FIRST 400:\n{instructions[:400]}")
            print(f"LAST 400:\n{instructions[-400:]}")
        for tool in session.get("tools") or []:
            print(f"TOOL {tool.get('name')}: {tool.get('description')!r}")
            print(f"     params: {json.dumps(tool.get('parameters'))}")
        if not session.get("tools"):
            print("TOOLS: none present in this payload")

    print("\n=== model-visible text injected by our code ===")
    for e in events:
        if e["source"] != "client" or e["type"] not in MODEL_VISIBLE_TOOL_TEXT:
            continue
        item = e["event"].get("item") or {}
        body = item.get("output") or item.get("content")
        print(f"  t={e['t']:.2f} type={item.get('type')} role={item.get('role')} {str(body)[:220]}")


main()
