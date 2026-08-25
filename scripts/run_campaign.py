import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import campaign_call, campaign_render, campaign_scenario, campaign_summary
from src import config
from src.planner import pinned_axes, plan_next_call

MAX_PLAN_ATTEMPTS = 3
SCRIPTS_DIR = os.path.join(config.PROJECT_DIR, "scripts")


def plan_valid_scenario(planner=plan_next_call, max_attempts=MAX_PLAN_ATTEMPTS):
    attempts = []
    for attempt in range(1, max_attempts + 1):
        scenario = planner()
        failures = campaign_scenario.validate(scenario)
        attempts.append((scenario.get("scenario_id"), failures))
        if not failures:
            return scenario, attempts
        print(f"  attempt {attempt} rejected: {scenario.get('scenario_id')}")
        for failure in failures:
            print(f"    {failure}")
    return None, attempts


def run_step(name, *arguments):
    done = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, name), *arguments],
        cwd=config.PROJECT_DIR, capture_output=True, text=True,
    )
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-4:]
        raise campaign_call.PreflightFailure(f"{name} failed: {' / '.join(tail)}")
    return done.stdout


def announce(turn):
    speaker = turn.get("speaker", "?")
    text = (turn.get("text") or "").replace("\n", " ")
    print(f"    [{turn.get('elapsed_seconds', 0):6.1f}s] {speaker:6} {text[:88]}")


def run_one_call(number, ask, planner=plan_next_call, dial=campaign_call.dial,
                 wait=campaign_call.wait_for_completion, steps=run_step, regenerate=True):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    placed, tunnels = campaign_call.preflight(today)
    print(f"preflight ok: server up, {tunnels} ngrok tunnel matching PUBLIC_BASE_URL, "
          f"{placed} of {config.MAX_CALLS_PER_RUN} calls placed today")

    print("planning..." if regenerate else "loading the scenario you wrote...")
    scenario, attempts = plan_valid_scenario(planner, MAX_PLAN_ATTEMPTS if regenerate else 1)
    if scenario is None:
        if regenerate:
            print(f"gave up after {len(attempts)} attempts; the planner could not produce a valid scenario:")
        else:
            print("the scenario you wrote was rejected, and there is nothing to regenerate from:")
        for scenario_id, failures in attempts:
            print(f"  {scenario_id}: {'; '.join(failures)}")
        return "planning_failed"

    print(campaign_render.render(scenario))
    answer = ask("dial this scenario? [enter] dial, [s] skip and regenerate, [q] quit: ")
    if answer.strip().lower() == "q":
        return "quit"
    if answer.strip().lower() == "s":
        return "skipped"

    print(f"dialling {number}...")
    started = dial(scenario["scenario_id"], number)
    call_id = started["call_id"]
    print(f"  call_id {call_id}, placed at {started.get('placed_at')}")

    completion = wait(call_id, on_progress=announce)
    if completion["outcome"] == "timeout":
        raise campaign_call.PreflightFailure(
            f"no Telnyx completion for {call_id} after {completion['waited']}s; check the server and ngrok"
        )
    print(f"  call completed after {completion['duration']}s, hung up by {completion['hangup_source']}")

    qualified = f"campaign/{call_id}" if config.CALL_TREE == "campaign" else call_id
    print("fetching and transcribing...")
    steps("fetch_and_transcribe.py", qualified)
    print("analysing...")
    steps("analyze_call.py", qualified)
    print(campaign_summary.summarise(qualified, completion))
    return "completed"


def main():
    parser = argparse.ArgumentParser(description="Run the graded campaign call loop.")
    parser.add_argument("number", nargs="?", default=config.TARGET_NUMBER)
    parser.add_argument("--identity", help="shorthand for --axis identity=NAME")
    parser.add_argument(
        "--axis", action="append", default=[], metavar="NAME=VALUE",
        help="pin one axis, repeatable; the sampler still chooses the rest",
    )
    parser.add_argument(
        "--scenario", metavar="PATH",
        help="dial a scenario JSON you wrote by hand instead of planning one",
    )
    arguments = parser.parse_args()
    pinned = pinned_axes(arguments.identity, arguments.axis)

    number = arguments.number
    if arguments.scenario:
        planner, regenerate = campaign_scenario.load_written(arguments.scenario), False
        source_note = f", from {arguments.scenario}"
    else:
        planner, regenerate = lambda: plan_next_call(
            identity=arguments.identity, axis_pairs=arguments.axis), True
        source_note = f", pinned {pinned}" if pinned else ""
    print(f"campaign runner: dialling {number}, cap {config.MAX_CALLS_PER_RUN} per day, "
          f"{config.MAX_CALL_SECONDS}s per call{source_note}")
    while True:
        try:
            outcome = run_one_call(number, input, planner=planner, regenerate=regenerate)
        except campaign_call.PreflightFailure as failure:
            print(f"\nSTOPPED: {failure}")
            return 1
        if outcome == "quit":
            print("stopping at your request")
            return 0
        if outcome == "skipped" and not regenerate:
            print("skipped, and there is no second draft of a scenario you wrote by hand")
            return 0
        if outcome == "planning_failed":
            return 1
        if outcome == "completed":
            again = input("\nrun another call? [enter] yes, [q] no: ")
            if again.strip().lower() == "q":
                print("stopping at your request")
                return 0


if __name__ == "__main__":
    sys.exit(main())
