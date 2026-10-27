#!/usr/bin/env python3
"""Run agent GitHub access as Tommy's GitHub App in personal repositories (Python 3.12+, needs openssl).

`token --owner X` prints an installation token, `credential get` is a git credential helper, `gh ...` wraps
the real gh, and `setup` installs the wrapper and the agent-only settings for Claude and Codex.
"""

from __future__ import annotations

import argparse
import base64
from importlib.resources import files
from http.server import BaseHTTPRequestHandler, HTTPServer
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
import urllib.error
import webbrowser
import zipfile
import stat

from tj_cli.paths import prepend

API = "https://api.github.com"
AGENT_FLAG = "TJ_AGENT"
UNAUTHENTICATED = "bot-identity-unauthenticated"
TIMEOUT_SECONDS = 30
TOKEN_MARGIN_SECONDS = 300
ENROLLMENT_SECONDS = 600
MAX_ENROLLMENT_BYTES = 32 * 1024
REQUIRED_OWNERS = ("tomjseery", "tj-agents", "concertable")
REQUIRED_CAPABILITY_VERSION = 1
REQUIRED_CAPABILITIES = {REQUIRED_CAPABILITY_VERSION: {"tj-agents": {"repository_creation": "write"}}}
FORBIDDEN_WRITE_PERMISSIONS = ("administration",)
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


