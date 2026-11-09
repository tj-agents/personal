#!/usr/bin/env python3
"""Approve, as tomjseery, the open tj-agents pull requests the bot App authored that await him (Python 3.12+)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "bot-identity" / "scripts"))
import bot_identity

ORG = "tj-agents"
REVIEWER = "tomjseery"
REPOSITORY_NAME = re.compile(r"[A-Za-z0-9_.-]+")
REMOVED = ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR")


class ApproveError(Exception):
    pass


def refusal() -> str | None:
    if bot_identity.AGENT_FLAG in os.environ:
        return "refusing in an agent session; Tommy runs `tj approve` in his own terminal"
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "refusing without an interactive terminal; Tommy runs `tj approve` in his own terminal"
    return None


def captured(run, command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess:
    return run(command, env=environment, check=False, capture_output=True, encoding="utf-8", errors="replace")


def reason(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else f"gh exited {result.returncode}"


def reviewer_environment(gh: str, run) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key not in REMOVED}
    result = captured(run, [gh, "auth", "token", "--user", REVIEWER], environment)
    token = (result.stdout or "").strip()
    if result.returncode or not token:
        raise ApproveError(f"gh has no {REVIEWER} login: {reason(result)}")
    return {**environment, "GH_TOKEN": token}


def gh_json(gh: str, arguments: list[str], environment: dict[str, str], run) -> object:
    result = captured(run, [gh, *arguments], environment)
    if result.returncode:
        raise ApproveError(f"gh {' '.join(arguments[:2])} failed: {reason(result)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ApproveError(f"gh {' '.join(arguments[:2])} returned invalid JSON") from error


def awaits_reviewer(details: dict) -> bool:
    head = details["headRefOid"]
    if any(request.get("login") == REVIEWER for request in details.get("reviewRequests") or []):
        return True
    return not any(review["state"] == "APPROVED" and (review.get("author") or {}).get("login") == REVIEWER
                   and (review.get("commit") or {}).get("oid") == head for review in details.get("reviews") or [])


def pending(gh: str, environment: dict[str, str], run, repository: str | None = None) -> list[dict]:
    scope = ["--repo", f"{ORG}/{repository}"] if repository else ["--owner", ORG]
    author = f"app/{bot_identity.app_descriptor()['slug']}"
    found = gh_json(gh, ["search", "prs", *scope, "--author", author, "--state", "open", "--limit", "100",
                         "--json", "repository,number,title,url"], environment, run)
    waiting = []
    for item in found:
        details = gh_json(gh, ["pr", "view", item["url"], "--json", "headRefOid,reviews,reviewRequests"],
                          environment, run)
        if awaits_reviewer(details):
            waiting.append({"name": f"{item['repository']['name']}#{item['number']}", "title": item["title"],
                            "url": item["url"]})
    return waiting


def approve(repository: str | None = None, run=subprocess.run, ask=input, out=sys.stdout) -> int:
    gh = bot_identity.real_gh()
    environment = reviewer_environment(gh, run)
    waiting = pending(gh, environment, run, repository)
    if not waiting:
        print("No pull requests await your approval.", file=out)
        return 0
    for item in waiting:
        print(f"{item['name']}  {item['title']}", file=out)
    try:
        answer = ask(f"Approve {len(waiting)} pull requests? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Nothing approved.", file=out)
        return 0
    failed = False
    for item in waiting:
        result = captured(run, [gh, "pr", "review", "--approve", item["url"]], environment)
        if result.returncode:
            failed = True
            print(f"failed {item['name']}: {reason(result)}", file=out)
        else:
            print(f"approved {item['name']}", file=out)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tj approve", description=__doc__)
    parser.add_argument("repository", nargs="?", help=f"limit to {ORG}/<repository>")
    arguments = parser.parse_args(argv)
    if arguments.repository and not REPOSITORY_NAME.fullmatch(arguments.repository):
        parser.error(f"name a repository in {ORG}, e.g. core")
    if message := refusal():
        print(f"tj approve: {message}", file=sys.stderr)
        return 2
    try:
        return approve(arguments.repository)
    except (ApproveError, bot_identity.IdentityError) as error:
        print(f"tj approve: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
