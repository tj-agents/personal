#!/usr/bin/env python3
"""Run agent GitHub access as the configured GitHub App in personal repositories (Python 3.12+, needs openssl).

`token --owner X` prints an installation token, `credential get` is a git credential helper, `gh ...` wraps
the real gh and `setup` installs the wrapper, the agent-only settings for Claude and Codex and the human's `tj approve`.
`converge` replaces stale wrapper and `tj approve` script copies with this plugin's.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
import time
import urllib.request
import urllib.error
import webbrowser
import zipfile
import stat

import onboarding

API = "https://api.github.com"
AGENT_FLAG = "TJ_AGENT"
TOKEN_FINGERPRINT = "TJ_BOT_TOKEN_SHA256"
UNAUTHENTICATED = "bot-identity-unauthenticated"
TIMEOUT_SECONDS = 30
TOKEN_MARGIN_SECONDS = 300
ENROLLMENT_SECONDS = 600
MAX_ENROLLMENT_BYTES = 32 * 1024
FORBIDDEN_WRITE_PERMISSIONS = ("administration",)
WINDOWS = os.name == "nt"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
GITHUB_URL = re.compile(r"(?<![\w.-])github\.com[:/]([A-Za-z0-9-]+)")
API_PATH = re.compile(r"(?:^|/)(?:repos|orgs|users)/([A-Za-z0-9-]+)")
REPOSITORY = re.compile(r"([A-Za-z0-9-]+)/[\w.-]+")
PULL_REQUEST = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/[\w.-]+/pull/\d+")
UNREVIEWABLE_CREATE = ("-d", "--draft", "-w", "--web", "--dry-run")
NATIVE_SESSIONS = (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_THREAD_ID"))
ITEM_TIMEOUT_SECONDS = 120
PR_VALUE_FLAGS = ("-t", "--title", "-b", "--body", "-F", "--body-file", "-B", "--base", "-H", "--head", "-a",
                  "--assignee", "-l", "--label", "-m", "--milestone", "-p", "--project", "-r", "--reviewer", "-R",
                  "--repo", "-T", "--template", "--recover")
OWNER_FLAGS = ("-R", "--repo", "--owner")
PAYLOAD_FLAGS = (*[flag for flag in PR_VALUE_FLAGS if flag.startswith("--")], "--field", "--raw-field",
                 "--input", "--header", "--jq", "--search", "--method", "--cache", "--json", "--limit",
                 "-q", "-t",
                 "--preview", "--branch", "--subject", "--author-email", "--match-head-commit", "--description",
                 "--homepage", "--gitignore", "--license", "--source", "--team", "--color", "--reason",
                 "--add-assignee", "--add-label", "--add-project", "--add-reviewer", "--remove-assignee",
                 "--remove-label", "--remove-project", "--remove-reviewer")
COMMAND_PAYLOAD_FLAGS = {
    ("api",): ("-F", "-f", "-H", "-q", "-X", "-p", "-t"),
    ("pr", "create"): ("-a", "-B", "-b", "-F", "-H", "-l", "-m", "-p", "-r", "-T", "-t"),
    ("pr", "edit"): ("-B", "-b", "-F", "-m", "-t"),
    ("pr", "merge"): ("-A", "-b", "-F", "-t"),
    ("pr", "review"): ("-b", "-F"),
    ("pr", "checkout"): ("-b",),
    ("pr", "comment"): ("-b", "-F"),
    ("pr", "close"): ("-c", "--comment"),
    ("pr", "reopen"): ("-c", "--comment"),
    ("pr", "view"): ("-q", "-t"),
    ("pr", "list"): ("-a", "-A", "-B", "-H", "-l", "-L", "-S", "-s", "-q", "-t"),
    ("pr", "checks"): ("-q", "-t"),
    ("issue", "create"): ("-a", "-b", "-F", "-l", "-m", "-p", "-T", "-t"),
    ("issue", "edit"): ("-b", "-F", "-m", "-t"),
    ("issue", "comment"): ("-b", "-F"),
    ("issue", "close"): ("-c", "-r", "--comment"),
    ("issue", "reopen"): ("-c", "--comment"),
    ("issue", "view"): ("-q", "-t"),
    ("issue", "list"): ("-a", "-A", "-l", "-L", "-S", "-s", "-m", "-q", "-t"),
    ("repo", "create"): ("-d", "-g", "-h", "-l", "-r", "-s", "-t", "-p", "--remote"),
    ("repo", "clone"): ("-u", "--upstream-remote-name"),
    ("repo", "fork"): ("--remote-name", "--org", "--fork-name"),
    ("repo", "edit"): ("-d", "-h"),
    ("repo", "view"): ("-q", "-t"),
}
AGENT_ONLY = (AGENT_FLAG, "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")
MANAGED = (AGENT_FLAG, "GH_TOKEN", "GH_CONFIG_DIR", "PATH", "Path")
CLEARED_HELPERS = ("https://*.github.com", "http://github.com", "http://*.github.com")
AGENT_DENY = (
    "mcp__github__merge_pull_request",
    "mcp__github__create_pull_request",
    "mcp__github__pull_request_review_write",
    "mcp__github__push_files",
    "mcp__github__create_or_update_file",
    "mcp__github__delete_file",
    "mcp__github__create_branch",
    "mcp__github__update_pull_request_branch",
    "Bash(tj approve:*)",
    "Bash(tj-approve:*)",
)


class IdentityError(Exception):
    pass


class KeyVerificationError(IdentityError):
    pass


class OnboardingRequired(IdentityError):
    pass


class GitHubError(IdentityError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HandoverError(IdentityError):
    pass


def store() -> Path:
    return Path.home() / ".agents-state" / "github-app"


def validate_identity(value: object) -> dict:
    fields = {"schema_version", "app", "reviewer", "accounts", "permissions", "key"}
    if not isinstance(value, dict) or set(value) != fields or (type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise IdentityError("the local GitHub identity configuration is invalid")
    app = value["app"]
    if not isinstance(app, dict) or set(app) != {"id", "client_id", "slug", "owner", "owner_type"} or \
            app["owner_type"] not in ("User", "Organization") or type(app["id"]) is not int or app["id"] <= 0 or any(
                not isinstance(app[name], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", app[name])
                for name in ("client_id", "slug", "owner")):
        raise IdentityError("the configured GitHub App descriptor is invalid")
    reviewer, accounts = value["reviewer"], value["accounts"]
    if not isinstance(reviewer, str) or not re.fullmatch(r"[A-Za-z0-9-]+", reviewer) or \
            not isinstance(accounts, list) or not accounts or any(
                not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9-]+", owner) for owner in accounts) or \
            len({owner.lower() for owner in accounts}) != len(accounts):
        raise IdentityError("configure a human reviewer and distinct permitted GitHub accounts")
    permissions = value["permissions"]
    if not isinstance(permissions, dict) or any(
            not isinstance(owner, str) or owner.lower() not in {account.lower() for account in accounts}
            or not isinstance(required, dict) or any(
                not isinstance(name, str) or not re.fullmatch(r"[a-z_]+", name) or level not in ("read", "write")
                for name, level in required.items()) for owner, required in permissions.items()):
        raise IdentityError("the configured account permissions are invalid")
    key = value["key"]
    if key is not None and (not isinstance(key, str) or not Path(key).is_absolute() or
                            Path(key).parent != store() or Path(key).name != f"{app['slug']}.pem"):
        raise IdentityError("the local GitHub App key location is invalid")
    return value


def identity_config() -> dict:
    if is_reparse(store()):
        raise IdentityError("the GitHub App enrollment directory is unsafe")
    path = store() / "identity.json"
    if not path.exists():
        raise OnboardingRequired("identity setup required: run `bot_identity.py setup --onboard`")
    safe_existing_file(path)
    require_private_permissions(store(), directory=True)
    require_private_permissions(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityError("the local GitHub identity configuration is invalid") from error
    return validate_identity(value)


def configure_identity(config: dict) -> None:
    config = validate_identity(config)
    try:
        previous = identity_config()
    except OnboardingRequired:
        previous = None
    if previous is not None and previous["key"] is not None:
        if previous["app"] != config["app"]:
            raise IdentityError("a different GitHub App is already enrolled; preserve its enrollment")
        if config["key"] is None:
            config = {**config, "key": previous["key"]}
    if previous != config:
        write_private(store() / "identity.json", config)


def app_descriptor() -> dict:
    return identity_config()["app"]


def required_owners() -> tuple[str, ...]:
    return tuple(owner.lower() for owner in identity_config()["accounts"])


def required_permissions(owner: str) -> dict[str, str]:
    return next((required for account, required in identity_config()["permissions"].items()
                 if account.lower() == owner.lower()), {})


def gh_config_directory() -> Path:
    return store() / "gh-agent"


def is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(os.lstat(path).st_file_attributes & 0x400)
    except FileNotFoundError:
        return False
    except AttributeError:
        return path.is_symlink()


def safe_existing_file(path: Path) -> None:
    if not path.is_file() or is_reparse(path):
        raise IdentityError("the local GitHub App enrollment is unsafe or incomplete")


def require_private_permissions(path: Path, directory: bool = False) -> None:
    """Read-only private-store validation for setup --check."""
    if WINDOWS:
        protect(path, directory=directory, check=True)
        return
    expected = 0o700 if directory else 0o600
    if stat.S_IMODE(path.stat().st_mode) != expected:
        raise IdentityError("the local GitHub App enrollment permissions are unsafe")


def app_record() -> dict:
    config = identity_config()
    if config["key"] is None:
        raise OnboardingRequired("enrollment required: run `bot_identity.py setup --onboard`")
    key = Path(config["key"])
    if not key.exists():
        raise OnboardingRequired("enrollment key is missing: run `bot_identity.py setup --onboard`")
    safe_existing_file(key)
    require_private_permissions(key)
    return {**config["app"], "key": str(key)}


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
        raise KeyVerificationError("openssl could not sign with the enrolled GitHub App key")
    return f"{signing}.{b64(result.stdout)}"


def api(path: str, bearer: str | None, method: str = "GET") -> object:
    headers = {"Accept": "application/vnd.github+json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(f"{API}{path}", method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise GitHubError(f"GitHub {method} {path} failed (HTTP {error.code})", error.code) from error
    except OSError as error:
        raise GitHubError(f"GitHub {method} {path} could not be reached") from error


def validate_remote_app(record: dict, fetch=api, sign=app_jwt) -> dict:
    actual = fetch("/app", sign(record))
    descriptor = app_descriptor()
    if not isinstance(actual, dict) or actual.get("id") != descriptor["id"] or \
            actual.get("client_id") != descriptor["client_id"] or actual.get("slug") != descriptor["slug"] or \
            actual.get("owner", {}).get("login", "").lower() != descriptor["owner"].lower() or \
            actual.get("owner", {}).get("type") != descriptor["owner_type"]:
        raise KeyVerificationError("the enrolled key does not authenticate the configured GitHub App")
    return actual


def app_settings_url(descriptor: dict) -> str:
    if descriptor["owner_type"] == "Organization":
        return f"https://github.com/organizations/{descriptor['owner']}/settings/apps/{descriptor['slug']}"
    return f"https://github.com/settings/apps/{descriptor['slug']}"


def installation_settings_url(installation: dict) -> str:
    account = installation.get("account", {})
    login = account.get("login", "")
    if installation.get("target_type") == "User":
        return f"https://github.com/settings/installations/{installation['id']}"
    return f"https://github.com/organizations/{login}/settings/installations/{installation['id']}"


def capability_error(subject: str, permissions: object, required: dict[str, str], url: str) -> None:
    available = permissions if isinstance(permissions, dict) else {}
    forbidden = [name for name in FORBIDDEN_WRITE_PERMISSIONS if available.get(name) == "write"]
    if forbidden:
        raise IdentityError(f"the {subject} grants forbidden {forbidden[0]}:write; remove it at {url}")
    for name, level in required.items():
        if available.get(name) != level:
            raise IdentityError(f"the {subject} does not grant {name}:{level}; update it at {url}")


def validate_app_capabilities(actual: dict) -> None:
    descriptor = app_descriptor()
    for owner in required_owners():
        capability_error("configured GitHub App", actual.get("permissions"),
                         required_permissions(owner), app_settings_url(descriptor))


def remote_installations(record: dict, fetch=api, sign=app_jwt) -> dict[str, dict]:
    values = fetch("/app/installations", sign(record))
    if not isinstance(values, list):
        raise IdentityError("the configured GitHub App installations response is invalid")
    known = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int) or \
                not isinstance(item.get("account"), dict) or \
                not isinstance(item["account"].get("login"), str):
            raise IdentityError("the configured GitHub App installations response is invalid")
        known[item["account"]["login"].lower()] = item
    return known


def missing_required_installations(record: dict, fetch=api, sign=app_jwt) -> list[str]:
    known = remote_installations(record, fetch=fetch, sign=sign)
    return [owner for owner in required_owners() if owner not in known]


def verify_ready(record: dict, fetch=api, sign=app_jwt) -> None:
    actual = validate_remote_app(record, fetch=fetch, sign=sign)
    validate_app_capabilities(actual)
    known = remote_installations(record, fetch=fetch, sign=sign)
    missing = [owner for owner in required_owners() if owner not in known]
    if missing:
        raise OnboardingRequired("the configured GitHub App is not installed on: " + ", ".join(missing) +
                                 f"; install it at https://github.com/apps/{record['slug']}/installations/new")
    for owner in required_owners():
        installation = known[owner]
        capability_error(f"{owner} App installation", installation.get("permissions"),
                         required_permissions(owner), installation_settings_url(installation))


def persist_enrollment(key: bytes, fetch=api, sign=app_jwt) -> dict:
    """Verify a newly generated key before atomically making it the local enrollment."""
    if not key.startswith(b"-----BEGIN ") or b"PRIVATE KEY-----" not in key or len(key) > MAX_ENROLLMENT_BYTES:
        raise IdentityError("the selected file is not a supported GitHub App private key")
    descriptor = app_descriptor()
    directory = secure_store()
    pending = directory / f"{descriptor['slug']}.pending.pem"
    if is_reparse(pending):
        raise IdentityError("the pending GitHub App key location is unsafe")
    candidate = directory / ".replacement.pem" if pending.exists() else pending
    if is_reparse(candidate):
        raise IdentityError("the replacement GitHub App key location is unsafe")
    write_key(candidate, key)
    record = {**descriptor, "key": str(candidate)}
    try:
        validate_remote_app(record, fetch=fetch, sign=sign)
        destination = directory / f"{descriptor['slug']}.pem"
        if is_reparse(destination):
            raise IdentityError("the local GitHub App key location is unsafe")
        os.replace(candidate, destination)
        protect(destination)
        record["key"] = str(destination)
        configure_identity({**identity_config(), "key": str(destination)})
        if candidate != pending:
            pending.unlink(missing_ok=True)
        return record
    finally:
        if candidate != pending:
            candidate.unlink(missing_ok=True)


def onboard(open_browser=webbrowser.open, fetch=api, sign=app_jwt, clock=time.monotonic) -> None:
    def ready() -> None:
        verify_enrollment(fetch=fetch, sign=sign)

    try:
        onboarding.onboard(
            load=identity_config,
            configure=configure_identity,
            enroll=lambda key: persist_enrollment(key, fetch=fetch, sign=sign),
            ready=ready,
            error_type=IdentityError,
            open_browser=open_browser,
            clock=clock,
            discover=lambda: sorted(remote_installations(app_record(), fetch=fetch, sign=sign)),
        )
    except onboarding.OnboardingError as error:
        raise IdentityError(str(error)) from error


def protect(path: Path, directory: bool = False, *, check: bool = False) -> None:
    """Apply private local-state permissions without ever putting secret content in a command."""
    if WINDOWS:
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                                ctypes.POINTER(wintypes.DWORD))
        advapi.GetTokenInformation.restype = wintypes.BOOL
        advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD))
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        advapi.SetFileSecurityW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
        advapi.SetFileSecurityW.restype = wintypes.BOOL
        advapi.GetFileSecurityW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD))
        advapi.GetFileSecurityW.restype = wintypes.BOOL
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(wintypes.DWORD))
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel.LocalFree.restype = ctypes.c_void_p
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise IdentityError("could not identify the Windows user for GitHub App enrollment")
        try:
            size = wintypes.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not size.value:
                raise IdentityError("could not identify the Windows user for GitHub App enrollment")
            class SID_AND_ATTRIBUTES(ctypes.Structure):
                _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)):
                raise IdentityError("could not identify the Windows user for GitHub App enrollment")
            sid = ctypes.cast(buffer, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents.Sid
            sid_text = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
                raise IdentityError("could not identify the Windows user for GitHub App enrollment")
            try:
                inherit = "OICI" if directory else ""
                sddl = f"D:P(A;{inherit};FA;;;SY)(A;{inherit};FA;;;{sid_text.value})"
                security = ctypes.c_void_p()
                if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                        sddl, 1, ctypes.byref(security), None):
                    raise IdentityError("could not protect the local GitHub App enrollment")
                try:
                    if check:
                        needed = wintypes.DWORD()
                        advapi.GetFileSecurityW(str(path), 4, None, 0, ctypes.byref(needed))
                        actual = ctypes.create_string_buffer(needed.value)
                        if not needed.value or not advapi.GetFileSecurityW(
                                str(path), 4, actual, needed.value, ctypes.byref(needed)):
                            raise IdentityError("could not inspect the local GitHub App permissions")
                        expected_rendered = wintypes.LPWSTR()
                        actual_rendered = wintypes.LPWSTR()
                        try:
                            if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                                    security, 1, 4, ctypes.byref(expected_rendered), None) or \
                                    not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                                            actual, 1, 4, ctypes.byref(actual_rendered), None):
                                raise IdentityError("could not inspect the local GitHub App permissions")
                            expected = expected_rendered.value
                            value = actual_rendered.value
                            if "P" not in value.split("(", 1)[0][2:] or \
                                    sorted(value.split("(")[1:]) != sorted(expected.split("(")[1:]):
                                raise IdentityError("the local GitHub App enrollment permissions are unsafe")
                        finally:
                            if expected_rendered:
                                kernel.LocalFree(expected_rendered)
                            if actual_rendered:
                                kernel.LocalFree(actual_rendered)
                        return
                    # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
                    if not advapi.SetFileSecurityW(str(path), 0x80000004, security):
                        raise IdentityError("could not protect the local GitHub App enrollment")
                finally:
                    kernel.LocalFree(security)
            finally:
                kernel.LocalFree(sid_text)
        finally:
            kernel.CloseHandle(token)
    else:
        path.chmod(0o700 if directory else 0o600)


def private_parent(directory: Path) -> None:
    parent = directory.parent
    if parent.exists() and is_reparse(parent):
        raise IdentityError("the GitHub App enrollment directory is unsafe")
    parent.mkdir(parents=True, exist_ok=True)
    if is_reparse(parent):
        raise IdentityError("the GitHub App enrollment directory is unsafe")


def secure_store() -> Path:
    directory = store()
    private_parent(directory)
    if directory.exists() and is_reparse(directory):
        raise IdentityError("the GitHub App enrollment directory is unsafe")
    directory.mkdir(parents=True, exist_ok=True)
    protect(directory, directory=True)
    return directory


def private_temporary(path: Path) -> int:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        protect(path)
    except Exception:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    return fd


def write_private(path: Path, value: dict) -> None:
    directory = secure_store()
    try:
        path.relative_to(directory)
    except ValueError as error:
        raise IdentityError("refusing to write outside the GitHub App enrollment directory") from error
    if is_reparse(path):
        raise IdentityError("refusing to write through an unsafe GitHub App enrollment path")
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_reparse(path.parent):
        raise IdentityError("refusing to write through an unsafe GitHub App enrollment path")
    protect(path.parent, directory=True)
    temporary = path.with_name(path.name + ".next")
    if temporary.exists() or is_reparse(temporary):
        temporary.unlink(missing_ok=True)
    descriptor = private_temporary(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output)
        os.replace(temporary, path)
        protect(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_key(path: Path, value: bytes) -> None:
    directory = secure_store()
    if path.parent != directory or is_reparse(path):
        raise IdentityError("refusing to write through an unsafe GitHub App enrollment path")
    temporary = path.with_name(path.name + ".next")
    if temporary.exists() or is_reparse(temporary):
        temporary.unlink(missing_ok=True)
    fd = private_temporary(temporary)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(value)
        os.replace(temporary, path)
        protect(path)
    finally:
        temporary.unlink(missing_ok=True)


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
    if owner.lower() not in required_owners():
        raise IdentityError("the GitHub App is not authorized for that account")
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


def normalized_arguments(arguments: list[str]) -> list[str]:
    aliases = {("pr", "new"): "create", ("issue", "new"): "create", ("pr", "co"): "checkout",
               ("pr", "ls"): "list", ("issue", "ls"): "list", ("repo", "ls"): "list"}
    replacement = aliases.get(tuple(arguments[:2]))
    return [arguments[0], replacement, *arguments[2:]] if replacement else arguments


def argument_context(arguments: list[str]) -> tuple[list[str], str | None]:
    arguments = normalized_arguments(arguments)
    owners, positional = [], []
    hostname = None
    command = tuple(arguments[:1] if arguments[:1] == ["api"] else arguments[:2])
    payload_flags = (*PAYLOAD_FLAGS, *COMMAND_PAYLOAD_FLAGS.get(command, ()))
    remaining = iter(arguments)
    for argument in remaining:
        flag, equals, inline = argument.partition("=")
        if flag == "--hostname":
            hostname = inline if equals else next(remaining, "")
            continue
        elif flag in OWNER_FLAGS:
            value = inline if equals else next(remaining, "")
        elif argument.startswith("-R") and len(argument) > 2:
            value = argument[2:]
        elif flag in payload_flags:
            if not equals:
                next(remaining, None)
            continue
        else:
            if not argument.startswith("-"):
                positional.append(argument)
            continue
        if value:
            match = GITHUB_URL.search(value)
            owners.append(match.group(1) if match else value.split("/")[0])
    if arguments[:1] == ["api"]:
        targets = positional[1:2]
        owners += [match.group(1) for argument in targets for match in API_PATH.finditer(argument)]
    elif arguments[:1] == ["repo"]:
        targets = positional[2:3]
    elif arguments[:1] in (["pr"], ["issue"]) and arguments[1:2] != ["create"]:
        targets = positional[2:]
    else:
        targets = []
    owners += [match.group(1) for argument in targets for match in GITHUB_URL.finditer(argument)]
    if arguments[:1] == ["repo"]:
        owners += [argument.split("/")[0] for argument in targets if REPOSITORY.fullmatch(argument)]
    return owners, hostname


def owners_from_arguments(arguments: list[str]) -> list[str]:
    return argument_context(arguments)[0]


def owner_from_checkout(run=subprocess.run) -> str | None:
    try:
        result = run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                     check=False, creationflags=NO_WINDOW)
    except OSError:
        return None
    match = GITHUB_URL.search(result.stdout.strip()) if result.returncode == 0 else None
    return match.group(1) if match else None


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
    explicit_owners, hostname = argument_context(arguments)
    owners = (explicit_owners
              or owners_from_arguments(["-R", os.environ.get("GH_REPO", "")])
              or ([checkout_owner] if checkout_owner else []))
    if len({owner.lower() for owner in owners}) > 1:
        raise IdentityError("one GitHub command must target a single account")
    environment = dict(os.environ)
    if not owners:
        return environment
    protected = [owner for owner in owners if owner.lower() in required_owners()]
    if not protected:
        if arguments[:1] == ["auth"]:
            return environment
        raise IdentityError(f"{owners[0]} is not an account the GitHub App covers; agent sessions never use the human's credentials")
    hostname = hostname if hostname is not None else os.environ.get("GH_HOST") or "github.com"
    if hostname.lower() != "github.com":
        raise IdentityError("the Personal GitHub App is authorized only for github.com")
    record = app_record()
    covered = installed(protected, record) if protected else {}
    missing = [owner for owner in protected if owner.lower() not in covered]
    if missing:
        raise IdentityError("the configured GitHub App is not installed on " + ", ".join(missing))
    app_owner = next(owner for owner in owners if owner.lower() in covered)
    token = installation_token(app_owner, record)
    if not token:
        raise IdentityError(f"could not get an installation token for {app_owner}")
    environment["GH_TOKEN"] = token
    environment[TOKEN_FINGERPRINT] = hashlib.sha256(token.encode()).hexdigest()
    return environment


def option_names(arguments: list[str]) -> set[str]:
    names, rest = set(), iter(arguments)
    for argument in rest:
        if argument in PR_VALUE_FLAGS:
            next(rest, None)
        elif argument.startswith("-"):
            names.add(argument.partition("=")[0])
    return names


def awaits_approval(arguments: list[str]) -> bool:
    arguments = normalized_arguments(arguments)
    flags = option_names(arguments[2:])
    if arguments[:2] == ["pr", "create"]:
        return not flags & set(UNREVIEWABLE_CREATE)
    return arguments[:2] == ["pr", "ready"] and "--undo" not in flags


def ready_selector(arguments: list[str]) -> list[str]:
    selector, rest = [], iter(arguments[2:])
    for argument in rest:
        if argument in ("-R", "--repo"):
            selector += [argument, next(rest, "")]
        elif argument.startswith(("-R", "--repo=")) or not argument.startswith("-"):
            selector.append(argument)
    return selector


def tool(name: str) -> str:
    found = shutil.which(name) or shutil.which(name, path=str(tj_bin_directory()))
    if not found:
        raise IdentityError(f"{name} is not on PATH or in {tj_bin_directory()}")
    return found


def captured(
    run, command: list[str], environment: dict[str, str] | None = None,
    *, timeout_seconds: int = TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    try:
        return run(command, env=environment, check=False, capture_output=True, encoding="utf-8", errors="replace",
                   timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        label = " ".join([Path(command[0]).stem, *command[1:2]])
        raise IdentityError(f"{label} timed out after {timeout_seconds} seconds") from error


def reason(result: subprocess.CompletedProcess) -> str:
    lines = [line for line in (result.stderr or result.stdout or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else f"exited {result.returncode}"


def agent_store(arguments: list[str], run) -> dict | None:
    result = captured(run, [tool("agent-store"), *arguments])
    try:
        document = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise IdentityError(f"agent-store {arguments[0]} failed: {reason(result)}") from error
    if document.get("ok"):
        return document["data"]
    failure = document.get("error") or {}
    if failure.get("code") == "not-found":
        return None
    raise IdentityError(f"agent-store {arguments[0]} failed: {failure.get('message') or reason(result)}")


def linked(session: dict) -> list[str]:
    return [link["item"]["ref"] for link in session.get("links") or []]


def current_session(
    run, session_handle: str | None = None
) -> tuple[str | None, list[str]] | None:
    if session_handle is not None:
        data = agent_store(["show", session_handle], run)
        if data is None:
            raise IdentityError(
                f"unknown agent session {session_handle}; nothing approved"
            )
        session = data["session"]
        return session["session"], linked(session)
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


def link_session_item(url: str | None, run=subprocess.run) -> str:
    if url is None:
        raise HandoverError("gh did not report the pull request URL")
    session = current_session(run)
    if session is None:
        raise HandoverError("no agent-store session is registered for this agent")
    items = list(dict.fromkeys(session[1]))
    if not items:
        raise HandoverError("this session has no linked work item")
    if len(items) > 1:
        raise HandoverError(f"this session links several work items ({', '.join(items)}), so the PR was not linked")
    result = captured(run, [tool("tj"), "item", "--profile", "github", "link", items[0], url],
                      timeout_seconds=ITEM_TIMEOUT_SECONDS)
    if result.returncode:
        raise HandoverError(f"tj item link {items[0]} failed: {reason(result)}")
    return items[0]


def session_label() -> str:
    return next((f"{host}:{os.environ[variable]}" for host, variable in NATIVE_SESSIONS if os.environ.get(variable)),
                "<session>")


def hand_over(output: str, run=subprocess.run) -> None:
    match = PULL_REQUEST.search(output)
    url = match.group(0) if match and match.group(1).lower() in required_owners() else None
    try:
        item = link_session_item(url, run)
    except IdentityError as error:
        print(f"bot_identity: REQUIRED BEFORE HANDOVER: {url or 'this PR'} is not reachable by `tj approve`: "
              f"{error}. Do not give the human `! tj approve` yet: link this session to its work item with "
              f"`agent-store link --session {session_label()} --item <ref>` and the PR with "
              f"`tj item link <ref> {url or '<pr-url>'}`, then hand it over.", file=sys.stderr)
    else:
        print(f"bot_identity: linked {url} to {item}. REQUIRED IN YOUR REPLY: {url} awaits "
              f"{identity_config()['reviewer']}'s approval. Put the line `! tj approve` on the human's clipboard "
              f"with cli:clip, and make your reply include that link and that line; never run it yourself.",
              file=sys.stderr)


def run_gh(arguments: list[str], run=subprocess.run, checkout=owner_from_checkout) -> int:
    if os.environ.get(AGENT_FLAG) != "1":
        return run([real_gh(), *arguments], check=False).returncode
    environment = agent_gh_environment(arguments, checkout())
    app = environment.get("GH_TOKEN") not in (None, UNAUTHENTICATED)
    if not (app and awaits_approval(arguments)):
        return run([real_gh(), *arguments], env=environment, check=False).returncode
    if normalized_arguments(arguments)[1] == "create":
        result = run([real_gh(), *arguments], env=environment, check=False, stdout=subprocess.PIPE,
                     encoding="utf-8", errors="replace")
        output = result.stdout or ""
        sys.stdout.write(output)
        sys.stdout.flush()
    else:
        result = run([real_gh(), *arguments], env=environment, check=False)
        view = [real_gh(), "pr", "view", *ready_selector(arguments), "--json", "url", "--jq", ".url"]
        output = "" if result.returncode else run(view, env=environment, check=False, stdout=subprocess.PIPE,
                                                    encoding="utf-8", errors="replace").stdout or ""
    if result.returncode == 0:
        hand_over(output, run)
    return result.returncode


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
    owner = fields.get("path", "").split("/")[0]
    if fields.get("protocol") != "https" or fields.get("host", "").lower() != "github.com" or not owner:
        return 0
    try:
        if owner.lower() not in required_owners():
            print(f"bot_identity: {owner} is not an account the GitHub App covers; agent sessions never use the human's "
                  "credentials", file=sys.stderr)
            return 0
        record = app_record()
        if not installed([owner], record):
            return 0
        token = installation_token(owner, record)
        if token:
            out.write(f"username=x-access-token\npassword={token}\n")
    except IdentityError:
        return 0
    return 0


def helper_command(script: Path) -> str:
    return f"!{shlex.quote(Path(sys.executable).resolve().as_posix())} -B {shlex.quote(script.resolve().as_posix())} credential"


def _agent_git_config() -> Path:
    return store() / "gitconfig"


def _git_config_sources() -> list[Path]:
    configured = os.environ.get("GIT_CONFIG_GLOBAL")
    if configured is None:
        xdg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return [(xdg / "git" / "config").absolute(), Path.home() / ".gitconfig"]
    if not configured:
        return []
    path = Path(configured).expanduser().absolute()
    if os.path.normcase(str(path)) != os.path.normcase(str(_agent_git_config().absolute())):
        return [path]
    if not path.exists() and not is_reparse(path):
        raise IdentityError("the agent Git configuration is missing; run setup with the original GIT_CONFIG_GLOBAL, "
                            "or unset it if you originally used Git's default global files")
    safe_existing_file(path)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG_")}
    result = subprocess.run(["git", "config", "--file", str(path), "--no-includes", "--null", "--get-all", "include.path"],
                            env=environment, capture_output=True, text=True, encoding="utf-8",
                            timeout=TIMEOUT_SECONDS, check=False, creationflags=NO_WINDOW)
    if result.returncode not in (0, 1):
        raise IdentityError("the agent Git configuration is invalid; run setup")
    return [Path(value) for value in result.stdout.split("\0") if value]


def _git_config_content(script: Path) -> bytes:
    lines = ["# Managed by personal:bot-identity; contains no credentials."]
    for path in _git_config_sources():
        lines += ["[include]", f"\tpath = {json.dumps(path.as_posix(), ensure_ascii=False)}"]
    lines += ['[credential "https://github.com"]', "\tuseHttpPath = true", "\thelper =",
              f"\thelper = {json.dumps(helper_command(script), ensure_ascii=False)}"]
    for url in CLEARED_HELPERS:
        lines += [f'[credential "{url}"]', "\thelper ="]
    return ("\n".join(lines) + "\n").encode("utf-8")


def agent_path(path: str) -> str:
    entries = [str(shim_directory())]
    seen = set()
    for entry in path.split(os.pathsep):
        if not entry or is_shim(entry):
            continue
        if entry not in seen:
            seen.add(entry)
            entries.append(entry)
    return os.pathsep.join(entries)


def agent_environment(path: str) -> dict[str, str]:
    environment = {AGENT_FLAG: "1", "GH_TOKEN": UNAUTHENTICATED, "GH_CONFIG_DIR": str(gh_config_directory()),
                   "GIT_CONFIG_GLOBAL": str(_agent_git_config())}
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
    permissions["deny"] = sorted(set(permissions.get("deny") or []) | set(AGENT_DENY))
    content = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".pre-bot-identity.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
    content = "\n".join(lines) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".pre-bot-identity.bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def script_launcher() -> bytes:
    import ensurepip
    wheels = sorted((Path(ensurepip.__file__).parent / "_bundled").glob("pip-*.whl"))
    if not wheels:
        raise IdentityError("this Python has no bundled pip wheel, whose script launcher becomes gh.exe")
    name = "t64-arm.exe" if sysconfig.get_platform() == "win-arm64" else "t64.exe"
    with zipfile.ZipFile(wheels[-1]) as wheel:
        return wheel.read(f"pip/_vendor/distlib/{name}")


def windows_executable(script: Path) -> bytes:
    main = (f"import runpy, sys\nsys.path.insert(0, {str(script.parent)!r})\n"
            f"sys.argv = [{str(script)!r}, 'gh', *sys.argv[1:]]\n"
            f"runpy.run_path({str(script)!r}, run_name='__main__')\n")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr(zipfile.ZipInfo("__main__.py", (1980, 1, 1, 0, 0, 0)), main)
    return script_launcher() + f'#!"{sys.executable}" -B\n'.encode() + archive.getvalue()


def write_changed(path: Path, content: bytes, *, executable: bool = False) -> None:
    if is_reparse(path):
        raise IdentityError("refusing to replace a redirected identity launcher")
    if not path.is_file() or path.read_bytes() != content:
        path.write_bytes(content)
    if executable and not WINDOWS and path.stat().st_mode & 0o777 != 0o755:
        path.chmod(0o755)


def install_shims(source: Path) -> Path:
    directory = shim_directory()
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / source.name
    write_changed(script, source.read_bytes())
    for name in ("onboarding.py", "onboarding.html"):
        write_changed(script.with_name(name), Path(__file__).with_name(name).read_bytes())
    if WINDOWS:
        write_changed(directory / "gh.exe", windows_executable(script))
        for retired in ("gh", "gh.cmd"):
            (directory / retired).unlink(missing_ok=True)
        return script
    python = Path(sys.executable)
    write_changed(directory / "gh", f"#!/bin/sh\nexec \"{python.as_posix()}\" -B \"{script.as_posix()}\" gh \"$@\"\n".encode(), executable=True)
    return script


def approve_source() -> Path:
    source = Path(__file__).resolve()
    if source.parent == shim_directory().resolve():
        return source.with_name("approve.py")
    return Path(__file__).resolve().parents[2] / "approve" / "scripts" / "approve.py"


def tj_bin_directory() -> Path:
    if configured := os.environ.get("TJ_BIN_DIR"):
        return Path(configured).expanduser()
    if WINDOWS:
        return Path(os.environ["LOCALAPPDATA"]) / "Programs" / "tj"
    return Path.home() / ".local" / "bin"


def approve_launcher() -> tuple[Path, bytes]:
    script, python = shim_directory() / approve_source().name, Path(sys.executable)
    if WINDOWS:
        return tj_bin_directory() / "tj-approve.cmd", f'@"{python}" -B "{script}" %*\r\n'.encode()
    return tj_bin_directory() / "tj-approve", \
        f'#!/bin/sh\nexec "{python.as_posix()}" -B "{script.as_posix()}" "$@"\n'.encode()


def install_approve() -> Path:
    write_changed(shim_directory() / approve_source().name, approve_source().read_bytes())
    launcher, content = approve_launcher()
    launcher.parent.mkdir(parents=True, exist_ok=True)
    write_changed(launcher, content, executable=True)
    return launcher


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


def installed_script() -> Path:
    return shim_directory() / Path(__file__).name


def converge_shims() -> list[Path]:
    script = installed_script()
    if not script.is_file():
        return []
    copies = (
        (script, Path(__file__).resolve()),
        *((script.with_name(name), Path(__file__).with_name(name)) for name in ("onboarding.py", "onboarding.html")),
        (shim_directory() / approve_source().name, approve_source()),
    )
    replaced: list[Path] = []
    for target, source in copies:
        content = source.read_bytes()
        current = target.is_file() and not is_reparse(target)
        if current and target.read_bytes() == content:
            continue
        temporary = target.with_name(f"{target.name}.{os.getpid()}.next")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        replaced.append(target)
    return replaced


def claude_user_settings() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def codex_user_config() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"


def verify_host_setup() -> None:
    source = Path(__file__).resolve()
    script = installed_script()
    for path, expected in ((script, source.read_bytes()),
                           *((script.with_name(name), source.with_name(name).read_bytes())
                             for name in ("onboarding.py", "onboarding.html"))):
        safe_existing_file(path)
        if path.read_bytes() != expected:
            raise IdentityError("the installed GitHub App wrapper is stale; run setup")
    launcher = shim_directory() / ("gh.exe" if WINDOWS else "gh")
    safe_existing_file(launcher)
    expected_launcher = windows_executable(script) if WINDOWS else \
        f"#!/bin/sh\nexec \"{Path(sys.executable).as_posix()}\" -B \"{script.as_posix()}\" gh \"$@\"\n".encode()
    if launcher.read_bytes() != expected_launcher:
        raise IdentityError("the installed GitHub App wrapper is stale; run setup")
    approve, expected_approve = approve_launcher()
    for path, expected in ((shim_directory() / approve_source().name, approve_source().read_bytes()),
                           (approve, expected_approve)):
        if not path.is_file() or is_reparse(path) or path.read_bytes() != expected:
            raise IdentityError(f"`tj approve` is not installed at {path}; run setup")
    git_config = _agent_git_config()
    if not git_config.is_file() or is_reparse(git_config) or git_config.read_bytes() != _git_config_content(script):
        raise IdentityError("the agent Git configuration is stale; run setup")
    environment = agent_environment(os.environ.get("PATH", ""))
    claude = claude_user_settings()
    codex = codex_user_config()
    try:
        claude_settings = json.loads(claude.read_text(encoding="utf-8-sig"))
        claude_env = claude_settings["env"]
        claude_denials = claude_settings["permissions"]["deny"]
        import tomllib
        codex_env = tomllib.loads(codex.read_text(encoding="utf-8-sig"))["shell_environment_policy"]["set"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise IdentityError("agent host settings are missing; run setup") from error
    if not isinstance(claude_denials, list) or any(rule not in claude_denials for rule in AGENT_DENY):
        raise IdentityError("agent host write restrictions are missing; run setup")
    for settings in (claude_env, codex_env):
        if any(settings.get(key) != value for key, value in environment.items()) or any(
                (key.startswith("GIT_CONFIG_") or key in MANAGED) and key not in environment for key in settings):
            raise IdentityError("agent host settings are stale; run setup")


def human_reviewer(run=subprocess.run) -> str:
    environment = {name: value for name, value in os.environ.items()
                   if name not in AGENT_ONLY and not name.startswith("GIT_CONFIG_")}
    environment["GH_HOST"] = "github.com"
    result = run([real_gh(), "api", "user", "--jq", ".login"], env=environment,
                 capture_output=True, text=True, encoding="utf-8", errors="replace",
                 timeout=TIMEOUT_SECONDS, check=False, creationflags=NO_WINDOW)
    login = (result.stdout or "").strip()
    if result.returncode or not re.fullmatch(r"[A-Za-z0-9-]+", login):
        raise IdentityError("a human GitHub login is required; sign in through `gh auth login --web`, or supply --reviewer")
    return login


def configure_existing_app(slug: str, reviewer: str | None = None, accounts: list[str] | None = None,
                           fetch=api) -> None:
    if not re.fullmatch(r"[A-Za-z0-9-]+", slug):
        raise IdentityError("the GitHub App slug is invalid")
    actual = fetch(f"/apps/{slug}", None)
    if not isinstance(actual, dict) or actual.get("slug") != slug or not isinstance(actual.get("owner"), dict):
        raise IdentityError("GitHub returned an invalid App descriptor")
    try:
        previous = identity_config()
    except OnboardingRequired:
        previous = None
    if previous is not None and previous["app"]["slug"] != slug:
        raise IdentityError("a different GitHub App is already configured; preserve its enrollment")
    login = reviewer or (previous["reviewer"] if previous else human_reviewer())
    permitted = accounts or (previous["accounts"] if previous else [login])
    configure_identity({
        "schema_version": 1,
        "app": {"id": actual.get("id"), "client_id": actual.get("client_id"),
                "slug": actual.get("slug"), "owner": actual["owner"].get("login"),
                "owner_type": actual["owner"].get("type")},
        "reviewer": login,
        "accounts": permitted,
        "permissions": previous["permissions"] if previous and not accounts else
                       {owner: dict(onboarding.PERMISSIONS) for owner in permitted},
        "key": previous["key"] if previous else None,
    })


def reuse_local_key(fetch=api, sign=app_jwt, prefer_pending: bool = False) -> None:
    config = identity_config()
    destination = store() / f"{config['app']['slug']}.pem"
    pending = store() / f"{config['app']['slug']}.pending.pem"
    if config["key"] is not None and Path(config["key"]).exists() and not prefer_pending:
        return
    path = pending if pending.exists() else destination
    if not path.exists():
        return
    safe_existing_file(path)
    require_private_permissions(path)
    record = {**config["app"], "key": str(path)}
    validate_remote_app(record, fetch=fetch, sign=sign)
    if path == pending:
        if is_reparse(destination):
            raise IdentityError("the local GitHub App key location is unsafe")
        os.replace(pending, destination)
        protect(destination)
    configure_identity({**config, "key": str(destination)})


def verify_enrollment(fetch=api, sign=app_jwt) -> None:
    reuse_local_key(fetch=fetch, sign=sign)
    try:
        verify_ready(app_record(), fetch=fetch, sign=sign)
    except GitHubError as error:
        config = identity_config()
        pending = store() / f"{config['app']['slug']}.pending.pem"
        if error.status != 401 or not pending.exists():
            raise
        reuse_local_key(fetch=fetch, sign=sign, prefer_pending=True)
        verify_ready(app_record(), fetch=fetch, sign=sign)


def setup(check: bool = False, onboard_key: bool = False) -> None:
    if onboard_key:
        try:
            verify_enrollment()
        except (OnboardingRequired, KeyVerificationError):
            onboard()
        except GitHubError as error:
            if error.status != 401:
                raise
            onboard()
    if check:
        verify_ready(app_record())
    else:
        verify_enrollment()
    if check:
        verify_host_setup()
        print("bot_identity: ready")
        return
    git_config = _git_config_content(installed_script())
    install_shims(Path(__file__).resolve())
    launcher = install_approve()
    gh_config_directory().mkdir(parents=True, exist_ok=True)
    write_changed(_agent_git_config(), git_config)
    environment = agent_environment(os.environ.get("PATH", ""))
    update_claude(claude_user_settings(), environment)
    update_codex(codex_user_config(), environment)
    if remove_user_path(shim_directory()):
        print(f"Removed {shim_directory()} from your user PATH; only agent sessions put it first")
    print(f"Installed `tj approve` at {launcher}")
    print("Personal agent identity is configured in the Claude and Codex user settings; restart Claude and Codex "
          "to apply, and re-run setup after changing PATH")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["gh"]:
            return run_gh(argv[1:])
        parser = argparse.ArgumentParser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("token").add_argument("--owner", required=True)
        commands.add_parser("credential").add_argument("operation")
        commands.add_parser("converge")
        setup_command = commands.add_parser("setup")
        setup_flags = setup_command.add_mutually_exclusive_group()
        setup_flags.add_argument("--check", action="store_true")
        setup_flags.add_argument("--onboard", action="store_true")
        setup_command.add_argument("--app", metavar="SLUG", help="select an existing GitHub App during explicit onboarding")
        setup_command.add_argument("--reviewer", metavar="LOGIN", help="human account used by tj approve")
        setup_command.add_argument("--account", action="append", metavar="ACCOUNT", help="permitted target account; repeat for organizations")
        arguments = parser.parse_args(argv)
        if arguments.command == "credential":
            return credential(arguments.operation)
        if arguments.command == "converge":
            converge_shims()
            return 0
        if arguments.command == "setup":
            if (arguments.app or arguments.reviewer or arguments.account) and not arguments.onboard:
                parser.error("identity selection requires explicit setup --onboard")
            if (arguments.reviewer or arguments.account) and not arguments.app:
                parser.error("--reviewer and --account require --app")
            if arguments.app:
                configure_existing_app(arguments.app, arguments.reviewer, arguments.account)
            setup(check=arguments.check, onboard_key=arguments.onboard)
            return 0
        if arguments.owner.lower() not in required_owners():
            raise IdentityError("the GitHub App is not authorized for that account")
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
