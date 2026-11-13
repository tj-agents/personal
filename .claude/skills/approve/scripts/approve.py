#!/usr/bin/env python3
"""Approve the configured bot's PRs as its human reviewer for this session's work items and arm their auto-merge
(Python 3.12+)."""

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

PULL_URL = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)")
PR_FIELDS = "url,title,state,author,headRefOid,reviews,reviewRequests"


class ApproveError(Exception):
    pass


def descendant_items(handle: str, run) -> list[str]:
    launches = bot_identity.agent_store(["launches"], run)["launches"]
    candidates = [link["session"] for item in bot_identity.agent_store(["items"], run)["items"]
                  for link in item["sessions"]]
    candidates += [launch[key] for launch in launches for key in ("parent", "session") if launch.get(key)]
    sessions, inspected = {}, {handle}
    for candidate in candidates:
        if candidate in inspected:
            continue
        inspected.add(candidate)
        data = bot_identity.agent_store(["show", candidate], run)
        if data is None:
            continue
        session = data["session"]
        sessions[candidate] = session
        if session.get("parent"):
            candidates.append(session["parent"])
    items, frontier, seen = [], [handle], {handle}
    while frontier:
        parent = frontier.pop()
        children = [child for child, session in sessions.items() if session.get("parent") == parent]
        for launch in launches:
            if launch.get("parent") != parent:
                continue
            if launch.get("item"):
                items.append(launch["item"]["ref"])
            if launch.get("session"):
                children.append(launch["session"])
        for child in children:
            if child in seen:
                continue
            seen.add(child)
            frontier.append(child)
            if child in sessions:
                items += bot_identity.linked(sessions[child])
    return items


def reviewer_environment(gh: str, reviewer: str, run) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if key not in bot_identity.AGENT_ONLY and not key.startswith("GIT_CONFIG_")}
    environment["GH_HOST"] = "github.com"
    result = bot_identity.captured(run, [gh, "auth", "token", "--hostname", "github.com"], environment)
    token = (result.stdout or "").strip()
    if result.returncode or not token:
        raise ApproveError(f"gh could not read the native github.com credential; check gh auth status "
                           f"before approving as {reviewer}")
    environment["GH_TOKEN"] = token
    actual = bot_identity.captured(run, [gh, "api", "user", "--jq", ".login"], environment)
    if actual.returncode:
        detail = bot_identity.reason(actual).replace(token, "[redacted]")
        raise ApproveError(
            f"gh could not verify the configured human reviewer {reviewer}: {detail}; nothing approved"
        )
    if (actual.stdout or "").strip().casefold() != reviewer.casefold():
        raise ApproveError(f"gh did not authenticate the configured human reviewer {reviewer}; nothing approved")
    return environment


def json_output(
    command: list[str], environment: dict[str, str], run,
    *, timeout_seconds: int = bot_identity.TIMEOUT_SECONDS,
) -> object:
    result = bot_identity.captured(run, command, environment, timeout_seconds=timeout_seconds)
    label = " ".join([Path(command[0]).stem, *command[1:3]])
    if result.returncode:
        raise ApproveError(f"{label} failed: {bot_identity.reason(result)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ApproveError(f"{label} returned invalid JSON") from error


def bot_authored(details: dict, slug: str) -> bool:
    author = details.get("author") or {}
    if author.get("type") == "User" or author.get("__typename") == "User" or author.get("is_bot") is False:
        return False
    return author.get("login") in (f"app/{slug}", slug, f"{slug}[bot]")


def awaits_reviewer(details: dict, reviewer: str) -> bool:
    head = details["headRefOid"]
    if any(request.get("login", "").casefold() == reviewer.casefold()
           for request in details.get("reviewRequests") or []):
        return True
    return not any(review["state"] == "APPROVED"
                   and (review.get("author") or {}).get("login", "").casefold() == reviewer.casefold()
                   and (review.get("commit") or {}).get("oid") == head for review in details.get("reviews") or [])


def display_name(url: str) -> str:
    match = PULL_URL.fullmatch(url)
    if not match:
        return url
    owner, name, number = match.groups()
    return f"{owner}/{name}#{number}"


def pending(items: list[str], gh: str, environment: dict[str, str], configuration: dict, run) -> list[dict]:
    urls = []
    for item in dict.fromkeys(items):
        found = json_output(
            [bot_identity.tool("tj"), "item", "--profile", "github", "prs", item], environment, run,
            timeout_seconds=bot_identity.ITEM_TIMEOUT_SECONDS,
        )
        urls += [pull["url"] for pull in found["prs"] if pull.get("state") == "open"]
    waiting = []
    accounts = {account.casefold() for account in configuration["accounts"]}
    for url in dict.fromkeys(urls):
        match = PULL_URL.fullmatch(url)
        if match is None or match.group(1).casefold() not in accounts:
            continue
        details = json_output([gh, "pr", "view", url, "--json", PR_FIELDS], environment, run)
        if (details.get("author") or {}).get("login", "").casefold() == configuration["reviewer"].casefold():
            continue
        if (details.get("state") == "OPEN" and bot_authored(details, configuration["app"]["slug"])
                and awaits_reviewer(details, configuration["reviewer"])):
            waiting.append({"name": display_name(url), "title": details.get("title", ""), "url": url,
                            "head": details["headRefOid"]})
    return waiting


def approve(
    run=subprocess.run, out=sys.stdout, session_handle: str | None = None
) -> int:
    session = bot_identity.current_session(run, session_handle)
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
    configuration = bot_identity.identity_config()
    environment = reviewer_environment(gh, configuration["reviewer"], run)
    waiting = pending(items, gh, environment, configuration, run)
    if not waiting:
        print("No pull requests await your approval.", file=out)
        return 0
    for item in waiting:
        print(f"{item['name']}  {item['title']}", file=out)
    failed = False
    for item in waiting:
        result = bot_identity.captured(run, [gh, "pr", "review", "--approve", item["url"]], environment)
        if result.returncode:
            failed = True
            print(f"failed {item['name']}: {bot_identity.reason(result)}", file=out)
            continue
        print(f"approved {item['name']}", file=out)
        merge = bot_identity.captured(run, [gh, "pr", "merge", "--auto", "--squash", "--match-head-commit",
                                            item["head"], item["url"]], environment)
        if merge.returncode:
            failed = True
            print(f"not merging {item['name']}: {bot_identity.reason(merge)}", file=out)
        else:
            print(f"merging {item['name']} when its checks pass", file=out)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tj approve", description=__doc__)
    parser.add_argument(
        "--session", metavar="HOST:ID", help="registered originating agent session"
    )
    arguments = parser.parse_args(argv)
    try:
        return approve(session_handle=arguments.session)
    except (ApproveError, bot_identity.IdentityError) as error:
        print(f"tj approve: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
