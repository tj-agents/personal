from __future__ import annotations

import copy
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import HTTPServer

import onboarding
import pytest


class EnrollmentIncompleteError(Exception):
    pass


def public_app(owner: str = "casey") -> dict[str, object]:
    return {
        "id": 2468,
        "client_id": "fixture-client",
        "slug": "casey-agent",
        "owner": {"login": owner, "type": "User"},
    }


@dataclass
class Enrollment:
    config: dict[str, object] | None = None
    installed: bool = False
    keys: list[bytes] = field(default_factory=list)
    api_calls: list[str] = field(default_factory=list)
    remote_accounts: list[str] = field(default_factory=lambda: ["casey", "casey-labs"])

    def load(self) -> dict[str, object]:
        if self.config is None:
            raise EnrollmentIncompleteError("choose an identity")
        return copy.deepcopy(self.config)

    def configure(self, config: dict[str, object]) -> None:
        self.config = copy.deepcopy(config)

    def enroll(self, key: bytes) -> None:
        assert self.config is not None
        self.keys.append(key)
        self.config["key"] = "/protected/casey-agent.pem"

    def ready(self) -> None:
        if not self.config or not self.config.get("key"):
            raise EnrollmentIncompleteError("enroll this machine")
        accounts = self.config["accounts"]
        assert isinstance(accounts, list)
        if not self.installed or not set(accounts) <= set(self.remote_accounts):
            raise EnrollmentIncompleteError("missing installation for casey")

    def discover(self) -> list[str]:
        return list(self.remote_accounts)

    def request(self, path: str, *, method: str = "GET") -> dict[str, object]:
        self.api_calls.append(f"{method} {path}")
        if path == "/apps/casey-agent":
            return public_app()
        assert method == "POST" and path == "/app-manifests/fixture-code/conversions"
        return {**public_app(), "pem": "fixture-private-material"}


