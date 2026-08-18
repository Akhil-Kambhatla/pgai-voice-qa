from datetime import datetime, timezone

from src import config, store


def reserve_call_slot():
    counter = store.load("call_counter", {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    used_today = counter.get(today, 0)
    if used_today >= config.MAX_CALLS_PER_RUN:
        raise RuntimeError(
            f"Daily call cap MAX_CALLS_PER_RUN ({config.MAX_CALLS_PER_RUN}) reached for {today}; "
            "refusing to place another call"
        )
    counter[today] = used_today + 1
    store.save("call_counter", counter)
    total = sum(counter.values())
    return f"call-{total:02d}"


def calls_placed_total():
    counter = store.load("call_counter", {})
    return sum(counter.values())
