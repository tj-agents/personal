"""Emit the packaged personal rules as SessionStart context in a project that selects personal."""

import json
import os
import sys

from personal_scope import CONTRACT, policy, repository_root, selects_personal

IDENTITY = "personal:rules"


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    root = repository_root(cwd or os.getcwd())
    if root is None or not selects_personal(root):
        return 0
    try:
        body, digest = policy()
    except (OSError, UnicodeError, ValueError, IndexError) as error:
        print(f"{IDENTITY}: cannot read contract at {CONTRACT}: {error}", file=sys.stderr)
        return 1
    context = f"{IDENTITY} (source SHA-256 {digest})\nSource: {CONTRACT}\n\n{body}"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": context
    }}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
