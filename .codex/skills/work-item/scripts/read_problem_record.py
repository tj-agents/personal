import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from github_tracker import GitHub, Tracker, digest, issue_number, metadata, selection
from tj_personal_work_items.records import ItemError


def read(root, reference):
    tracker = Tracker(selection(root), GitHub(timeout=10))
    number = issue_number(reference, tracker.repo)
    if reference != f"https://github.com/{tracker.repo}/issues/{number}":
        raise ItemError("problem records require the canonical GitHub issue URL")
    issue = tracker.get(number)
    info, text = metadata(issue["body"])
    if digest(text) != info["render_hash"]:
        raise ItemError("problem record was manually edited; reconcile its managed body")
    if digest(info["kind"] + "\n" + text) != info.get("kind_hash"):
        raise ItemError("problem record kind differs or is unbound; update its managed body before use")
    compact = tracker.compact(issue)
    if compact["kind"] not in {"bug", "mistake", "debt"} or compact["state"] != "open":
        raise ItemError("reader supports only open problem records")
    return {"record": compact["url"], "kind": compact["kind"], "state": compact["state"], "body": issue["body"]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Read one canonical Personal problem record for an optional Core protocol")
    parser.add_argument("--root", required=True)
    parser.add_argument("--record", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(read(args.root, args.record), ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ItemError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
