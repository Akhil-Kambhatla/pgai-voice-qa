import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analyst import analyze_call


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: analyze_call.py <call_id>")
    changes = analyze_call(sys.argv[1])
    if not changes:
        print("No changes to any data file.")
        return
    for change in changes:
        print(change)


if __name__ == "__main__":
    main()
