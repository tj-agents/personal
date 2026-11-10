"""Exercise the real local UI with a fake GitHub boundary; capture failures safely."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "personal/utility/bot-identity/scripts"),
)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import onboarding
from test_onboarding import Enrollment, Wizard


def capture_failure(page: Page, directory: Path, step: str, errors: list[str]) -> None:
    capture_errors: list[str] = []
    rendered_state = "unavailable"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"Cannot create diagnostic directory: {error}", file=sys.stderr)
        return
    try:
        page.screenshot(path=str(directory / "failure.png"), timeout=5_000)
    except (BrowserError, OSError) as error:
        capture_errors.append(f"screenshot: {error}")
    try:
        rendered_state = page.locator("body").inner_text(timeout=5_000)
    except BrowserError as error:
        capture_errors.append(f"rendered state: {error}")
    try:
        (directory / "failure.json").write_text(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "expected_step": step,
                    "rendered_state": rendered_state,
                    "browser_errors": errors,
                    "capture_errors": capture_errors,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        print(f"Cannot save diagnostic state: {error}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", required=True, type=Path, help="Chromium executable"
    )
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    backend = Enrollment()
    onboarding.request_json = backend.request
    wizard = Wizard(backend)
    wizard.start()
    step = "first rendered account choice"
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(args.browser.resolve()),
                headless=not args.headed,
                chromium_sandbox=True,
            )
            context = browser.new_context(service_workers="block")
            # This fixture contains only synthetic identity/key data. External requests
            # are blocked; never run this capture helper against human authentication.
            origin = urlsplit(wizard.url)
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if urlsplit(route.request.url)[:2] == origin[:2]
                    else route.abort()
                ),
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.on(
                "requestfailed",
                lambda request: errors.append(
                    f"request failed: {request.method} {request.resource_type}"
                ),
            )
            try:
                page.goto(wizard.url, timeout=10_000)
                expect(page.locator("#create")).to_be_visible(timeout=5_000)
                step = "existing App selection"
                page.locator("#reviewer").fill("casey")
                page.locator("#accounts").fill("casey, casey-labs")
                page.locator("#app").fill("casey-agent")
                page.locator("#select").click()
                expect(page.locator("#result")).to_contain_text("App selected")
                expect(page.locator("#creation-option")).to_be_hidden()
                expect(page.locator("#new-app")).to_be_hidden()
                step = "retained enrollment and existing installations"
                page.locator("#key").set_input_files(
                    {
                        "name": "fixture.pem",
                        "mimeType": "application/x-pem-file",
                        "buffer": b"fixture-key",
                    }
                )
                page.locator("#enroll").click()
                expect(page.locator("#result")).to_contain_text("Enrollment retained")
                expect(page.locator("#installations")).to_contain_text("casey-labs")
                step = "verified existing bot"
                backend.installed = True
                page.locator("#verify").click()
                expect(page.locator("#result")).to_contain_text("Bot verified")
                assert backend.api_calls == ["GET /apps/casey-agent"]
                assert backend.keys == [b"fixture-key"]
                assert not errors, errors
            except Exception:
                capture_failure(page, args.artifacts, step, errors)
                raise
            finally:
                browser.close()
        wizard.finish()
        print("Existing-bot browser acceptance passed; no new App created.")
    finally:
        wizard.now = 100
        wizard.finish()


if __name__ == "__main__":
    main()
