import json
import re
from datetime import datetime

from loguru import logger
from openai import OpenAI

from src import config, oracle, scoring, store


def gather_state():
    history = store.list_call_records()
    claims = store.load("claims", [])
    suspicions = store.load("suspicions", [])
    unverified_claims = [c for c in claims if c.get("status") == "unverified"]
    open_suspicions = [
        s for s in suspicions if s.get("status") in ("suspected", "confirming")
    ]
    return history, unverified_claims, open_suspicions


def plan_next_call():
    axes_space = store.load("axes", {})
    history, unverified_claims, open_suspicions = gather_state()
    call_index = len(history) + 1

    chosen_axes, axis_score = scoring.select_scenario_axes(
        axes_space, history, open_suspicions, unverified_claims, call_index
    )

    identities = store.load("identities", {})
    now = datetime.now()
    user_content = json.dumps(
        {
            "axes": chosen_axes,
            "identity": identities.get(chosen_axes["identity"]),
            "oracle": store.load("oracle", {}),
            "frontier": [e for e in store.load("frontier", []) if not e.get("probed")],
            "open_suspicions": open_suspicions,
            "claims": unverified_claims,
            "call_index": call_index,
            "total_calls": scoring.TOTAL_CALLS,
            "today": {"date": now.strftime("%Y-%m-%d"), "weekday": now.strftime("%A")},
        },
        indent=2,
    )

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.PLANNER_MODEL,
        messages=[
            {"role": "system", "content": store.load_prompt("planner")},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    scenario = json.loads(response.choices[0].message.content)

    slug = re.sub(r"[^a-z0-9-]", "", scenario.get("scenario_id", "scenario").lower())
    scenario["scenario_id"] = f"{call_index:02d}-{slug}"
    scenario["axes"] = chosen_axes
    scenario["identity"] = chosen_axes["identity"]
    scenario["call_index"] = call_index
    scenario["axis_score"] = round(axis_score, 4)
    scenario["facts_to_elicit"] = _valid_slots_only(scenario)
    store.save_scenario(scenario)
    return scenario


def _valid_slots_only(scenario):
    requested = scenario.get("facts_to_elicit") or []
    dropped = [slot for slot in requested if slot not in oracle.ORACLE_SLOTS]
    if dropped:
        logger.warning(
            f"{scenario['scenario_id']}: dropped facts_to_elicit entries that are not oracle "
            f"slot names: {dropped}"
        )
    return [slot for slot in requested if slot in oracle.ORACLE_SLOTS]
