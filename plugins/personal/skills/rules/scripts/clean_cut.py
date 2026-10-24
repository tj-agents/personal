"""Deny a git commit that removes a skill while tracked sources still name it."""

from functools import cache
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

from personal_scope import repository_root, selects_personal

RESERVED = {"continuation", "plugins", "tiers", "tests", "hooks"}
GENERATED = ("plugins", ".claude/skills", ".codex/skills", ".agents/INDEX.md",
             ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json")
GIT_OPTIONS = r"""((?:\s+(?:-C\s+(?:"[^"]*"|'[^']*'|\S+)|-c\s+\S+|--\S+))*)"""
COMMIT = re.compile(rf"""\bgit{GIT_OPTIONS}\s+commit\b(?!-)(?P<args>[^;&|\n]*)""")
STAGES = re.compile(rf"""\bgit{GIT_OPTIONS}\s+(?P<verb>add|rm|mv)\b""")
CHDIR = re.compile(r"""(?:^|[;&|\n]\s*)(?:cd|Set-Location|pushd|Push-Location)(?:\s+(?:-Path|-LiteralPath|/d))?\s+(?P<path>"[^"]*"|'[^']*'|[^\s;&|]+)""", re.IGNORECASE)
TARGET = re.compile(r"""-C\s+("[^"]*"|'[^']*'|\S+)""")
HEREDOC = re.compile(r"""(?<!<)<<(?!<)-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1""")
MESSAGE = re.compile(r"""(?<=\s)(?:-[A-Za-z]*[mF]|--message|--file)(?:=|\s+)""")
REDIRECT = re.compile(r"^\d*[<>]+&?(?P<target>.*)$")
UNRESOLVED = re.compile(r"[$%`]")
DRIVE = re.compile(r"^/([A-Za-z])(?=/|$)")
NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
VALUE_FLAGS = set("mFCct")
ATTACHED_VALUE_FLAGS = set("uS")
WORKTREE_FLAGS = set("aoi")
SHELLS = {"bash", "sh", "zsh", "dash", "pwsh", "powershell", "cmd"}
VALUE_OPTIONS = {"--message", "--file", "--author", "--date", "--template", "--reuse-message",
                 "--reedit-message", "--fixup", "--squash", "--cleanup", "--trailer"}
BUDGET_SECONDS = 25
deadline = 0.0


class GitError(Exception):
    pass


def command_text(tool_input):
    value = tool_input.get("command") or tool_input.get("cmd") or ""
    if not isinstance(value, list):
        return str(value)
    words = [str(word) for word in value]
    shell = bool(words) and Path(words[0]).stem.lower() in SHELLS
    return "\n".join(words) if shell else shlex.join(words)


def heredoc_end(command, heredoc):
    body = command.find("\n", heredoc.end())
    if body == -1:
        return heredoc.end()
    end = re.compile(rf"^\s*{re.escape(heredoc.group(2))}\s*$", re.MULTILINE).search(command, body + 1)
    return end.end() if end else len(command)


def value_end(command, start):
    if command.startswith(("@'", '@"'), start):
        close = command.find(f"\n{command[start + 1]}@", start + 2)
        return close + 3 if close != -1 else len(command)
    if command[start:start + 1] == "'":
        index = start + 1
        while (index := command.find("'", index)) != -1 and command[index + 1:index + 2] == "'":
            index += 2
        return index + 1 if index != -1 else len(command)
    if command[start:start + 1] == '"':
        index, depth = start + 1, 0
        while index < len(command):
            char = command[index]
            heredoc = HEREDOC.match(command, index) if depth else None
            if heredoc:
                index = heredoc_end(command, heredoc)
                continue
            if char == "\\" and command[index + 1:index + 2] in ('"', "\\", "$", "`"):
                index += 2
                continue
            if char == "(" and command[index - 1] == "$":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif char == '"' and not depth:
                return index + 1
            index += 1
        return len(command)
    match = re.compile(r"\S*").match(command, start)
    return match.end()


def masked(command):
    chars = list(command)

    for flag in MESSAGE.finditer(command):
        for position in range(flag.end(), value_end(command, flag.end())):
            chars[position] = "x"
    shape = "".join(chars)
    for heredoc in HEREDOC.finditer(shape):
        body = shape.find("\n", heredoc.end())
        if body != -1:
            for position in range(body + 1, heredoc_end(shape, heredoc)):
                if chars[position] != "\n":
                    chars[position] = "x"
    return "".join(chars)


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
        if redirect := REDIRECT.match(token):
            if not redirect["target"]:
                next(values, None)
            continue
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
    value = os.path.expanduser(unquote(value))
    if os.name == "nt":
        value = DRIVE.sub(lambda drive: f"{drive.group(1)}:", value)
    return directory / Path(value)


def commit_targets(command, start):
    shape = masked(command)
    targets, previous = [], 0
    for match in COMMIT.finditer(shape):
        paths = [command[move.start("path"):move.end("path")] for move in CHDIR.finditer(shape[:match.start()])]
        paths += [command[option.start(1):option.end(1)]
                  for option in TARGET.finditer(shape, match.start(1), match.end(1))]
        directory = start
        for path in paths:
            directory = resolve(directory, path)
        if any(UNRESOLVED.search(path) for path in paths):
            directory = None
        staged = frozenset(stage["verb"] for stage in STAGES.finditer(shape[previous:match.start()]))
        targets.append((directory, commits_worktree(match["args"]), staged))
        previous = match.end()
    return targets


def git(root, *arguments, accept=(0,), stdin=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GitError("the gate ran out of time")
    result = subprocess.run(["git", "-C", str(root), *arguments], input=stdin, capture_output=True,
                            timeout=remaining)
    if result.returncode not in accept:
        raise GitError(f"git {arguments[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return result.stdout


def text(root, *arguments, accept=(0,)):
    return git(root, *arguments, accept=accept).decode("utf-8", "replace")


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


@cache
def tracked_skills(root):
    return [path for path in text(root, "ls-files", "--", ".agents").split("\n") if skill_path(path)]


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
    output = git(root, "cat-file", "--batch", stdin="".join(f"{revision}\n" for revision in revisions).encode("utf-8"))
    bodies, cursor = [], 0
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
    if not text(root, "rev-parse", "--verify", "--quiet", "HEAD", accept=(0, 1)).strip():
        return set()
    owners = packages(root)
    changed = text(root, "diff", "--cached", "--no-renames", "--name-only", "--diff-filter=DM", "HEAD").split("\n")
    if include_worktree:
        changed += text(root, "diff", "--no-renames", "--name-only", "--diff-filter=DM", "HEAD").split("\n")
    candidates = sorted({path for path in changed if skill_path(path)})
    if not candidates:
        return set()
    old = set()
    for path, body in zip(candidates, blobs(root, [f"HEAD:{path}" for path in candidates])):
        old |= qualified(path, body, owners)
    paths = tracked_skills(root)
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
    lines = text(root, *arguments, accept=(0, 1)).splitlines()
    return [line for line in lines if bounded.search(line.split(":", 2)[-1])]


def touches_skills(root):
    status = text(root, "status", "--porcelain", "--untracked-files=all", "--", ".agents")
    return any(skill_path(line[3:].split(" -> ")[-1].strip('"')) for line in status.splitlines())


def check(root, include_worktree, chained_staging):
    if chained_staging & {"rm", "mv"} and tracked_skills(root):
        return ("Clean cut: run `git rm`/`git mv` as its own call, then commit, so the gate can inspect "
                "what the commit removes.")
    if chained_staging and touches_skills(root):
        return ("Clean cut: skills under .agents have changed, so run `git add` as its own call, then "
                "commit, so the gate inspects exactly what the commit contains.")
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


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=True))
    return 0


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("tool_input"), dict):
        return 0
    tool_input = data["tool_input"]
    start = Path(str(tool_input.get("workdir") or data.get("cwd") or os.getcwd()))
    global deadline
    deadline = time.monotonic() + BUDGET_SECONDS
    seen = set()
    for directory, include_worktree, chained_staging in commit_targets(command_text(tool_input), start):
        if directory is None:
            session = repository_root(start, timeout=max(deadline - time.monotonic(), 0.1))
            if session is not None and selects_personal(session):
                return deny("Clean cut: this commit's directory comes from a variable or substitution. Use a "
                            "literal path for cd or git -C so the gate can inspect the commit.")
            continue
        if not directory.is_dir():
            continue
        root = repository_root(directory, timeout=max(deadline - time.monotonic(), 0.1))
        if root is None or not selects_personal(root) or (root, include_worktree, chained_staging) in seen:
            continue
        seen.add((root, include_worktree, chained_staging))
        try:
            reason = check(root, include_worktree, chained_staging)
        except Exception as error:
            reason = (f"Clean cut: the gate could not inspect this commit from {directory} ({error}). "
                      "Resolve the error and commit again.")
        if reason:
            return deny(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