@dataclass
class Wizard:
    backend: Enrollment
    now: float = 0
    url: str = ""
    errors: list[str] = field(default_factory=list)
    started: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def opened(self, url: str) -> bool:
        self.url = url
        self.started.set()
        return True

    def clock(self) -> float:
        return self.now

    def run(self) -> None:
        try:
            onboarding.onboard(
                load=self.backend.load,
                configure=self.backend.configure,
                enroll=self.backend.enroll,
                ready=self.backend.ready,
                error_type=EnrollmentIncompleteError,
                open_browser=self.opened,
                clock=self.clock,
                duration=10,
                discover=self.backend.discover,
            )
        except onboarding.OnboardingError as error:
            self.errors.append(str(error))

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
        assert self.started.wait(2), "local server did not start"

    def finish(self) -> None:
        assert self.thread is not None
        self.thread.join(2)
        assert not self.thread.is_alive(), "local server did not finish"

    def post(
        self, action: str, body: dict[str, object] | bytes, *, origin: str | None = None
    ) -> tuple[int, dict[str, object]]:
        nonce = self.url.rsplit("/", 1)[1]
        base = self.url.split("/enroll/", 1)[0]
        request = urllib.request.Request(
            f"{base}/{action}/{nonce}",
            data=body if isinstance(body, bytes) else json.dumps(body).encode(),
            headers={"Origin": origin or base, "X-Bot-Identity-State": nonce},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                result: dict[str, object] = json.loads(response.read())
                return response.status, result
        except urllib.error.HTTPError as error:
            with error:
                result = json.loads(error.read())
                return error.code, result


@pytest.fixture
def enrollment(monkeypatch: pytest.MonkeyPatch) -> Enrollment:
    backend = Enrollment()
    monkeypatch.setattr(onboarding, "request_json", backend.request)
    return backend


@pytest.fixture
def wizard(enrollment: Enrollment) -> Iterator[Wizard]:
    running = Wizard(enrollment)
    running.start()
    try:
        yield running
    finally:
        running.now = 100
        running.finish()


def selection() -> dict[str, object]:
    return {"reviewer": "casey", "accounts": "casey, casey-labs", "organization": ""}


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_existing_bot_on_new_machine_never_recreates_app(wizard: Wizard) -> None:
    status, result = wizard.post(
        "select", {**selection(), "app": "https://github.com/apps/casey-agent"}
    )
    assert status == 200
    links = result["links"]
    assert isinstance(links, dict)
    assert "Existing App key settings" in links
    wizard.backend.installed = True
    status, _ = wizard.post("enroll", b"existing-protected-key-fixture")
    assert status == 200
    wizard.finish()
    assert wizard.backend.api_calls == ["GET /apps/casey-agent"]
    assert wizard.backend.keys == [b"existing-protected-key-fixture"]
    assert wizard.backend.config is not None
    assert wizard.backend.config["reviewer"] == "casey"
    assert wizard.backend.config["accounts"] == ["casey", "casey-labs"]
    assert not wizard.errors


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_manifest_creation_exchanges_code_without_printing_key(
    wizard: Wizard, capsys: pytest.CaptureFixture[str]
) -> None:
    status, result = wizard.post("create", selection())
    assert status == 200
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    assert manifest["default_permissions"] == onboarding.PERMISSIONS
    action = result["action"]
    assert isinstance(action, str)
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(action).query)["state"][0]
    callback = manifest["redirect_url"]
    assert isinstance(callback, str)
    with urllib.request.urlopen(
        f"{callback}?code=fixture-code&state={state}", timeout=2
    ) as response:
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "fixture-private-material" not in response.read().decode()
    assert wizard.backend.keys == [b"fixture-private-material"]
    status, progress = wizard.post("enroll", b"")
    assert status == 200
    assert "missing installation for casey" in str(progress["message"])
    wizard.backend.installed = True
    wizard.post("enroll", b"")
    wizard.finish()
    output = capsys.readouterr()
    assert "fixture-private-material" not in output.out + output.err
    assert "fixture-code" not in output.out + output.err
    assert wizard.backend.api_calls == ["POST /app-manifests/fixture-code/conversions"]


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_partial_existing_enrollment_retains_key_and_resumes_installation(
    wizard: Wizard,
) -> None:
    wizard.post("select", {**selection(), "app": "casey-agent"})
    wizard.post("enroll", b"fixture-existing-key")
    saved = copy.deepcopy(wizard.backend.config)
    status, _ = wizard.post("create", selection())
    assert status == 400
    assert wizard.backend.config == saved
    wizard.now = 100
    wizard.finish()
    assert wizard.errors and "retained enrollment" in wizard.errors[0]
    resumed = Wizard(wizard.backend)
    resumed.start()
    try:
        resumed.backend.installed = True
        resumed.post("enroll", b"")
        resumed.finish()
    finally:
        resumed.now = 100
        resumed.finish()
    assert wizard.backend.config == saved
    assert wizard.backend.keys == [b"fixture-existing-key"]
    assert wizard.backend.api_calls == ["GET /apps/casey-agent"]


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_cross_origin_and_callback_state_cannot_configure_identity(
    wizard: Wizard,
) -> None:
    status, _ = wizard.post(
        "select", {**selection(), "app": "casey-agent"}, origin="https://evil.invalid"
    )
    assert status == 403
    _, result = wizard.post("create", selection())
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(
            f"{manifest['redirect_url']}?code=fixture-code&state=wrong", timeout=2
        )
    with error.value:
        assert error.value.code == 403
    assert wizard.backend.config is None
    assert not wizard.backend.api_calls
    assert not wizard.backend.keys


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_network_failure_preserves_app_selection_without_creating_an_app(
    wizard: Wizard,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wizard.post("select", {**selection(), "app": "casey-agent"})
    saved = copy.deepcopy(wizard.backend.config)

    def unavailable(path: str, *, method: str = "GET") -> dict[str, object]:
        raise onboarding.OnboardingError("offline")

    monkeypatch.setattr(onboarding, "request_json", unavailable)
    status, _ = wizard.post("select", {**selection(), "app": "casey-agent"})
    assert status == 400
    assert wizard.backend.config == saved
    assert wizard.backend.api_calls == ["GET /apps/casey-agent"]


def test_organization_owned_app_has_correct_settings_link() -> None:
    selected = onboarding.Selection.parse(selection())
    config = selected.configuration(
        {
            **public_app("casey-labs"),
            "owner": {"login": "casey-labs", "type": "Organization"},
        }
    )
    app = config["app"]
    assert isinstance(app, dict)
    assert (
        onboarding.settings_url(app)
        == "https://github.com/organizations/casey-labs/settings/apps/casey-agent"
    )


def test_known_identity_page_disables_new_app_and_escapes_fields() -> None:
    config = onboarding.Selection.parse(selection()).configuration(public_app())
    config["reviewer"] = '"><script>bad()</script>'
    config["key"] = "/protected/key.pem"
    document = onboarding.page("fixture-nonce", config)
    assert document.count("<script") == 1
    assert "&lt;script&gt;" in document
    assert 'id="create" disabled' in document
    assert "post(endpoint,new Uint8Array(),true);" in document


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_existing_organization_installation_can_be_reused_without_installing_again(
    wizard: Wizard,
) -> None:
    wizard.backend.remote_accounts = ["casey-labs"]
    wizard.backend.installed = True
    wizard.post("select", {**selection(), "app": "casey-agent"})
    status, progress = wizard.post("enroll", b"existing-key-fixture")
    assert status == 200
    assert progress["installed_accounts"] == ["casey-labs"]
    status, _ = wizard.post("accounts", {"accounts": ["casey-labs"]})
    assert status == 200
    wizard.finish()
    assert wizard.backend.config is not None
    assert wizard.backend.config["accounts"] == ["casey-labs"]
    assert wizard.backend.keys == [b"existing-key-fixture"]
    assert wizard.backend.api_calls == ["GET /apps/casey-agent"]


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_installed_account_selection_cannot_authorize_unknown_accounts(
    wizard: Wizard,
) -> None:
    wizard.post("select", {**selection(), "app": "casey-agent"})
    wizard.post("enroll", b"existing-key-fixture")
    saved = copy.deepcopy(wizard.backend.config)
    status, _ = wizard.post("accounts", {"accounts": ["unrelated-company"]})
    assert status == 400
    assert wizard.backend.config == saved


@pytest.mark.allow_hosts(["127.0.0.1"])
def test_cancelled_wizard_retains_selected_app_and_key(
    enrollment: Enrollment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enrollment.config = onboarding.Selection.parse(selection()).configuration(
        public_app()
    )
    enrollment.enroll(b"retained-key-fixture")
    saved = copy.deepcopy(enrollment.config)

    def interrupt(server: HTTPServer) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(HTTPServer, "handle_request", interrupt)
    with pytest.raises(onboarding.OnboardingError, match="cancelled"):
        onboarding.onboard(
            load=enrollment.load,
            configure=enrollment.configure,
            enroll=enrollment.enroll,
            ready=enrollment.ready,
            error_type=EnrollmentIncompleteError,
            open_browser=lambda url: True,
        )
    assert enrollment.config == saved
    assert enrollment.keys == [b"retained-key-fixture"]
