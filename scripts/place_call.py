"""Place an outbound call via the local server. Usage: place_call.py +1XXXXXXXXXX"""

import json
import sys
import urllib.request

# The local machine cannot reach the ngrok URL over TLS, so always hit localhost.
SERVER = "http://localhost:7860"


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: place_call.py <phone_number, e.g. +17325550123>")
    phone_number = sys.argv[1]

    req = urllib.request.Request(
        f"{SERVER}/start",
        data=json.dumps({"phone_number": phone_number}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    main()
