#!/usr/bin/env python3
"""Run agent GitHub access as Tommy's GitHub App in personal repositories (Python 3.11+, needs openssl).

`token --owner X` prints an installation token, `credential get` is a git credential helper, `gh ...` wraps
the real gh, and `setup` installs the wrapper and the agent-only settings for Claude and Codex.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

API = "https://api.github.com"
AGENT_FLAG = "TJ_AGENT"
APP_ENV = "BOT_IDENTITY_APP"
TIMEOUT_SECONDS = 30
TOKEN_MARGIN_SECONDS = 300
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SYNC_TIMEOUT_SECONDS = 1800
TASK_NAME = "tj-agents merge gates"
CRON_MARKER = "# tj-agents-merge-gates"
MERGE_POLICY = Path(".agents", "github-actions", "utility", "merge-policy", "scripts", "merge_policy.py")
MCP_DENY = (
    "mcp__github__merge_pull_request",
    "mcp__github__create_pull_request",
    "mcp__github__pull_request_review_write",
    "mcp__github__push_files",
    "mcp__github__create_or_update_file",
    "mcp__github__delete_file",
    "mcp__github__create_branch",
    "mcp__github__update_pull_request_branch",
)


class IdentityError(Exception):
    pass


def store() -> Path:
    return Path.home() / ".agents-state" / "github-app"


def app_record() -> dict:
    named = os.environ.get(APP_ENV)
    records = [store() / f"{named}.json"] if named else sorted(store().glob("*.json"))
    records = [path for path in records if path.is_file()]
    if len(records) != 1:
        raise IdentityError(f"expected one GitHub App record in {store()}, found {len(records)}; set {APP_ENV}")
    return json.loads(records[0].read_text(encoding="utf-8"))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_jwt(record: dict, now: float | None = None, run=subprocess.run) -> str:
    now = int(now if now is not None else time.time())
    signing = f"{b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())}." \
              f"{b64(json.dumps({'iat': now - 60, 'exp': now + 540, 'iss': record['client_id']}).encode())}"
    openssl = shutil.which("openssl")
    if not openssl:
        raise IdentityError("openssl is not on PATH")
    result = run([openssl, "dgst", "-sha256", "-sign", record["key"]], input=signing.encode(), capture_output=True,
                 timeout=TIMEOUT_SECONDS, check=False, creationflags=NO_WINDOW)
    if result.returncode:
        raise IdentityError(f"openssl could not sign with {record['key']}")
    return f"{signing}.{b64(result.stdout)}"


def api(path: str, bearer: str, method: str = "GET") -> object:
    request = urllib.request.Request(f"{API}{path}", method=method, headers={
        "Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except OSError as error:
        raise IdentityError(f"GitHub {method} {path} failed: {error}") from error


def write_private(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".next")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)


def installations(record: dict, refresh: bool = False, fetch=api, sign=app_jwt) -> dict[str, int]:
    path = store() / "tokens" / f"{record['slug']}-installations.json"
    if not refresh and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    found = {item["account"]["login"].lower(): item["id"] for item in fetch("/app/installations", sign(record))}
    write_private(path, found)
    return found


def installed_owner(owner: str | None, record: dict, fetch=api, sign=app_jwt) -> int | None:
    if not owner:
        return None
    owner = owner.lower()
    known = installations(record, fetch=fetch, sign=sign)
    if owner not in known:
        known = installations(record, refresh=True, fetch=fetch, sign=sign)
    return known.get(owner)


def installation_token(owner: str, record: dict, now: float | None = None, fetch=api, sign=app_jwt) -> str | None:
    installation = installed_owner(owner, record, fetch=fetch, sign=sign)
    if installation is None:
        return None
    now = now if now is not None else time.time()
    path = store() / "tokens" / f"{record['slug']}-{owner.lower()}.json"
    if path.is_file():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("expires", 0) - TOKEN_MARGIN_SECONDS > now:
            return cached["token"]
    issued = fetch(f"/app/installations/{installation}/access_tokens", sign(record), method="POST")
    expires = datetime.fromisoformat(issued["expires_at"].replace("Z", "+00:00")).timestamp()
    write_private(path, {"token": issued["token"], "expires": expires})
    return issued["token"]


def owner_from_url(url: str) -> str | None:
    match = re.match(r"(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/", url)
    return match.group(1) if match else None


def owner_from_arguments(arguments: list[str]) -> str | None:
    for index, argument in enumerate(arguments):
        value = None
        if argument in ("-R", "--repo") and index + 1 < len(arguments):
            value = arguments[index + 1]
        elif argument.startswith("--repo="):
            value = argument.split("=", 1)[1]
        elif argument.startswith("-R") and len(argument) > 2:
            value = argument[2:]
        if value:
            value = owner_from_url(value + "/") or value
            return value.split("/")[0]
    if arguments[:1] == ["api"]:
        for argument in arguments[1:]:
            match = re.match(r"/?repos/([^/]+)/", argument)
            if match:
                return match.group(1)
    return None


def owner_from_checkout(run=subprocess.run) -> str | None:
    try:
        result = run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                     check=False, creationflags=NO_WINDOW)
    except OSError:
        return None
    return owner_from_url(result.stdout.strip()) if result.returncode == 0 else None


def shim_directory() -> Path:
    return Path.home() / ".agents-state" / "bin" / "bot-identity"


def real_gh() -> str:
    shim = os.path.normcase(str(shim_directory()))
    path = os.pathsep.join(entry for entry in os.environ.get("PATH", "").split(os.pathsep)
                           if entry and os.path.normcase(os.path.abspath(entry)) != shim)
    found = shutil.which("gh", path=path)
    if not found:
        raise IdentityError("the real gh CLI is not on PATH")
    return found


def run_gh(arguments: list[str]) -> int:
    environment = dict(os.environ)
    if environment.get(AGENT_FLAG) == "1":
        owner = owner_from_arguments(arguments) or owner_from_checkout()
        token = installation_token(owner, app_record()) if owner else None
        if token:
            environment["GH_TOKEN"] = token
    return subprocess.run([real_gh(), *arguments], env=environment, check=False).returncode


def credential(operation: str, stream=sys.stdin, out=sys.stdout) -> int:
    if operation != "get":
        return 0
    fields = {}
    for line in stream:
        line = line.rstrip("\r\n")
        if not line:
            break
        key, _, value = line.partition("=")
        fields[key] = value
    if fields.get("protocol") != "https" or fields.get("host") != "github.com" or not fields.get("path"):
        return 0
    owner = fields["path"].split("/")[0]
    try:
        token = installation_token(owner, app_record())
    except IdentityError:
        return 0
    if token:
        out.write(f"username=x-access-token\npassword={token}\n")
    return 0


def helper_command(script: Path) -> str:
    return f"!\"{Path(sys.executable).as_posix()}\" -B \"{script.as_posix()}\" credential"


def agent_environment(script: Path, fallback_helpers: list[str]) -> dict[str, str]:
    entries = [("credential.https://github.com.useHttpPath", "true"),
               ("credential.https://github.com.helper", ""),
               ("credential.https://github.com.helper", helper_command(script))]
    entries += [("credential.https://github.com.helper", helper) for helper in fallback_helpers]
    environment = {AGENT_FLAG: "1", "GIT_CONFIG_COUNT": str(len(entries))}
    for index, (key, value) in enumerate(entries):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment


def configured_helpers(run=subprocess.run) -> list[str]:
    result = run(["git", "config", "--get-all", "credential.helper"], capture_output=True, text=True,
                 timeout=TIMEOUT_SECONDS, check=False, creationflags=NO_WINDOW)
    helpers = []
    for helper in result.stdout.splitlines():
        helpers = [] if not helper.strip() else helpers + [helper.strip()]
    return helpers


def update_claude(path: Path, environment: dict[str, str]) -> None:
    settings = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    if not isinstance(settings, dict):
        raise IdentityError(f"{path} does not contain a JSON object")
    current = settings.setdefault("env", {})
    for key in [key for key in current if key.startswith("GIT_CONFIG_")]:
        del current[key]
    current.update(environment)
    permissions = settings.setdefault("permissions", {})
    permissions["deny"] = sorted(set(permissions.get("deny") or []) | set(MCP_DENY))
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".pre-bot-identity.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def toml_string(value: str) -> str:
    return json.dumps(value)


def update_codex(path: Path, environment: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    header = "[shell_environment_policy.set]"
    if header not in [line.strip() for line in lines]:
        lines += ["", header]
    start = [line.strip() for line in lines].index(header) + 1
    end = next((index for index in range(start, len(lines)) if lines[index].lstrip().startswith("[")), len(lines))
    managed = re.compile(rf"^\s*(GIT_CONFIG_\w+|{AGENT_FLAG})\s*=")
    body = [line for line in lines[start:end] if not managed.match(line)]
    while body and not body[-1].strip():
        body.pop()
    body += [f"{key} = {toml_string(value)}" for key, value in environment.items()]
    lines = lines[:start] + body + ([""] if end < len(lines) else []) + lines[end:]
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".pre-bot-identity.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def install_shims(source: Path) -> Path:
    directory = shim_directory()
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / source.name
    shutil.copyfile(source, script)
    python = Path(sys.executable)
    (directory / "gh").write_text(f"#!/bin/sh\nexec \"{python.as_posix()}\" -B \"{script.as_posix()}\" gh \"$@\"\n",
                                  encoding="utf-8", newline="\n")
    if os.name == "nt":
        (directory / "gh.cmd").write_text(f"@\"{python}\" -B \"{script}\" gh %*\r\n", encoding="utf-8")
    else:
        (directory / "gh").chmod(0o755)
    return script


def prepend_user_path(directory: Path) -> bool:
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current, kind = "", winreg.REG_EXPAND_SZ
            entries = [entry for entry in current.split(";") if entry]
            if any(os.path.normcase(entry) == os.path.normcase(str(directory)) for entry in entries):
                return False
            winreg.SetValueEx(key, "Path", 0, kind, ";".join([str(directory), *entries]))
        return True
    profile = Path.home() / ".profile"
    line = f'export PATH="{directory}:$PATH"  # bot-identity'
    text = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    if line in text:
        return False
    profile.write_text(text + ("" if text.endswith("\n") or not text else "\n") + line + "\n", encoding="utf-8")
    return True


def merge_policy_script() -> Path:
    roots = [Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "plugins" / "cache",
             Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "plugins" / "cache"]
    found = [path for root in roots for path in root.glob(f"*/github-actions/*/{MERGE_POLICY.as_posix()}")]
    if not found:
        raise IdentityError("the github-actions plugin, which ships merge_policy.py, is not installed")
    return max(found, key=lambda path: path.stat().st_mtime)


def merge_gates(record: dict, run=subprocess.run) -> int:
    owners = sorted(installations(record, refresh=True))
    if not owners:
        raise IdentityError("the GitHub App is not installed on any account")
    command = [console_python(), "-B", str(merge_policy_script()), "sync"]
    for owner in owners:
        command += ["--owner", owner]
    environment = {key: value for key, value in os.environ.items() if key != AGENT_FLAG}
    return run(command, env=environment, timeout=SYNC_TIMEOUT_SECONDS, check=False,
               creationflags=NO_WINDOW).returncode


def console_python() -> str:
    executable = Path(sys.executable)
    console = executable.with_name("python.exe")
    return str(console) if executable.name.lower() == "pythonw.exe" and console.is_file() else sys.executable


def windowless_python() -> str:
    executable = Path(sys.executable)
    hidden = executable.with_name("pythonw.exe")
    return str(hidden) if os.name == "nt" and hidden.is_file() else sys.executable


def schedule_merge_gates(script: Path, run=subprocess.run) -> None:
    command = f'"{windowless_python()}" -B "{script}" merge-gates'
    if os.name == "nt":
        run(["schtasks", "/create", "/f", "/tn", TASK_NAME, "/sc", "hourly", "/tr", command], capture_output=True,
            text=True, timeout=TIMEOUT_SECONDS, check=True, creationflags=NO_WINDOW)
        return
    current = run(["crontab", "-l"], capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
    lines = [line for line in current.stdout.splitlines() if CRON_MARKER not in line]
    lines.append(f"17 * * * * {command} >/dev/null 2>&1 {CRON_MARKER}")
    run(["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        check=True)


def setup() -> None:
    app_record()
    script = install_shims(Path(__file__).resolve())
    environment = agent_environment(script, configured_helpers())
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    update_claude(claude, environment)
    update_codex(codex, environment)
    if prepend_user_path(shim_directory()):
        print(f"Added {shim_directory()} to the front of your user PATH")
    schedule_merge_gates(script)
    print(f"Scheduled '{TASK_NAME}' hourly: repositories that declare a merge gate get it on GitHub")
    print("Agents now use the GitHub App in its installed accounts; restart Claude and Codex to apply")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["gh"]:
            return run_gh(argv[1:])
        parser = argparse.ArgumentParser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("token").add_argument("--owner", required=True)
        commands.add_parser("credential").add_argument("operation")
        commands.add_parser("setup")
        commands.add_parser("merge-gates")
        arguments = parser.parse_args(argv)
        if arguments.command == "credential":
            return credential(arguments.operation)
        if arguments.command == "setup":
            setup()
            return 0
        if arguments.command == "merge-gates":
            return merge_gates(app_record())
        token = installation_token(arguments.owner, app_record())
        if not token:
            raise IdentityError(f"the GitHub App is not installed on {arguments.owner}")
        print(token)
        return 0
    except IdentityError as error:
        print(f"bot_identity: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
