"""Deny a git commit that removes a skill while tracked sources still name it."""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

from personal_scope import repository_root, selects_personal

RESERVED = {"continuation", "plugins", "tiers", "tests", "hooks"}
GENERATED = ("plugins", ".claude/skills", ".codex/skills", ".agents/INDEX.md",
             ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json")
COMMIT = re.compile(r"""\bgit((?:\s+(?:-C\s+(?:"[^"]*"|'[^']*'|\S+)|-c\s+\S+|--\S+))*)\s+commit\b(?P<args>[^;&|\n]*)""")
CHDIR = re.compile(r"""(?:^|[;&|\n]\s*)(?:cd|Set-Location|pushd|Push-Location)\s+(?P<path>"[^"]*"|'[^']*'|[^\s;&|]+)""")
TARGET = re.compile(r"""-C\s+("[^"]*"|'[^']*'|\S+)""")
NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
VALUE_FLAGS = set("mFCct")
ATTACHED_VALUE_FLAGS = set("uS")
WORKTREE_FLAGS = set("aoi")
SHELLS = {"bash", "sh", "zsh", "dash", "pwsh", "powershell", "cmd"}
VALUE_OPTIONS = {"--message", "--file", "--author", "--date", "--template", "--reuse-message",
                 "--reedit-message", "--fixup", "--squash", "--cleanup", "--trailer"}
STAGES = re.compile(r"\bgit\b(?:\s+-C\s+\S+)?\s+(?P<verb>add|rm|mv)\b")


class GitError(Exception):
    pass


def command_text(tool_input):
    value = tool_input.get("command") or tool_input.get("cmd") or ""
    if not isinstance(value, list):
        return str(value)
    words = [str(word) for word in value]
    shell = bool(words) and Path(words[0]).stem.lower() in SHELLS
    return "\n".join(words) if shell else shlex.join(words)


def unquote(value):
    return value[1:-1] if value[:1] in "\"'" and value[-1:] == value[:1] else value


def tokens(arguments):
    try:
        return shlex.split(arguments)
    except ValueError:
        return arguments.split()


def commits_worktree(arguments):
    values = iter(tokens(arguments))
    for token in values:
        if token == "--" or not token.startswith("-"):
            return True
        if token.startswith("--"):
            if token in ("--all", "--only", "--include"):
                return True
            if token in VALUE_OPTIONS:
                next(values, None)
            continue
        for index, flag in enumerate(token[1:], 1):
            if flag in WORKTREE_FLAGS:
                return True
            if flag in ATTACHED_VALUE_FLAGS:
                break
            if flag in VALUE_FLAGS:
                if index == len(token) - 1:
                    next(values, None)
                break
    return False


def resolve(directory, value):
    return directory / Path(os.path.expanduser(unquote(value)))


def commit_target(command, directory):
    match = COMMIT.search(command)
    if match is None:
        return None
    for move in CHDIR.finditer(command[:match.start()]):
        directory = resolve(directory, move["path"])
    for option in TARGET.finditer(match.group(1)):
        directory = resolve(directory, option.group(1))
    staged = {stage["verb"] for stage in STAGES.finditer(command[:match.start()])}
    return directory, commits_worktree(match["args"]) or "add" in staged, bool(staged & {"rm", "mv"})


def git(root, *arguments, accept=(0,)):
    result = subprocess.run(["git", "-C", str(root), *arguments],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode not in accept:
        raise GitError(f"git {arguments[0]} failed: {result.stderr.strip()[:300]}")
    return result.stdout


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
        raise GitError(f"git cat-file failed: {result.stderr.decode('utf-8', 'replace').strip()[:300]}")
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
    if not git(root, "rev-parse", "--verify", "--quiet", "HEAD", accept=(0, 1)).strip():
        return set()
    owners = packages(root)
    changed = git(root, "diff", "--cached", "--no-renames", "--name-only", "--diff-filter=DM", "HEAD").split("\n")
    if include_worktree:
        changed += git(root, "diff", "--no-renames", "--name-only", "--diff-filter=DM", "HEAD").split("\n")
    candidates = sorted({path for path in changed if skill_path(path)})
    if not candidates:
        return set()
    old = set()
    for path, body in zip(candidates, blobs(root, [f"HEAD:{path}" for path in candidates])):
        old |= qualified(path, body, owners)
    listing = ["ls-files", "--cached", *(["--others", "--exclude-standard"] if include_worktree else []), "--", ".agents"]
    paths = sorted({path for path in git(root, *listing).split("\n") if skill_path(path)})
    current = set()
    if include_worktree:
        for path in paths:
            try:
                body = (root / path).read_bytes().decode("utf-8-sig", errors="replace")
            except OSError:
                continue
            current |= qualified(path, body, owners)
    else:
        for path, body in zip(paths, blobs(root, [f":0:{path}" for path in paths])):
            current |= qualified(path, body, owners)
    return old - current


def references(root, names, include_worktree):
    arguments = ["grep", "-n", "-I", "-F", *([] if include_worktree else ["--cached"])]
    for name in sorted(names):
        arguments += ["-e", name]
    arguments += ["--", ".", *(f":(exclude){path}" for path in GENERATED)]
    bounded = re.compile("|".join(
        rf"(?<![A-Za-z0-9_:-]){re.escape(name)}(?![A-Za-z0-9_-])" for name in sorted(names)))
    lines = git(root, *arguments, accept=(0, 1)).splitlines()
    return [line for line in lines if bounded.search(line.split(":", 2)[-1])]


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=True))
    return 0


def check(root, include_worktree, stages_removal):
    if stages_removal:
        return ("Clean cut: run `git rm`/`git mv` and the commit as separate calls so the gate can see "
                "what this commit removes.")
    names = removed_skills(root, include_worktree)
    hits = references(root, names, include_worktree) if names else []
    if not hits:
        return None
    shown = "\n".join(f"  {hit}" for hit in hits[:40])
    more = f"\n  ... and {len(hits) - 40} more" if len(hits) > 40 else ""
    return (f"Clean cut: this commit removes {', '.join(sorted(names))}, but tracked files still name "
            f"{'them' if len(names) > 1 else 'it'}:\n{shown}{more}\nMigrate each reference to the "
            "current skill or delete it, then commit again. Generated payloads are excluded; "
            "regenerate them with the repository's sync.")


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("tool_input"), dict):
        return 0
    tool_input = data["tool_input"]
    start = Path(str(tool_input.get("workdir") or data.get("cwd") or os.getcwd()))
    target = commit_target(command_text(tool_input), start)
    if target is None:
        return 0
    directory, include_worktree, stages_removal = target
    root = repository_root(directory)
    if root is None or not selects_personal(root):
        return 0
    try:
        reason = check(root, include_worktree, stages_removal)
    except Exception as error:
        reason = (f"Clean cut: the gate could not inspect this commit in {root} ({error}). "
                  "Resolve the error and commit again.")
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
