import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

failures = []


def check(condition, passed, failed):
    if condition:
        print(f"  PASS {passed}")
    else:
        failures.append(failed)
        print(f"  FAIL {failed}")


def normalise(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def load_judgments():
    path = os.path.join(config.CALL_TREES["campaign"][1], "judgments.json")
    if not os.path.exists(path):
        sys.exit(f"No judgments at {path}; run scripts/judge_campaign.py first")
    with open(path) as handle:
        return json.load(handle)
