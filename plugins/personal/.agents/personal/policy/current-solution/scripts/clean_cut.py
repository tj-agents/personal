"""Block a git commit that removes a skill while tracked sources still name it."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

PERSONAL = "personal@tj-agents"
RESERVED = {"continuation", "plugins", "tiers", "tests", "hooks"}
GENERATED = ("plugins", ".claude/skills", ".codex/skills", ".agents/INDEX.md",
             ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json")
COMMIT = re.compile(r"""\bgit((?:\s+(?:-C\s+(?:"[^"]*"|'[^']*'|\S+)|-c\s+\S+|--\S+))*)\s+commit\b(?P<args>[^;&|\n]*)""")
CHDIR = re.compile(r"""(?:^|[;&|\n]\s*)(?:cd|Set-Location|pushd|Push-Location)\s+(?P<path>"[^"]*"|'[^']*'|[^\s;&|]+)""")
TARGET = re.compile(r"""-C\s+("[^"]*"|'[^']*'|\S+)""")
NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
MESSAGE_FLAGS = set("mFCc")


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)


def unquote(value):
    return value[1:-1] if value[:1] in "\"'" and value[-1:] == value[:1] else value


def commits_all(arguments):
    for token in arguments.split():
        if token == "--all":
            return True
        if token.startswith("--") or not token.startswith("-"):
            continue
        for flag in token[1:]:
            if flag == "a":
                return True
            if flag in MESSAGE_FLAGS:
                return False
    return False


def commit_target(command, cwd):
    match = COMMIT.search(command)
    if match is None:
        return None
    directory = Path(cwd)
    moves = [move for move in CHDIR.finditer(command) if move.start() < match.start()]
    if moves:
        directory = directory / Path(os.path.expanduser(unquote(moves[-1]["path"])))
    for option in TARGET.finditer(match.group(1)):
        directory = directory / Path(os.path.expanduser(unquote(option.group(1))))
    return directory, commits_all(match["args"])


def git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode, result.stdout


def selects_personal(root):
    try:
        selection = json.loads((root / ".agents/plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(selection, dict) and PERSONAL in (selection.get("plugins") or [])


def packages(root):
    try:
        payloads = json.loads((root / ".agents/plugins/payloads.json").read_text(encoding="utf-8"))["payloads"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    owners = {}
    for package, sources in payloads.items():
        for source in sources:
            owners.setdefault(source, []).append(package)
    return owners


def skill_path(path):
    parts = path.split("/")
    return len(parts) >= 4 and parts[0] == ".agents" and parts[1] not in RESERVED and parts[-1] == "SKILL.md"


def qualified(path, body, owners):
    body = body.replace("\r\n", "\n")
    match = NAME.search(body.split("\n---", 1)[0]) if body.startswith("---") else None
    if match is None:
        return set()
    source = path.split("/")[1]
    return {f"{package}:{match.group(1)}" for package in owners.get(source, [source])}


def blobs(root, revisions):
    if not revisions:
        return []
    result = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], capture_output=True,
                            input="".join(f"{revision}\n" for revision in revisions).encode("utf-8"))
    if result.returncode:
        return [""] * len(revisions)
    output, bodies, cursor = result.stdout, [], 0
    for _ in revisions:
        header_end = output.index(b"\n", cursor)
        header = output[cursor:header_end].split()
        cursor = header_end + 1
        if len(header) < 3 or header[1] != b"blob":
            bodies.append("")
            continue
        size = int(header[2])
        bodies.append(output[cursor:cursor + size].decode("utf-8-sig", errors="replace"))
        cursor += size + 1
    return bodies


def removed_skills(root, include_worktree):
    owners = packages(root)
    changed = git(root, "diff", "--cached", "--no-renames", "--name-only", "--diff-filter=DM", "HEAD")[1].split("\n")
    if include_worktree:
        changed += git(root, "diff", "--no-renames", "--name-only", "--diff-filter=DM", "HEAD")[1].split("\n")
    candidates = sorted({path for path in changed if skill_path(path)})
    if not candidates:
        return set()
    old = set()
    for path, body in zip(candidates, blobs(root, [f"HEAD:{path}" for path in candidates])):
        old |= qualified(path, body, owners)
    listed = git(root, "ls-files", "--", ".agents")[1].split("\n")
    current = set()
    paths = [path for path in listed if skill_path(path)]
    if include_worktree:
        for path in paths:
            try:
                current |= qualified(path, (root / path).read_text(encoding="utf-8-sig"), owners)
            except OSError:
                continue
    else:
        for path, body in zip(paths, blobs(root, [f":0:{path}" for path in paths])):
            current |= qualified(path, body, owners)
    return old - current


def references(root, names, include_worktree):
    arguments = ["grep", "-n", "-I", "-E"]
    if not include_worktree:
        arguments.append("--cached")
    for name in sorted(names):
        arguments += ["-e", f"(^|[^A-Za-z0-9_:-]){re.escape(name)}([^A-Za-z0-9_-]|$)"]
    arguments += ["--", ".", *(f":(exclude){path}" for path in GENERATED)]
    return [line for line in git(root, *arguments)[1].splitlines() if line]


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    command = "\n".join(strings(data.get("tool_input") or {}))
    target = commit_target(command, data.get("cwd") or os.getcwd())
    if target is None:
        return 0
    directory, include_worktree = target
    code, top = git(directory, "rev-parse", "--show-toplevel")
    if code:
        return 0
    root = Path(top.strip())
    if not selects_personal(root):
        return 0
    names = removed_skills(root, include_worktree)
    if not names:
        return 0
    hits = references(root, names, include_worktree)
    if not hits:
        return 0
    shown = "\n".join(f"  {hit}" for hit in hits[:40])
    more = f"\n  ... and {len(hits) - 40} more" if len(hits) > 40 else ""
    print(f"Clean cut: this commit removes {', '.join(sorted(names))}, but tracked files still name "
          f"{'them' if len(names) > 1 else 'it'}:\n"
          f"{shown}{more}\nMigrate each reference to the current skill or delete it, then commit again. "
          "Generated payloads are excluded; regenerate them with the repository's sync.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
