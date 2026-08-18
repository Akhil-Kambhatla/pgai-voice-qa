import json
import sys
import urllib.request

SERVER = "http://localhost:7860"


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: place_call.py <scenario_id> <phone_number, e.g. +17325550123>")
    scenario_id, phone_number = sys.argv[1], sys.argv[2]

    req = urllib.request.Request(
        f"{SERVER}/start",
        data=json.dumps({"scenario_id": scenario_id, "phone_number": phone_number}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    main()