class GitHubError(IdentityError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def store() -> Path:
    return Path.home() / ".agents-state" / "github-app"


def descriptor_path() -> Path:
    return Path(__file__).with_name("tomjseery-bot.json")


def app_descriptor() -> dict:
    try:
        value = json.loads(descriptor_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityError("the bundled GitHub App descriptor is unavailable") from error
    required = {"id", "client_id", "slug", "owner"}
    if set(value) != required or not isinstance(value["id"], int) or any(
        not isinstance(value[key], str) or not value[key] for key in required - {"id"}
    ):
        raise IdentityError("the bundled GitHub App descriptor is invalid")
    return value


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
    descriptor = app_descriptor()
    if is_reparse(store()):
        raise IdentityError("the GitHub App enrollment directory is unsafe")
    path = store() / f"{descriptor['slug']}.json"
    if not path.exists():
        raise IdentityError("enrollment required: run `bot_identity.py setup --onboard` with Tommy present")
    safe_existing_file(path)
    require_private_permissions(store(), directory=True)
    require_private_permissions(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IdentityError("the local GitHub App enrollment is invalid") from error
    if any(record.get(key) != value for key, value in descriptor.items()):
        raise IdentityError("the local GitHub App enrollment does not match the pinned App")
    key = Path(record.get("key", ""))
    if not key.is_absolute() or key.parent != store() or key.name != f"{descriptor['slug']}.pem":
        raise IdentityError("the local GitHub App key location is invalid")
    safe_existing_file(key)
    require_private_permissions(key)
    record["key"] = str(key)
    return record


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
        raise IdentityError("openssl could not sign with the enrolled GitHub App key")
    return f"{signing}.{b64(result.stdout)}"


def api(path: str, bearer: str, method: str = "GET") -> object:
    request = urllib.request.Request(f"{API}{path}", method=method, headers={
        "Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json"})
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
            actual.get("owner", {}).get("login", "").lower() != descriptor["owner"].lower():
        raise IdentityError("the enrolled key does not authenticate the pinned GitHub App")
    return actual


def app_settings_url(descriptor: dict) -> str:
    return f"https://github.com/settings/apps/{descriptor['slug']}"


def installation_settings_url(installation: dict) -> str:
    account = installation.get("account", {})
    login = account.get("login", "tj-agents")
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
    capability_error("pinned GitHub App", actual.get("permissions"),
                     REQUIRED_CAPABILITIES[REQUIRED_CAPABILITY_VERSION]["tj-agents"], app_settings_url(descriptor))


def remote_installations(record: dict, fetch=api, sign=app_jwt) -> dict[str, dict]:
    values = fetch("/app/installations", sign(record))
    if not isinstance(values, list):
        raise IdentityError("the pinned GitHub App installations response is invalid")
    known = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int) or \
                not isinstance(item.get("account"), dict) or \
                not isinstance(item["account"].get("login"), str):
            raise IdentityError("the pinned GitHub App installations response is invalid")
        known[item["account"]["login"].lower()] = item
    return known


def missing_required_installations(record: dict, fetch=api, sign=app_jwt) -> list[str]:
    known = remote_installations(record, fetch=fetch, sign=sign)
    return [owner for owner in REQUIRED_OWNERS if owner not in known]


def verify_ready(record: dict, fetch=api, sign=app_jwt) -> None:
    actual = validate_remote_app(record, fetch=fetch, sign=sign)
    validate_app_capabilities(actual)
    known = remote_installations(record, fetch=fetch, sign=sign)
    missing = [owner for owner in REQUIRED_OWNERS if owner not in known]
    if missing:
        raise IdentityError("the pinned GitHub App is not installed on: " + ", ".join(missing) +
                            "; install it at https://github.com/apps/tomjseery-bot/installations/new")
    tj_agents = known["tj-agents"]
    capability_error("tj-agents App installation", tj_agents.get("permissions"),
                     REQUIRED_CAPABILITIES[REQUIRED_CAPABILITY_VERSION]["tj-agents"],
                     installation_settings_url(tj_agents))


def persist_enrollment(key: bytes, fetch=api, sign=app_jwt) -> dict:
    """Verify a newly generated key before atomically making it the local enrollment."""
    if not key.startswith(b"-----BEGIN ") or b"PRIVATE KEY-----" not in key or len(key) > MAX_ENROLLMENT_BYTES:
        raise IdentityError("the selected file is not a supported GitHub App private key")
    descriptor = app_descriptor()
    directory = secure_store()
    candidate = directory / ".candidate.pem"
    if candidate.exists() or is_reparse(candidate):
        candidate.unlink(missing_ok=True)
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
        write_private(directory / f"{descriptor['slug']}.json", record)
        return record
    finally:
        candidate.unlink(missing_ok=True)


def enrollment_page(port: int, nonce: str) -> bytes:
    descriptor = app_descriptor()
    endpoint = f"/enroll/{nonce}"
    return f"""<!doctype html><meta charset=utf-8><title>GitHub App enrollment</title>
<h1>Enroll this machine for {descriptor['slug']}</h1>
<p>This connects only to the existing GitHub App <strong>{descriptor['owner']}/{descriptor['slug']}</strong>
(App ID {descriptor['id']}). Your browser keeps the downloaded PEM; remove it yourself through your browser or OS after success.</p>
<p>Create a new private key at <a href=\"https://github.com/settings/apps/tomjseery-bot\">GitHub App settings</a>, then select that PEM file.</p>
<input id=key type=file accept=\".pem,application/x-pem-file\"><button id=enroll>Enroll key</button>
<button id=verify>Verify required installations</button><pre id=result></pre>
<script>const endpoint={endpoint!r}, state={nonce!r}, result=document.getElementById('result');
async function post(body) {{ let r=await fetch(endpoint,{{method:'POST',headers:{{'X-Bot-Identity-State':state}},body}}); result.textContent=await r.text(); }}
document.getElementById('enroll').onclick=async()=>{{let f=document.getElementById('key').files[0];if(!f){{result.textContent='Select the newly downloaded PEM file.';return}};await post(await f.arrayBuffer())}};
document.getElementById('verify').onclick=()=>post('');</script>""".encode("utf-8")


def onboard(open_browser=webbrowser.open, fetch=api, sign=app_jwt, clock=time.monotonic) -> None:
    import secrets
    nonce = secrets.token_urlsafe(32)

    class EnrollmentHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def allowed(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def reply(self, code: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
            payload = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if not self.allowed() or self.path != f"/enroll/{nonce}":
                self.reply(404, "Not found")
                return
            payload = enrollment_page(self.server.server_port, nonce)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if not self.allowed() or self.path != f"/enroll/{nonce}" or \
                    self.headers.get("Origin") != origin or self.headers.get("X-Bot-Identity-State") != nonce:
                self.reply(403, "Enrollment request rejected")
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_ENROLLMENT_BYTES:
                self.reply(413, "Enrollment upload rejected")
                return
            key = self.rfile.read(length)
            try:
                if key:
                    persist_enrollment(key, fetch=fetch, sign=sign)
                missing = missing_required_installations(app_record(), fetch=fetch, sign=sign)
                if missing:
                    self.reply(200, "Key enrolled. Install the App for " + ", ".join(missing) +
                               " at https://github.com/apps/tomjseery-bot/installations/new, then rerun setup.")
                    self.server.finished = True
                else:
                    self.reply(200, "Enrollment verified. Return to the terminal to finish setup.")
                    self.server.finished = True
            except IdentityError:
                self.reply(400, "Enrollment could not be verified. Check the connection and that the selected key belongs to this App, then retry.")

    server = HTTPServer(("127.0.0.1", 0), EnrollmentHandler)
    server.timeout = 1
    server.finished = False
    url = f"http://127.0.0.1:{server.server_port}/enroll/{nonce}"
    print("Opening a local GitHub App enrollment page. It expires in 10 minutes.")
    print(url)
    open_browser(url)
    deadline = clock() + ENROLLMENT_SECONDS
    try:
        while clock() < deadline and not server.finished:
            server.handle_request()
    finally:
        server.server_close()
    if not server.finished:
        raise IdentityError("GitHub App enrollment did not complete within 10 minutes")


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
    if owner.lower() not in REQUIRED_OWNERS:
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
    protected = [owner for owner in owners if owner.lower() in REQUIRED_OWNERS]
    covered = installed(protected, record) if protected else {}
    missing = [owner for owner in protected if owner.lower() not in covered]
    if missing:
        raise IdentityError("the pinned GitHub App is not installed on " + ", ".join(missing))
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
        if owner.lower() in REQUIRED_OWNERS:
            if not installed([owner], record):
                return 0
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
    entries = (entry for entry in path.split(os.pathsep) if entry and not is_shim(entry))
    return os.pathsep.join(prepend(entries, str(shim_directory())))


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
    main = (f"import runpy, sys\nsys.path.insert(0, {str(script.parent)!r})\n"
            f"sys.argv = [{str(script)!r}, 'gh', *sys.argv[1:]]\n"
            f"runpy.run_path({str(script)!r}, run_name='__main__')\n")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr(zipfile.ZipInfo("__main__.py", (1980, 1, 1, 0, 0, 0)), main)
    return script_launcher() + f'#!"{sys.executable}" -B\n'.encode() + archive.getvalue()


def package_contents(directory: Path) -> dict[Path, bytes]:
    if not directory.is_dir() or is_reparse(directory):
        raise IdentityError("the shared CLI package is missing or unsafe; run setup")
    contents = {}
    for path in sorted(directory.rglob("*")):
        if is_reparse(path):
            raise IdentityError("the shared CLI package contains a link; run setup")
        relative = path.relative_to(directory)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_file():
            contents[relative] = path.read_bytes()
    return contents


def cli_package_contents() -> dict[Path, bytes]:
    directory = files("tj_cli")
    if not isinstance(directory, Path):
        raise IdentityError("the shared CLI package must be a shipped filesystem package")
    return package_contents(directory)


def install_cli_package(directory: Path) -> None:
    expected = cli_package_contents()
    current = package_contents(directory) if directory.exists() else {}
    if is_reparse(directory):
        raise IdentityError("the installed shared CLI package is unsafe")
    for relative, content in expected.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for relative in current.keys() - expected.keys():
        (directory / relative).unlink()
    for cached in directory.rglob("*.pyc"):
        cached.unlink()
    for child in sorted(directory.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()


def install_shims(source: Path) -> Path:
    directory = shim_directory()
    if is_reparse(directory):
        raise IdentityError("the GitHub App wrapper directory is unsafe")
    directory.mkdir(parents=True, exist_ok=True)
    install_cli_package(directory / "tj_cli")
    script = directory / source.name
    shutil.copyfile(source, script)
    shutil.copyfile(descriptor_path(), script.with_name("tomjseery-bot.json"))
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


def installed_script() -> Path:
    return shim_directory() / Path(__file__).name


def verify_host_setup() -> None:
    source = Path(__file__).resolve()
    script = installed_script()
    descriptor = script.with_name("tomjseery-bot.json")
    if package_contents(shim_directory() / "tj_cli") != cli_package_contents():
        raise IdentityError("the installed shared CLI package is stale; run setup")
    for path, expected in ((script, source.read_bytes()),
                           (descriptor, source.with_name("tomjseery-bot.json").read_bytes())):
        safe_existing_file(path)
        if path.read_bytes() != expected:
            raise IdentityError("the installed GitHub App wrapper is stale; run setup")
    launcher = shim_directory() / ("gh.exe" if WINDOWS else "gh")
    safe_existing_file(launcher)
    expected_launcher = windows_executable(script) if WINDOWS else \
        f"#!/bin/sh\nexec \"{Path(sys.executable).as_posix()}\" -B \"{script.as_posix()}\" gh \"$@\"\n".encode()
    if launcher.read_bytes() != expected_launcher:
        raise IdentityError("the installed GitHub App wrapper is stale; run setup")
    environment = agent_environment(script, os.environ.get("PATH", ""))
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    try:
        claude_settings = json.loads(claude.read_text(encoding="utf-8-sig"))
        claude_env = claude_settings["env"]
        claude_denials = claude_settings["permissions"]["deny"]
        import tomllib
        codex_env = tomllib.loads(codex.read_text(encoding="utf-8-sig"))["shell_environment_policy"]["set"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise IdentityError("agent host settings are missing; run setup") from error
    if not isinstance(claude_denials, list) or any(rule not in claude_denials for rule in MCP_DENY):
        raise IdentityError("agent host write restrictions are missing; run setup")
    for settings in (claude_env, codex_env):
        if any(settings.get(key) != value for key, value in environment.items()) or any(
                (key.startswith("GIT_CONFIG_") or key in MANAGED) and key not in environment for key in settings):
            raise IdentityError("agent host settings are stale; run setup")


def setup(check: bool = False, onboard_key: bool = False) -> None:
    if onboard_key:
        try:
            candidate = app_record()
            validate_remote_app(candidate)
        except IdentityError as error:
            if isinstance(error, GitHubError) and error.status != 401:
                raise
            onboard()
    record = app_record()
    verify_ready(record)
    if check:
        verify_host_setup()
        print("bot_identity: ready")
        return
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
        setup_command = commands.add_parser("setup")
        setup_flags = setup_command.add_mutually_exclusive_group()
        setup_flags.add_argument("--check", action="store_true")
        setup_flags.add_argument("--onboard", action="store_true")
        arguments = parser.parse_args(argv)
        if arguments.command == "credential":
            return credential(arguments.operation)
        if arguments.command == "setup":
            setup(check=arguments.check, onboard_key=arguments.onboard)
            return 0
        if arguments.owner.lower() not in REQUIRED_OWNERS:
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
