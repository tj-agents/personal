"""Local GitHub App registration and existing-App enrollment (Python 3.12+)."""

from __future__ import annotations

import html
import json
import re
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from string import Template

API = "https://api.github.com"
PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "workflows": "write",
}
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,99}")
MAX_BYTES = 32 * 1024


class OnboardingError(Exception):
    pass


def request_json(path: str, *, method: str = "GET") -> dict[str, object]:
    request = urllib.request.Request(
        API + path,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "tj-agents-onboarding",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise OnboardingError("GitHub returned an oversized response")
        value: object = json.loads(raw)
    except (OSError, ValueError) as error:
        raise OnboardingError(
            "GitHub could not complete this step; enrollment is retained"
        ) from error
    if not isinstance(value, dict):
        raise OnboardingError("GitHub returned an invalid App response")
    return value


def login(value: object) -> str:
    if not isinstance(value, str) or not LOGIN.fullmatch(value):
        raise OnboardingError("Enter a valid GitHub account login")
    return value.lower()


def app_slug(value: object) -> str:
    if not isinstance(value, str):
        raise OnboardingError("Enter the existing App's slug or github.com/apps URL")
    value = value.strip()
    if value.startswith("https://github.com/apps/"):
        value = value.removeprefix("https://github.com/apps/").rstrip("/")
    if not SLUG.fullmatch(value):
        raise OnboardingError("Enter the existing App's slug or github.com/apps URL")
    return value.lower()


@dataclass(frozen=True, slots=True)
class Selection:
    reviewer: str
    accounts: tuple[str, ...]
    organization: str
    create_repositories: bool

    @classmethod
    def parse(cls, value: dict[str, object]) -> Selection:
        reviewer = login(value.get("reviewer"))
        accounts = value.get("accounts")
        if not isinstance(accounts, str):
            raise OnboardingError(
                "Enter the accounts this machine may use with your bot"
            )
        chosen = tuple(
            dict.fromkeys(
                login(item) for item in re.split(r"[,\s]+", accounts.strip()) if item
            )
        )
        if not chosen:
            chosen = (reviewer,)
        organization = value.get("organization", "")
        organization = login(organization) if organization else ""
        return cls(
            reviewer, chosen, organization, value.get("create_repositories") is True
        )

    def configuration(self, app: dict[str, object]) -> dict[str, object]:
        owner = app.get("owner")
        if not isinstance(owner, dict):
            raise OnboardingError("GitHub did not return the App owner")
        descriptor = {key: app.get(key) for key in ("id", "client_id", "slug")}
        descriptor["owner"] = login(owner.get("login"))
        owner_type = owner.get("type")
        if owner_type not in ("User", "Organization"):
            raise OnboardingError("GitHub did not return the App owner type")
        descriptor["owner_type"] = owner_type
        if type(descriptor["id"]) is not int or descriptor["id"] <= 0:
            raise OnboardingError("GitHub did not return a valid App ID")
        app_slug(descriptor["slug"])
        if not isinstance(descriptor["client_id"], str) or not descriptor["client_id"]:
            raise OnboardingError("GitHub did not return the App client ID")
        permissions = {
            **PERMISSIONS,
            **({"repository_creation": "write"} if self.create_repositories else {}),
        }
        return {
            "schema_version": 1,
            "app": descriptor,
            "reviewer": self.reviewer,
            "accounts": list(self.accounts),
            "permissions": {account: dict(permissions) for account in self.accounts},
            "key": None,
        }

    def manifest(self, origin: str, nonce: str) -> dict[str, object]:
        return {
            "name": f"{self.reviewer}-agent-bot",
            "url": "https://github.com/tj-agents",
            "description": "Agent changes with separate human approval",
            "public": True,
            "redirect_url": f"{origin}/callback/{nonce}",
            "setup_url": f"{origin}/installed/{nonce}",
            "default_events": [],
            "default_permissions": {
                **PERMISSIONS,
                **(
                    {"repository_creation": "write"} if self.create_repositories else {}
                ),
            },
        }


def settings_url(app: dict[str, object]) -> str:
    slug = app_slug(app.get("slug"))
    if app.get("owner_type") == "Organization":
        return f"https://github.com/organizations/{login(app.get('owner'))}/settings/apps/{slug}"
    return f"https://github.com/settings/apps/{slug}"


def page(nonce: str, config: dict[str, object] | None) -> str:
    config = config or {}
    app = config.get("app")
    slug = app.get("slug", "") if isinstance(app, dict) else ""
    reviewer = config.get("reviewer", "")
    accounts = config.get("accounts", [])
    chosen = (
        ", ".join(str(account) for account in accounts)
        if isinstance(accounts, list)
        else ""
    )
    state = (
        "A protected key is already enrolled. Verify installations to continue."
        if config.get("key")
        else "Select an existing App and key, or create your own App."
    )
    existing_links = ""
    if isinstance(app, dict):
        existing_links = (
            f'<a href="{html.escape(settings_url(app), quote=True)}" target="_blank" '
            'rel="noreferrer">Existing App key settings</a><br>'
            f'<a href="https://github.com/apps/{app_slug(slug)}/installations/new" '
            'target="_blank" rel="noreferrer">Install on a selected account</a>'
        )
    disabled = " disabled" if config else ""
    verify_on_load = (
        "post(endpoint,new Uint8Array(),true);" if config.get("key") else ""
    )
    template = Template(
        Path(__file__).with_name("onboarding.html").read_text(encoding="utf-8")
    )
    return template.substitute(
        reviewer=html.escape(str(reviewer), quote=True),
        accounts=html.escape(chosen, quote=True),
        slug=html.escape(str(slug), quote=True),
        message=state,
        disabled=disabled,
        links=existing_links,
        verify_on_load=verify_on_load,
        nonce=nonce,
    )


def onboard(
    *,
    load: Callable[[], dict[str, object]],
    configure: Callable[[dict[str, object]], None],
    enroll: Callable[[bytes], object],
    ready: Callable[[], None],
    error_type: type[Exception],
    open_browser: Callable[[str], object] = webbrowser.open,
    clock: Callable[[], float] = time.monotonic,
    duration: float = 600,
    discover: Callable[[], list[str]] | None = None,
) -> None:
    nonce = secrets.token_urlsafe(32)
    finished = False
    pending: Selection | None = None
    creation_started = False
    converted = False

    def configuration() -> dict[str, object] | None:
        try:
            return load()
        except error_type:
            return None

    def progress() -> dict[str, object]:
        nonlocal finished
        config = load()
        app = config.get("app")
        slug = app_slug(app.get("slug")) if isinstance(app, dict) else ""
        links = {
            "App settings (reuse this App)": settings_url(app)
            if isinstance(app, dict)
            else "",
            "Install on a selected account": f"https://github.com/apps/{slug}/installations/new",
        }
        try:
            ready()
        except error_type as error:
            available: list[str] = []
            if discover is not None and config.get("key"):
                try:
                    available = discover()
                except error_type as discovery_error:
                    return {
                        "message": f"Enrollment retained. {discovery_error}",
                        "links": links,
                    }
            return {
                "message": f"Enrollment retained. {error}",
                "links": links,
                "installed_accounts": available,
            }
        finished = True
        return {
            "message": "Bot verified. Return to setup to finish local configuration."
        }

    class Handler(BaseHTTPRequestHandler):
        server: HTTPServer

        def log_message(self, format_string: str, *args: object) -> None:
            return

        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(5)

        def allowed(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def reply(self, status: int, content: str | dict[str, object]) -> None:
            document = isinstance(content, str)
            payload = (
                content if isinstance(content, str) else json.dumps(content)
            ).encode("utf-8")
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8" if document else "application/json",
            )
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'none'; script-src 'nonce-{nonce}'; "
                "connect-src 'self'; form-action https://github.com; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            nonlocal converted
            if not self.allowed():
                self.reply(404, {"message": "Not found"})
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == f"/enroll/{nonce}" and not parsed.query:
                self.reply(200, page(nonce, configuration()))
                return
            try:
                if parsed.path == f"/callback/{nonce}":
                    query = urllib.parse.parse_qs(parsed.query)
                    code = query.get("code", [""])[0]
                    if (
                        pending is None
                        or converted
                        or query.get("state") != [nonce]
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", code)
                    ):
                        self.reply(
                            403, {"message": "App registration callback rejected"}
                        )
                        return
                    response = request_json(
                        f"/app-manifests/{code}/conversions", method="POST"
                    )
                    converted = True
                    config = pending.configuration(response)
                    app = config["app"]
                    expected = pending.organization or pending.reviewer
                    if not isinstance(app, dict) or app.get("owner") != expected:
                        raise OnboardingError(
                            "Different App owner; resume through existing-App setup."
                        )
                    key = response.get("pem")
                    if not isinstance(key, str):
                        raise OnboardingError(
                            "No App key returned; resume through existing-App setup."
                        )
                    configure(config)
                    enroll(key.encode("utf-8"))
                    self.reply(200, page(nonce, configuration()))
                    return
                if parsed.path == f"/installed/{nonce}":
                    self.reply(200, page(nonce, configuration()))
                    return
            except (OnboardingError, error_type):
                self.reply(
                    400,
                    {
                        "message": "Registration incomplete. Enrollment is retained. "
                        "Resume using your existing App; do not create another App."
                    },
                )
                return
            self.reply(404, {"message": "Not found"})

        def do_POST(self) -> None:
            nonlocal pending, creation_started
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (
                not self.allowed()
                or self.headers.get("Origin") != origin
                or self.headers.get("X-Bot-Identity-State") != nonce
            ):
                self.reply(403, {"message": "Enrollment request rejected"})
                return
            if self.path not in (
                f"/enroll/{nonce}",
                f"/select/{nonce}",
                f"/create/{nonce}",
                f"/accounts/{nonce}",
            ):
                self.reply(404, {"message": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BYTES:
                self.reply(413, {"message": "Enrollment upload rejected"})
                return
            raw = self.rfile.read(length)
            try:
                if self.path == f"/enroll/{nonce}":
                    if raw:
                        enroll(raw)
                    self.reply(200, progress())
                    return
                body: object = json.loads(raw)
                if not isinstance(body, dict):
                    raise OnboardingError("Invalid setup selection")
                if self.path == f"/accounts/{nonce}":
                    chosen = body.get("accounts")
                    if not isinstance(chosen, list) or not chosen or discover is None:
                        raise OnboardingError("Select existing installations")
                    accounts = list(dict.fromkeys(login(account) for account in chosen))
                    available = {account.lower() for account in discover()}
                    if not set(accounts) <= available:
                        raise OnboardingError(
                            "An account is not an existing installation"
                        )
                    config = load()
                    requirements = config.get("permissions")
                    requirements = (
                        requirements if isinstance(requirements, dict) else {}
                    )
                    config["accounts"] = accounts
                    config["permissions"] = {
                        account: requirements.get(account, dict(PERMISSIONS))
                        for account in accounts
                    }
                    configure(config)
                    self.reply(200, progress())
                    return
                selected = Selection.parse(body)
                if self.path == f"/select/{nonce}":
                    slug = app_slug(body.get("app"))
                    app = request_json(f"/apps/{slug}")
                    config = selected.configuration(app)
                    app_config = config["app"]
                    if not isinstance(app_config, dict):
                        raise OnboardingError("Invalid App descriptor")
                    previous = configuration()
                    if previous and previous.get("key"):
                        if previous.get("app") != config["app"]:
                            raise OnboardingError(
                                "Finish current enrollment before changing Apps."
                            )
                        config["key"] = previous["key"]
                    configure(config)
                    self.reply(
                        200,
                        {
                            "message": "App selected. Choose its PEM; "
                            "reuse its existing installations.",
                            "links": {
                                "Existing App key settings": settings_url(app_config)
                            },
                        },
                    )
                    return
                if creation_started or configuration():
                    raise OnboardingError(
                        "App already selected; resume through existing-App setup."
                    )
                pending, creation_started = selected, True
                action = (
                    f"https://github.com/organizations/{selected.organization}/settings/apps/new"
                    if selected.organization
                    else "https://github.com/settings/apps/new"
                )
                self.reply(
                    200,
                    {
                        "action": f"{action}?state={nonce}",
                        "manifest": selected.manifest(origin, nonce),
                    },
                )
            except (OnboardingError, ValueError, error_type):
                self.reply(
                    400,
                    {
                        "message": "Step not verified. Check the App, accounts or key "
                        "and retry; completed enrollment is retained."
                    },
                )

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.25
    url = f"http://127.0.0.1:{server.server_port}/enroll/{nonce}"
    print("Opening local setup for an existing or new bot.")
    try:
        if open_browser(url) is False:
            raise OnboardingError("Cannot open local setup; enrollment is retained")
        deadline = clock() + duration
        while clock() < deadline and not finished:
            server.handle_request()
    except KeyboardInterrupt as error:
        raise OnboardingError(
            "Setup cancelled; completed App selection and enrollment are retained"
        ) from error
    finally:
        server.server_close()
    if not finished:
        raise OnboardingError(
            "Setup timed out; resume the existing App and retained enrollment"
        )
