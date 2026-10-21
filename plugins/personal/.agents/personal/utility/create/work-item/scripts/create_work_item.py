from importlib import import_module
from pathlib import Path
import sys


SKILL = Path(__file__).resolve().parents[1]
SOURCE_UTILITY = SKILL.parents[1] / "work-item"
PUBLISHED_UTILITY = SKILL.parent / "work-item"
if SOURCE_UTILITY.is_dir():
    UTILITY = SOURCE_UTILITY
elif SKILL.parent.name == "skills" and PUBLISHED_UTILITY.is_dir():
    UTILITY = PUBLISHED_UTILITY
else:
    raise RuntimeError("cannot locate the published Personal work-item helper")
sys.path.insert(0, str(UTILITY))
work_item = import_module("work_item")


def main():
    return work_item.main()


if __name__ == "__main__":
    raise SystemExit(main())
