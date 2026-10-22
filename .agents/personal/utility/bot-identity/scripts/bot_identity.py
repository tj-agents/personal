#!/usr/bin/env python3
"""Run agent GitHub access as Tommy's GitHub App in personal repositories (Python 3.11+, needs openssl).

`token --owner X` prints an installation token, `credential get` is a git credential helper, `gh ...` wraps
the real gh, and `setup` installs the wrapper and the agent-only settings for Claude and Codex.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

API = "https://api.github.com"
AGENT_FLAG = "TJ_AGENT"
APP_ENV = "BOT_IDENTITY_APP"
UNAUTHENTICATED = "bot-identity-unauthenticated"
TIMEOUT_SECONDS = 30
TOKEN_MARGIN_SECONDS = 300
WINDOWS = os.name == "nt"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
GITHUB_URL = re.compile(r"(?<![\w.-])github\.com[:/]([A-Za-z0-9-]+)")
API_PATH = re.compile(r"(?:^|/)(?:repos|orgs|users)/([A-Za-z0-9-]+)")
REPOSITORY = re.compile(r"([A-Za-z0-9-]+)/[\w.-]+")
OWNER_FLAGS = ("-R", "--repo", "--owner")
AGENT_ONLY = (AGENT_FLAG, "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")
MANAGED = (AGENT_FLAG, "GH_TOKEN", "GH_CONFIG_DIR", "PATH", "Path")
CLEARED_HELPERS = ("https://*.github.com", "http://github.com", "http://*.github.com")
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


def gh_config_directory() -> Path:
    return store() / "gh-agent"


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
    if not WINDOWS:
        temporary.chmod(0o600)
    os.replace(temporary, path)


def installations(record: dict, refresh: bool = False, fetch=api, sign=app_jwt) -> dict[str, int]:
    path = store() / "tokens" / f"{record['slug']}-installations.json"
    if not refresh and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    found = {item["account"]["login"].lower(): item["id"] for item in fetch("/app/installations", sign(record))}
    write_private(path, found)
    return found


def installed(owners: list[str], record: dict, fetch=api, sign=app_jwt) -> dict[str, int]:
    wanted = {owner.lower() for owner in owners}
    known = installations(record, fetch=fetch, sign=sign)
    if not wanted <= known.keys():
        known = installations(record, refresh=True, fetch=fetch, sign=sign)
    return {owner: known[owner] for owner in wanted if owner in known}


def installation_token(owner: str, record: dict, now: float | None = None, fetch=api, sign=app_jwt) -> str | None:
    installation = installed([owner], record, fetch=fetch, sign=sign).get(owner.lower())
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


def owners_from_arguments(arguments: list[str]) -> list[str]:
    owners = [match.group(1) for argument in arguments for match in GITHUB_URL.finditer(argument)]
    for index, argument in enumerate(arguments):
        flag, equals, inline = argument.partition("=")
        if flag in OWNER_FLAGS:
            value = inline if equals else (arguments[index + 1] if index + 1 < len(arguments) else "")
        elif argument.startswith("-R") and len(argument) > 2:
            value = argument[2:]
        else:
            continue
        if value and not GITHUB_URL.search(value):
            owners.append(value.split("/")[0])
    if arguments[:1] == ["api"]:
        owners += [match.group(1) for argument in arguments[1:] for match in API_PATH.finditer(argument)]
    if arguments[:1] == ["repo"]:
        owners += [argument.split("/")[0] for argument in arguments[2:] if REPOSITORY.fullmatch(argument)]
    return owners


def owner_from_checkout(run=subprocess.run) -> str | None:
    try:
        result = run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                     check=False, creationflags=NO_WINDOW)
    except OSError:
        return None
    match = GITHUB_URL.search(result.stdout.strip()) if result.returncode == 0 else None
    return match.group(1) if match else None


def tommy_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key not in AGENT_ONLY and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}


def shim_directory() -> Path:
    return Path.home() / ".agents-state" / "bin" / "bot-identity"


def is_shim(entry: str) -> bool:
    return os.path.normcase(os.path.abspath(entry)) == os.path.normcase(str(shim_directory()))


def real_gh() -> str:
    path = os.pathsep.join(entry for entry in os.environ.get("PATH", "").split(os.pathsep)
                           if entry and not is_shim(entry))
    found = shutil.which("gh", path=path)
    if not found:
        raise IdentityError("the real gh CLI is not on PATH")
    return found


def agent_gh_environment(arguments: list[str], checkout_owner: str | None) -> dict[str, str]:
    if arguments[:1] == ["auth"] and arguments[1:2] != ["status"]:
        raise IdentityError("agents may run only `gh auth status`")
    owners = owners_from_arguments(arguments) + ([checkout_owner] if checkout_owner else [])
    environment = dict(os.environ)
    if not owners:
        return environment
    record = app_record()
    covered = installed(owners, record)
    app_owner = next((owner for owner in owners if owner.lower() in covered), None)
    if app_owner:
        token = installation_token(app_owner, record)
        if not token:
            raise IdentityError(f"could not get an installation token for {app_owner}")
        environment["GH_TOKEN"] = token
        return environment
    return environment if arguments[:1] == ["auth"] else tommy_environment()


def run_gh(arguments: list[str], run=subprocess.run, checkout=owner_from_checkout) -> int:
    if os.environ.get(AGENT_FLAG) != "1":
        return run([real_gh(), *arguments], check=False).returncode
    environment = agent_gh_environment(arguments, checkout())
    return run([real_gh(), *arguments], env=environment, check=False).returncode


def tommy_credential(fields: dict[str, str], run=subprocess.run) -> str:
    request = "".join(f"{key}={fields[key]}\n" for key in ("protocol", "host", "path")) + "\n"
    try:
        result = run(["git", "credential", "fill"], input=request, capture_output=True, text=True,
                     env={**tommy_environment(), "GIT_TERMINAL_PROMPT": "0"}, timeout=TIMEOUT_SECONDS, check=False,
                     creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode:
        return ""
    return "".join(f"{line}\n" for line in result.stdout.splitlines() if line.startswith(("username=", "password=")))


def credential(operation: str, stream=sys.stdin, out=sys.stdout, run=subprocess.run) -> int:
    if operation != "get":
        return 0
    fields = {}
    for line in stream:
        line = line.rstrip("\r\n")
        if not line:
            break
        key, _, value = line.partition("=")
        fields[key] = value
    owner = fields.get("path", "").split("/")[0]
    if fields.get("protocol") != "https" or fields.get("host", "").lower() != "github.com" or not owner:
        return 0
    try:
        record = app_record()
        if installed([owner], record):
            token = installation_token(owner, record)
            if token:
                out.write(f"username=x-access-token\npassword={token}\n")
            return 0
    except IdentityError:
        return 0
    out.write(tommy_credential(fields, run))
    return 0


def helper_command(script: Path) -> str:
    return f"!\"{Path(sys.executable).as_posix()}\" -B \"{script.as_posix()}\" credential"


def agent_path(path: str) -> str:
    return os.pathsep.join([str(shim_directory()), *(entry for entry in path.split(os.pathsep)
                                                     if entry and not is_shim(entry))])


def agent_environment(script: Path, path: str) -> dict[str, str]:
    entries = [("credential.https://github.com.useHttpPath", "true"),
               ("credential.https://github.com.helper", ""),
               ("credential.https://github.com.helper", helper_command(script)),
               *((f"credential.{url}.helper", "") for url in CLEARED_HELPERS)]
    environment = {AGENT_FLAG: "1", "GH_TOKEN": UNAUTHENTICATED, "GH_CONFIG_DIR": str(gh_config_directory()),
                   "GIT_CONFIG_COUNT": str(len(entries))}
    for index, (key, value) in enumerate(entries):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    # Windows names are case-insensitive, yet a host can keep Path and PATH apart; set both so neither stays stale.
    for key in ("PATH", "Path") if WINDOWS else ("PATH",):
        environment[key] = agent_path(path)
    return environment


def update_claude(path: Path, environment: dict[str, str]) -> None:
    settings = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    if not isinstance(settings, dict):
        raise IdentityError(f"{path} does not contain a JSON object")
    current = settings.setdefault("env", {})
    for key in [key for key in current if key.startswith("GIT_CONFIG_") or key in MANAGED]:
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
    managed = re.compile(rf"^\s*(GIT_CONFIG_\w+|{'|'.join(MANAGED)})\s*=")
    body = [line for line in lines[start:end] if not managed.match(line)]
    while body and not body[-1].strip():
        body.pop()
    body += [f"{key} = {toml_string(value)}" for key, value in environment.items()]
    lines = lines[:start] + body + ([""] if end < len(lines) else []) + lines[end:]
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".pre-bot-identity.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def script_launcher() -> bytes:
    import ensurepip
    wheels = sorted((Path(ensurepip.__file__).parent / "_bundled").glob("pip-*.whl"))
    if not wheels:
        raise IdentityError("this Python has no bundled pip wheel, whose script launcher becomes gh.exe")
    name = "t64-arm.exe" if platform.machine().lower() in ("arm64", "aarch64") else "t64.exe"
    with zipfile.ZipFile(wheels[-1]) as wheel:
        return wheel.read(f"pip/_vendor/distlib/{name}")


def windows_executable(script: Path) -> bytes:
    main = (f"import runpy, sys\nsys.argv = [{str(script)!r}, 'gh', *sys.argv[1:]]\n"
            f"runpy.run_path({str(script)!r}, run_name='__main__')\n")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr("__main__.py", main)
    return script_launcher() + f'#!"{sys.executable}" -B\n'.encode() + archive.getvalue()


def install_shims(source: Path) -> Path:
    directory = shim_directory()
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / source.name
    shutil.copyfile(source, script)
    if WINDOWS:
        (directory / "gh.exe").write_bytes(windows_executable(script))
        for retired in ("gh", "gh.cmd"):
            (directory / retired).unlink(missing_ok=True)
        return script
    python = Path(sys.executable)
    (directory / "gh").write_text(f"#!/bin/sh\nexec \"{python.as_posix()}\" -B \"{script.as_posix()}\" gh \"$@\"\n",
                                  encoding="utf-8", newline="\n")
    (directory / "gh").chmod(0o755)
    return script


def remove_user_path(directory: Path) -> bool:
    if WINDOWS:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                return False
            entries = [entry for entry in current.split(";") if entry]
            kept = [entry for entry in entries if os.path.normcase(entry) != os.path.normcase(str(directory))]
            if kept == entries:
                return False
            winreg.SetValueEx(key, "Path", 0, kind, ";".join(kept))
        return True
    profile = Path.home() / ".profile"
    line = f'export PATH="{directory}:$PATH"  # bot-identity'
    text = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    if line not in text.splitlines():
        return False
    profile.write_text("".join(kept + "\n" for kept in text.splitlines() if kept != line), encoding="utf-8")
    return True


def setup() -> None:
    app_record()
    script = install_shims(Path(__file__).resolve())
    gh_config_directory().mkdir(parents=True, exist_ok=True)
    environment = agent_environment(script, os.environ.get("PATH", ""))
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    update_claude(claude, environment)
    update_codex(codex, environment)
    if remove_user_path(shim_directory()):
        print(f"Removed {shim_directory()} from your user PATH; only agent sessions put it first")
    print("Agents now use the GitHub App in its installed accounts; restart Claude and Codex to apply, "
          "and re-run setup after changing PATH")


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
        arguments = parser.parse_args(argv)
        if arguments.command == "credential":
            return credential(arguments.operation)
        if arguments.command == "setup":
            setup()
            return 0
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
