import json
import os

from src import config


def _path(name):
    return os.path.join(config.DATA_DIR, f"{name}.json")


def load(name, default):
    path = _path(name)
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(name, obj):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_path(name), "w") as f:
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
