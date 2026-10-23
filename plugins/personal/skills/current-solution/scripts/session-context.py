"""Emit the packaged personal ground rules as SessionStart context without changing caller state."""

import hashlib
import json
from pathlib import Path
import sys

IDENTITY = "personal:current-solution"


def main():
    if sys.version_info < (3, 9):
        print(f"{IDENTITY}: Python 3.9 or newer is required.", file=sys.stderr)
        return 1

    contract = Path(__file__).resolve().parent.parent / "SKILL.md"
    try:
        source = contract.read_text(encoding="utf-8-sig")
        if not source.startswith("---\n"):
            raise ValueError("missing frontmatter")
        _, body = source.removeprefix("---\n").split("\n---\n", 1)
        if not body.strip():
            raise ValueError("missing contract body")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"{IDENTITY}: cannot read contract at {contract}: {error}", file=sys.stderr)
        return 1

    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    context = f"{IDENTITY} (source SHA-256 {digest})\nSource: {contract}\n\n{body.strip()}"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": context
    }}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
