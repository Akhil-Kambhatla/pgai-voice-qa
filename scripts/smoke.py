import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import smoke_checks, smoke_config, smoke_planner, smoke_replay
from src import config

SCRIPTS_DIR = os.path.join(config.PROJECT_DIR, "scripts")
DEFAULT_PLANNER_DRAWS = 3


def run_script(name):
    def check():
        done = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, name)],
            cwd=config.PROJECT_DIR, capture_output=True, text=True,
        )
        if done.returncode != 0:
            tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
            raise AssertionError(" / ".join(tail))

    return check


CHECKS = [
    ("prompt assembly", "the scope paragraph, second person, tool parity, prompt size",
     smoke_checks.prompt_assembly),
    ("turn detection config", "every VAD combination assembles, every bad one dies at startup",
     smoke_config.config_combinations),
    ("hang_up gate", "grants and denials, and a denial scheduling a retry",
     run_script("test_exit_path.py")),
    ("goal judge", "the 2s timeout and failing closed instead of ending a live call",
     run_script("test_goal_judge.py")),
    ("payload hygiene", "no prose in a tool result or a nudge for the model to read aloud",
     smoke_checks.payload_hygiene),
    ("commentary replay", "the phase filter, against two calls it took three rounds to fix",
     smoke_replay.commentary_filter),
    ("transcript channels", "channel 1 is the bot, so the submission is not mislabelled",
     smoke_checks.transcription_mapping),
    ("call tree resolution", "graded calls cannot land in the roleplay tree",
     smoke_checks.call_tree_resolution),
]


def main():
    draws = DEFAULT_PLANNER_DRAWS
    for index, argument in enumerate(sys.argv):
        if argument == "--planner-draws" and index + 1 < len(sys.argv):
            draws = int(sys.argv[index + 1])

    results = []
    for name, protects, check in CHECKS:
        started = time.monotonic()
        try:
            check()
            results.append((name, protects, "PASS", "", time.monotonic() - started))
        except Exception as error:
            results.append((name, protects, "FAIL", str(error), time.monotonic() - started))

    width = max(len(name) for name, *_ in results)
    print()
    print("=" * 78)
    print("SMOKE SUITE")
    print("=" * 78)
    for name, protects, status, detail, seconds in results:
        print(f"{status:4}  {name:{width}}  {seconds:5.2f}s  {protects}")
        if detail:
            print(f"      {'':{width}}         {detail}")
    failed = [r for r in results if r[2] == "FAIL"]
    print("-" * 78)
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed")

    if draws:
        print()
        print("=" * 78)
        print(f"PLANNER CONTRACT ({draws} draws, advisory, does not fail the suite)")
        print("=" * 78)
        sampled = smoke_planner.sample(draws)
        clean = 0
        for slug, failures in sampled:
            if failures:
                print(f"MISS  {slug}")
                for failure in failures:
                    print(f"      {failure}")
            else:
                clean += 1
                print(f"OK    {slug}")
        print("-" * 78)
        print(f"{clean} of {len(sampled)} draws satisfied the contract")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
