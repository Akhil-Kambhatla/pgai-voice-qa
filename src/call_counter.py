import json
import os
from datetime import datetime, timezone

from src import config, store


def _counter_at(state_dir):
    path = os.path.join(state_dir, "call_counter.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def placed_on(day):
    return sum(_counter_at(state_dir).get(day, 0) for _, state_dir in config.CALL_TREES.values())


def reserve_call_slot():
    counter = store.load("call_counter", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    placed_today = placed_on(today)
    if placed_today >= config.MAX_CALLS_PER_RUN:
        raise RuntimeError(
            f"Daily call cap MAX_CALLS_PER_RUN ({config.MAX_CALLS_PER_RUN}) reached for {today} "
            f"across all call trees; refusing to place another call"
        )
    counter[today] = counter.get(today, 0) + 1
    store.save("call_counter", counter)
    total = sum(counter.values())
    return f"call-{total:02d}"


def calls_placed_total():
    counter = store.load("call_counter", {})
    return sum(counter.values())
