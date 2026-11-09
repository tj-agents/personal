#!/usr/bin/env python3
"""Approve, as tomjseery, the bot App's open pull requests for this agent session's work items (Python 3.12+)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "bot-identity" / "scripts"))
import bot_identity

ORG = "tj-agents"
REVIEWER = "tomjseery"
PULL_URL = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
NATIVE_SESSIONS = (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID"))
PR_FIELDS = "url,title,state,author,headRefOid,reviews,reviewRequests"


class ApproveError(Exception):
    pass


def tool(name: str) -> str:
    found = shutil.which(name) or shutil.which(name, path=str(bot_identity.tj_bin_directory()))
    if not found:
        raise ApproveError(f"{name} is not on PATH or in {bot_identity.tj_bin_directory()}")
    return found


def captured(run, command: list[str], environment: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return run(command, env=environment, check=False, capture_output=True, encoding="utf-8", errors="replace")


def reason(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else f"exited {result.returncode}"


def agent_store(arguments: list[str], run) -> dict | None:
    result = captured(run, [tool("agent-store"), *arguments])
    try:
        document = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise ApproveError(f"agent-store {arguments[0]} failed: {reason(result)}") from error
    if document.get("ok"):
        return document["data"]
    failure = document.get("error") or {}
    if failure.get("code") == "not-found":
        return None
    raise ApproveError(f"agent-store {arguments[0]} failed: {failure.get('message') or reason(result)}")


def linked(session: dict) -> list[str]:
    return [link["item"]["ref"] for link in session.get("links") or []]


def current_session(run) -> tuple[str | None, list[str]] | None:
    if launch_id := os.environ.get("TJ_RUN_LAUNCH_ID"):
        data = agent_store(["show", "--launch-id", launch_id], run)
        if data is None:
            return None
        launch, session = data["launch"], data.get("session")
        items = [launch["item"]["ref"]] if launch.get("item") else []
        return launch.get("session"), items + (linked(session) if session else [])
    for host, variable in NATIVE_SESSIONS:
        if native := os.environ.get(variable):
            data = agent_store(["show", f"{host}:{native}"], run)
            return None if data is None else (data["session"]["session"], linked(data["session"]))
    return None


def descendant_items(handle: str, run) -> list[str]:
    launches = agent_store(["launches"], run)["launches"]
    items, frontier, seen = [], [handle], {handle}
    while frontier:
        parent = frontier.pop()
        for launch in launches:
            if launch.get("parent") != parent:
                continue
            if launch.get("item"):
                items.append(launch["item"]["ref"])
            child = launch.get("session")
            if child and child not in seen:
                seen.add(child)
                frontier.append(child)
                data = agent_store(["show", child], run)
                if data is not None:
                    items += linked(data["session"])
    return items


def reviewer_environment(gh: str, run) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key not in bot_identity.AGENT_ONLY}
    result = captured(run, [gh, "auth", "token", "--user", REVIEWER], environment)
    token = (result.stdout or "").strip()
    if result.returncode or not token:
        raise ApproveError(f"gh has no {REVIEWER} login: {reason(result)}")
    return {**environment, "GH_TOKEN": token}


def json_output(command: list[str], environment: dict[str, str], run) -> object:
    result = captured(run, command, environment)
    label = " ".join([Path(command[0]).stem, *command[1:3]])
    if result.returncode:
        raise ApproveError(f"{label} failed: {reason(result)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ApproveError(f"{label} returned invalid JSON") from error


def bot_authored(details: dict) -> bool:
    slug = bot_identity.app_descriptor()["slug"]
    return (details.get("author") or {}).get("login") in (f"app/{slug}", slug, f"{slug}[bot]")


def awaits_reviewer(details: dict) -> bool:
    head = details["headRefOid"]
    if any(request.get("login") == REVIEWER for request in details.get("reviewRequests") or []):
        return True
    return not any(review["state"] == "APPROVED" and (review.get("author") or {}).get("login") == REVIEWER
                   and (review.get("commit") or {}).get("oid") == head for review in details.get("reviews") or [])


def display_name(url: str) -> str:
    match = PULL_URL.match(url)
    if not match:
        return url
    owner, name, number = match.groups()
    return f"{name}#{number}" if owner == ORG else f"{owner}/{name}#{number}"


def pending(items: list[str], gh: str, environment: dict[str, str], run) -> list[dict]:
    urls = []
    for item in dict.fromkeys(items):
        found = json_output([tool("tj"), "item", "prs", item], environment, run)
        urls += [pull["url"] for pull in found["prs"] if pull.get("state") == "open"]
    waiting = []
    for url in dict.fromkeys(urls):
        details = json_output([gh, "pr", "view", url, "--json", PR_FIELDS], environment, run)
        if details.get("state") == "OPEN" and bot_authored(details) and awaits_reviewer(details):
            waiting.append({"name": display_name(url), "title": details.get("title", ""), "url": url})
    return waiting


def approve(run=subprocess.run, out=sys.stdout) -> int:
    session = current_session(run)
    if session is None:
        print("No agent session found here; nothing approved.", file=out)
        return 0
    handle, items = session
    if handle:
        items += descendant_items(handle, run)
    if not items:
        print("No work items are linked to this session; nothing approved.", file=out)
        return 0
    gh = bot_identity.real_gh()
    environment = reviewer_environment(gh, run)
    waiting = pending(items, gh, environment, run)
    if not waiting:
        print("No pull requests await your approval.", file=out)
        return 0
    for item in waiting:
        print(f"{item['name']}  {item['title']}", file=out)
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
    argparse.ArgumentParser(prog="tj approve", description=__doc__).parse_args(argv)
    try:
        return approve()
    except (ApproveError, bot_identity.IdentityError) as error:
        print(f"tj approve: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
