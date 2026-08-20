import json
import os

from src import config


SHARED_STATE = ("identities", "axes")


def _path(name):
    root = config.DATA_DIR if name in SHARED_STATE else config.STATE_DIR
    return os.path.join(root, f"{name}.json")


def resolve_call_dir(call_id):
    if "/" in call_id:
        tree, _, bare_id = call_id.partition("/")
        if tree not in config.CALL_TREES:
            raise SystemExit(
                f"Unknown call tree '{tree}'; expected one of {', '.join(config.CALL_TREES)}"
            )
        path = os.path.join(config.CALL_TREES[tree][0], bare_id)
        if not os.path.isdir(path):
            raise SystemExit(f"No call directory at {path}")
        return path
    found = {
        tree: os.path.join(calls_dir, call_id)
        for tree, (calls_dir, _) in config.CALL_TREES.items()
        if os.path.isdir(os.path.join(calls_dir, call_id))
    }
    if not found:
        trees = ", ".join(config.CALL_TREES)
        raise SystemExit(f"No call directory named {call_id} in any call tree ({trees})")
    if len(found) > 1:
        qualified = ", ".join(f"{tree}/{call_id}" for tree in sorted(found))
        raise SystemExit(
            f"Call id {call_id} exists in more than one call tree; name one of: {qualified}"
        )
    return next(iter(found.values()))


def load(name, default):
    path = _path(name)
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(name, obj):
    path = _path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def load_scenario(scenario_id):
    with open(os.path.join(config.SCENARIOS_DIR, f"{scenario_id}.json")) as f:
        return json.load(f)


def save_scenario(scenario):
    os.makedirs(config.SCENARIOS_DIR, exist_ok=True)
    path = os.path.join(config.SCENARIOS_DIR, f"{scenario['scenario_id']}.json")
    with open(path, "w") as f:
        json.dump(scenario, f, indent=2)
    return path


def load_prompt(name):
    with open(os.path.join(config.PROMPTS_DIR, f"{name}.md")) as f:
        return f.read()


def list_call_records():
    records = []
    if not os.path.isdir(config.CALLS_DIR):
        return records
    for call_id in sorted(os.listdir(config.CALLS_DIR)):
        path = os.path.join(config.CALLS_DIR, call_id, "call.json")
        if os.path.exists(path):
            with open(path) as f:
                records.append(json.load(f))
    return records
