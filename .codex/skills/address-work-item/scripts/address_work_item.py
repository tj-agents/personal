import argparse
from importlib import import_module
import json
from pathlib import Path
import sys


SKILL = Path(__file__).resolve().parents[1]
SOURCE_UTILITY = SKILL.parents[2] / "utility" / "work-item"
PUBLISHED_UTILITY = SKILL.parent / "work-item"
if SOURCE_UTILITY.is_dir():
    UTILITY = SOURCE_UTILITY
elif SKILL.parent.name == "skills" and PUBLISHED_UTILITY.is_dir():
    UTILITY = PUBLISHED_UTILITY
else:
    raise RuntimeError("cannot locate the published Personal work-item helper")
sys.path.insert(0, str(UTILITY))
github_tracker = import_module("github_tracker")
runtime_bootstrap = import_module("runtime_bootstrap")
runtime_bootstrap.bootstrap()
ItemError = import_module("tj_personal_work_items.records").ItemError


def parser():
    result = argparse.ArgumentParser(description="Address existing Personal work items")
    commands = result.add_subparsers(dest="command", required=True)
    github_tracker.add_commands(commands, ("update", "note", "link", "close"))
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        output = github_tracker.execute(parser().parse_args())
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (ItemError, OSError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
