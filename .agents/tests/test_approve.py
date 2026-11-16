from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/approve/scripts/approve.py"
spec = importlib.util.spec_from_file_location("approve", SCRIPT)
approve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approve)
bot = approve.bot_identity

HEAD = "a" * 40
BOT = "app/alex-bot"
CONFIGURATION = {"schema_version": 1, "app": {"id": 123, "client_id": "test-client", "slug": "alex-bot", "owner": "alex"},
                 "reviewer": "alex", "accounts": ["alex", "example-tools"], "permissions": {}, "key": None}
SESSION_VARIABLES = ("TJ_RUN_LAUNCH_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")


def ref(number):
    return {"ref": f"github:github.com/example-tools/core:{number}", "provider": "github", "scope": "github.com/example-tools/core",
            "native_id": str(number)}


def session(handle, *items, parent=None):
    return {"session": handle, "parent": parent, "links": [{"item": ref(item), "role": "owner"} for item in items]}


def launch(launch_id, parent=None, child=None, item=None):
    return {"launch_id": launch_id, "parent": parent, "session": child, "item": ref(item) if item else None}


def url(repository, number):
    return f"https://github.com/{repository}/pull/{number}"


def review(login, state="APPROVED", oid=HEAD):
    return {"author": {"login": login}, "state": state, "commit": {"oid": oid}}


def details(address, author=BOT, state="OPEN", reviews=(), requests=()):
    return {"url": address, "title": f"Change {address.rsplit('/', 1)[1]}", "state": state,
            "author": {"login": author}, "headRefOid": HEAD, "reviews": list(reviews),
            "reviewRequests": [{"login": login} for login in requests]}


def completed(command, stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class FakeTools:
    def __init__(self, sessions=None, launches=(), item_prs=None, pulls=None, failing=(), unmergeable=()):
        self.sessions = sessions or {}
        self.launches = list(launches)
        self.item_prs = item_prs or {}
        self.pulls = pulls or {}
        self.failing = failing
        self.unmergeable = unmergeable
        self.login = "alex"
        self.calls = []

    def store(self, command, data):
        if data is None:
            return completed(command, json.dumps({"ok": False, "schema_version": 1,
                                                  "error": {"code": "not-found", "message": "unknown"}}), 3)
        return completed(command, json.dumps({"ok": True, "schema_version": 1, "data": data}))

    def __call__(self, command, env=None, check=False, **captured):
        self.calls.append((command, env))
        tool, arguments = command[0], command[1:]
        if tool == "agent-store":
            if arguments == ["launches"]:
                return self.store(command, {"launches": self.launches})
            if arguments == ["items"]:
                items = {}
                for value in self.sessions.values():
                    for link in value.get("links") or []:
                        entry = items.setdefault(link["item"]["ref"], {"item": link["item"], "sessions": []})
                        entry["sessions"].append({"session": value["session"], "role": link["role"]})
                return self.store(command, {"items": list(items.values())})
            if arguments[:1] == ["sessions"]:
                if len(arguments) != 3 or arguments[1] not in ("--item", "--title"):
                    return completed(command, json.dumps({"ok": False, "schema_version": 1,
                        "error": {"code": "invalid-input", "message": "sessions requires --item or --title"}}), 2)
                if arguments[1] == "--item":
                    values = [value for value in self.sessions.values()
                              if any(link["item"]["ref"] == arguments[2] for link in value.get("links") or [])]
                else:
                    values = [value for value in self.sessions.values() if value.get("title") == arguments[2]]
                return self.store(command, {"sessions": values})
            if arguments[:2] == ["show", "--launch-id"]:
                found = next((item for item in self.launches if item["launch_id"] == arguments[2]), None)
                return self.store(command, found and {"launch": found, "session": self.sessions.get(found["session"])})
            found = self.sessions.get(arguments[1])
            return self.store(command, found and {"session": found})
        if tool == "tj":
            assert arguments[:4] == ["item", "--profile", "github", "prs"]
            pulls = [{"url": address, "state": state, "head": "Feature/x", "title": ""}
                     for address, state in self.item_prs.get(arguments[4], [])]
            return completed(command, json.dumps({"ref": arguments[4], "prs": pulls, "all_merged": False}))
        if arguments == ["auth", "token", "--hostname", "github.com"]:
            return completed(command, "gho_alex\n")
        if arguments[:2] == ["auth", "token"]:
            return completed(command, returncode=1, stderr="no oauth token found for named account")
        if arguments == ["api", "user", "--jq", ".login"]:
            return completed(command, self.login + "\n")
        if arguments[:2] == ["pr", "view"]:
            return completed(command, json.dumps(self.pulls[arguments[2]]))
        if arguments[:3] == ["pr", "review", "--approve"]:
            if arguments[3] in self.failing:
                return completed(command, returncode=1, stderr="GraphQL: Review cannot be submitted\n")
            return completed(command)
        if arguments[:3] == ["pr", "merge", "--auto"]:
            if arguments[-1] in self.unmergeable:
                return completed(command, returncode=1, stderr="Auto merge is not allowed for this repository\n")
            return completed(command)
        raise AssertionError(command)

    def commands(self, *prefix):
        return [command for command, _ in self.calls if command[:len(prefix)] == list(prefix)]


class ApproveTests(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(bot, "real_gh", return_value="real-gh"),
                        mock.patch.object(bot, "tool", side_effect=lambda name: name),
                        mock.patch.object(bot, "identity_config", return_value=CONFIGURATION, create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = {key: value for key, value in os.environ.items() if key not in SESSION_VARIABLES}
        environment.update({"TJ_AGENT": "1", "GH_TOKEN": "bot-identity-unauthenticated", "GITHUB_TOKEN": "ghs_bot",
                            "GH_CONFIG_DIR": "/agent/gh", "CLAUDE_CODE_SESSION_ID": "me"})
        patcher = mock.patch.dict(os.environ, environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.first, self.second, self.approved, self.stale = (url("example-tools/core", 1), url("alex/notes", 2),
                                                             url("example-tools/cli", 3), url("example-tools/docs", 4))
        self.tools = FakeTools(
            sessions={"claude:me": session("claude:me", 10, 11)},
            item_prs={"github:github.com/example-tools/core:10": [(self.first, "open"), (self.approved, "open")],
                      "github:github.com/example-tools/core:11": [(self.first, "open"), (self.second, "open"),
                                                   (self.stale, "open"), (url("example-tools/core", 5), "merged")]},
            pulls={self.first: details(self.first),
                   self.second: details(self.second),
                   self.approved: details(self.approved, reviews=[review("alex")]),
                   self.stale: details(self.stale, reviews=[review("alex", oid="b" * 40)])})

    def run_approve(self):
        out = io.StringIO()
        code = approve.approve(run=self.tools, out=out)
        return code, out.getvalue()

    def approvals(self):
        return [command[4] for command in self.tools.commands("real-gh", "pr", "review")]

    def test_the_list_is_printed_then_every_pr_approved_as_the_configured_human_with_stdin_at_nul(self):
        with open(os.devnull, encoding="utf-8") as nul, mock.patch.object(sys, "stdin", nul):
            code, out = self.run_approve()
        self.assertEqual(0, code)
        self.assertEqual(["example-tools/core#1  Change 1", "alex/notes#2  Change 2", "example-tools/docs#4  Change 4",
                          "approved example-tools/core#1", "merging example-tools/core#1 when its checks pass",
                          "approved alex/notes#2", "merging alex/notes#2 when its checks pass",
                          "approved example-tools/docs#4", "merging example-tools/docs#4 when its checks pass"],
                         out.splitlines())
        self.assertEqual([self.first, self.second, self.stale], self.approvals())
        token = self.tools.commands("real-gh", "auth", "token")
        self.assertEqual([["real-gh", "auth", "token", "--hostname", "github.com"]], token)
        for command, env in self.tools.calls:
            if command[0] in ("real-gh", "tj"):
                self.assertTrue(all(key not in env for key in ("TJ_AGENT", "GITHUB_TOKEN", "GH_CONFIG_DIR")))
                if command[1:3] != ["auth", "token"]:
                    self.assertEqual("gho_alex", env["GH_TOKEN"])

    def test_each_linked_item_and_pr_is_read_once(self):
        self.tools.sessions["claude:me"] = session("claude:me", 10, 11, 10)
        self.run_approve()
        self.assertEqual([["tj", "item", "--profile", "github", "prs", "github:github.com/example-tools/core:10"],
                          ["tj", "item", "--profile", "github", "prs", "github:github.com/example-tools/core:11"]], self.tools.commands("tj"))
        viewed = [command[3] for command in self.tools.commands("real-gh", "pr", "view")]
        self.assertEqual([self.first, self.approved, self.second, self.stale], viewed)

    def test_only_open_bot_prs_without_the_reviewers_approval_at_head_are_kept(self):
        other, closed, requested = url("example-tools/core", 6), url("example-tools/core", 7), url("example-tools/core", 8)
        self.tools.item_prs = {"github:github.com/example-tools/core:10": [(other, "open"), (closed, "open"), (requested, "open")]}
        self.tools.pulls = {other: details(other, author="alex"), closed: details(closed, state="CLOSED"),
                            requested: details(requested, reviews=[review("alex")], requests=["alex"])}
        self.tools.sessions["claude:me"] = session("claude:me", 10)
        self.run_approve()
        self.assertEqual([requested], self.approvals())

    def test_a_failed_approval_fails_the_run_after_trying_every_pr(self):
        self.tools.failing = (self.second,)
        code, out = self.run_approve()
        self.assertEqual(1, code)
        self.assertEqual(3, len(self.approvals()))
        self.assertIn("failed alex/notes#2: GraphQL: Review cannot be submitted", out)
        self.assertIn("approved example-tools/docs#4", out)

    def test_each_approved_pr_arms_squash_auto_merge_at_the_approved_head(self):
        self.tools.failing = (self.second,)
        self.run_approve()
        self.assertEqual([["real-gh", "pr", "merge", "--auto", "--squash", "--match-head-commit", HEAD, address]
                          for address in (self.first, self.stale)], self.tools.commands("real-gh", "pr", "merge"))

    def test_a_failed_auto_merge_is_reported_and_fails_the_run_after_every_pr(self):
        self.tools.unmergeable = (self.first,)
        code, out = self.run_approve()
        self.assertEqual(1, code)
        self.assertIn("approved example-tools/core#1", out)
        self.assertIn("not merging example-tools/core#1: Auto merge is not allowed for this repository", out)
        self.assertIn("merging example-tools/docs#4 when its checks pass", out)

    def test_a_launch_id_resolves_the_launch_item_and_its_bound_session(self):
        os.environ["TJ_RUN_LAUNCH_ID"] = "L1"
        self.tools.launches = [launch("L1", child="claude:bound", item=11)]
        self.tools.sessions = {"claude:bound": session("claude:bound", 10)}
        self.run_approve()
        self.assertEqual([["agent-store", "show", "--launch-id", "L1"]], self.tools.commands("agent-store", "show"))
        self.assertEqual(["github:github.com/example-tools/core:11", "github:github.com/example-tools/core:10"],
                         [command[5] for command in self.tools.commands("tj")])

    def test_a_codex_thread_resolves_its_native_session(self):
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        os.environ["CODEX_THREAD_ID"] = "thread"
        self.tools.sessions = {"codex:thread": session("codex:thread", 10)}
        self.run_approve()
        self.assertEqual([["agent-store", "show", "codex:thread"]], self.tools.commands("agent-store", "show"))
        self.assertEqual([self.first], self.approvals())

    def test_explicit_session_works_without_host_environment_and_overrides_unrelated_launches(
        self,
    ) -> None:
        for inherited in (
            {},
            {"TJ_RUN_LAUNCH_ID": "unrelated", "CLAUDE_CODE_SESSION_ID": "someone-else"},
        ):
            with self.subTest(inherited=inherited):
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if key not in SESSION_VARIABLES
                }
                environment.update(inherited)
                self.tools.sessions = {
                    "codex:chosen": session("codex:chosen", 10),
                    "claude:someone-else": session("claude:someone-else", 11),
                }
                self.tools.launches = [
                    launch("unrelated", child="claude:someone-else", item=11)
                ]
                self.tools.calls = []
                with mock.patch.dict(os.environ, environment, clear=True):
                    code = approve.approve(
                        run=self.tools, out=io.StringIO(), session_handle="codex:chosen"
                    )
                self.assertEqual(0, code)
                self.assertEqual([self.first], self.approvals())
                self.assertEqual(
                    [ref(10)["ref"]],
                    [command[5] for command in self.tools.commands("tj")],
                )
                self.assertNotIn(
                    ["agent-store", "show", "--launch-id", "unrelated"],
                    self.tools.commands("agent-store", "show"),
                )

    def test_unknown_explicit_session_fails_without_using_inherited_session_or_credentials(
        self,
    ) -> None:
        with self.assertRaisesRegex(bot.IdentityError, "unknown.*codex:missing"):
            approve.approve(
                run=self.tools, out=io.StringIO(), session_handle="codex:missing"
            )
        self.assertEqual(
            [["agent-store", "show", "codex:missing"]],
            [command for command, _ in self.tools.calls],
        )

    def test_children_are_collected_recursively_through_bound_sessions(self):
        self.tools.sessions = {"claude:me": session("claude:me"), "claude:child": session("claude:child", 10),
                               "codex:grandchild": session("codex:grandchild", 11)}
        self.tools.launches = [launch("L1", parent="claude:me", child="claude:child"),
                               launch("L2", parent="claude:child", child="codex:grandchild"),
                               launch("L3", parent="codex:grandchild", item=11),
                               launch("L4", parent="claude:someone-else", item=12)]
        self.run_approve()
        self.assertEqual(["github:github.com/example-tools/core:10", "github:github.com/example-tools/core:11"],
                         [command[5] for command in self.tools.commands("tj")])
        self.assertEqual([self.first, self.second, self.stale], self.approvals())

    def test_a_parent_without_items_approves_children_that_record_it_as_their_session_parent(self):
        self.tools.sessions = {"claude:me": session("claude:me"),
                               "claude:child": session("claude:child", 10, parent="claude:me"),
                               "codex:grandchild": session("codex:grandchild", 11, parent="claude:child"),
                               "claude:stranger": session("claude:stranger", 12, parent="claude:someone-else")}
        code, _ = self.run_approve()
        self.assertEqual(0, code)
        self.assertEqual(["github:github.com/example-tools/core:10", "github:github.com/example-tools/core:11"],
                         [command[5] for command in self.tools.commands("tj")])
        self.assertEqual([self.first, self.second, self.stale], self.approvals())

    def test_no_session_or_nothing_linked_says_so_and_approves_nothing(self):
        cases = (({}, "No agent session found here; nothing approved.\n"),
                 ({"claude:me": session("claude:me")}, "No work items are linked to this session; nothing approved.\n"))
        for sessions, message in cases:
            with self.subTest(message=message):
                self.tools.sessions, self.tools.calls = sessions, []
                self.assertEqual((0, message), self.run_approve())
                self.assertEqual([], [command for command, _ in self.tools.calls if command[0] != "agent-store"])
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.tools.calls = []
        self.assertEqual((0, "No agent session found here; nothing approved.\n"), self.run_approve())
        self.assertEqual([], self.tools.calls)

    def test_nothing_waiting_says_so_and_approves_nothing(self):
        self.tools.item_prs = {"github:github.com/example-tools/core:10": [(self.approved, "open")]}
        code, out = self.run_approve()
        self.assertEqual((0, []), (code, self.approvals()))
        self.assertEqual("No pull requests await your approval.\n", out)


class MainTests(unittest.TestCase):
    def test_agent_sessions_are_not_refused(self):
        with mock.patch.dict(os.environ, {"TJ_AGENT": "1"}), \
                mock.patch.object(approve, "approve", return_value=0) as run:
            self.assertEqual(0, approve.main([]))
            run.assert_called_once_with(session_handle=None)

    def test_explicit_session_is_passed_from_the_human_command(self) -> None:
        with mock.patch.object(approve, "approve", return_value=0) as run:
            self.assertEqual(0, approve.main(["--session", "codex:chosen"]))
            run.assert_called_once_with(session_handle="codex:chosen")

    def test_tool_failures_exit_2_with_one_line(self):
        error = io.StringIO()
        with mock.patch.object(approve, "approve", side_effect=approve.ApproveError("agent-store is not on PATH")), \
                contextlib.redirect_stderr(error):
            self.assertEqual(2, approve.main([]))
        self.assertEqual("tj approve: agent-store is not on PATH\n", error.getvalue())


class LauncherTests(unittest.TestCase):
    def test_setup_installs_a_tj_approve_launcher_that_runs_the_installed_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            shim = home / "shim"
            shim.mkdir()
            source = Path(bot.__file__)
            for name in (source.name, "onboarding.py", "onboarding.html"):
                (shim / name).write_bytes((source.parent / name).read_bytes())
            with mock.patch.object(bot, "shim_directory", return_value=shim), \
                    mock.patch.dict(os.environ, {"TJ_BIN_DIR": str(home / "bin")}):
                launcher = bot.install_approve()
                expected = home / "bin" / ("tj-approve.cmd" if bot.WINDOWS else "tj-approve")
                self.assertEqual(expected, launcher)
                self.assertEqual(SCRIPT.read_bytes(), (shim / "approve.py").read_bytes())
                self.assertEqual(bot.approve_launcher(), (launcher, launcher.read_bytes()))
            environment = {key: value for key, value in os.environ.items() if key not in SESSION_VARIABLES}
            result = subprocess.run([str(launcher), "--help"], env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("usage: tj approve", result.stdout)
            self.assertIn("--session HOST:ID", result.stdout)


def test_another_users_bot_and_reviewer_are_used_and_other_accounts_are_not_read() -> None:
    own = url("mira-projects/editor", 1)
    other_bot = url("mira-projects/editor", 2)
    unauthorized = url("unselected/editor", 3)
    human = url("mira-projects/editor", 4)
    spoofed = details(human, author="mira-helper")
    spoofed["author"]["type"] = "User"
    configuration = {**CONFIGURATION, "app": {**CONFIGURATION["app"], "slug": "mira-helper"},
                     "reviewer": "mira", "accounts": ["mira-projects"]}
    tools = FakeTools(sessions={"codex:mira-thread": session("codex:mira-thread", 1)},
                      item_prs={"github:github.com/example-tools/core:1": [(address, "open")
                                                             for address in (own, other_bot, unauthorized, human)]},
                      pulls={own: details(own, author="app/mira-helper"),
                             other_bot: details(other_bot, author="app/someone-else"), human: spoofed})
    tools.login = "mira"
    environment = {key: value for key, value in os.environ.items() if key not in SESSION_VARIABLES}
    environment["CODEX_THREAD_ID"] = "mira-thread"
    with mock.patch.dict(os.environ, environment, clear=True), \
            mock.patch.object(bot, "identity_config", return_value=configuration, create=True), \
            mock.patch.object(bot, "real_gh", return_value="real-gh"), \
            mock.patch.object(bot, "tool", side_effect=lambda name: name):
        assert approve.approve(run=tools, out=io.StringIO()) == 0
    assert tools.commands("real-gh", "auth", "token") == [["real-gh", "auth", "token", "--hostname", "github.com"]]
    assert tools.commands("real-gh", "pr", "review") == [["real-gh", "pr", "review", "--approve", own]]
    assert unauthorized not in [command[3] for command in tools.commands("real-gh", "pr", "view")]


def test_wrong_authenticated_reviewer_blocks_every_approval_and_pr_lookup() -> None:
    tools = FakeTools(sessions={"codex:thread": session("codex:thread", 1)})
    tools.login = "someone-else"
    environment = {key: value for key, value in os.environ.items() if key not in SESSION_VARIABLES}
    environment["CODEX_THREAD_ID"] = "thread"
    with mock.patch.dict(os.environ, environment, clear=True), \
            mock.patch.object(bot, "identity_config", return_value=CONFIGURATION, create=True), \
            mock.patch.object(bot, "real_gh", return_value="real-gh"), \
            mock.patch.object(bot, "tool", side_effect=lambda name: name), \
            pytest.raises(approve.ApproveError, match="configured human reviewer alex"):
        approve.approve(run=tools, out=io.StringIO())
    assert not tools.commands("real-gh", "pr")
    assert not tools.commands("tj")


def test_failed_native_token_lookup_never_includes_credential_output_in_the_error() -> None:
    def failed_lookup(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="credential-must-stay-private", stderr="failed")

    with pytest.raises(approve.ApproveError, match="could not read the native github.com credential") as failure:
        approve.reviewer_environment("real-gh", "alex", failed_lookup)
    assert "credential-must-stay-private" not in str(failure.value)


def test_item_discovery_can_outlast_one_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    address = url("example-tools/core", 1)
    tools = FakeTools(
        sessions={"codex:thread": session("codex:thread", 1)},
        item_prs={ref(1)["ref"]: [(address, "open")]},
        pulls={address: details(address)},
    )

    def slow_item_lookup(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "tj":
            timeout = kwargs["timeout"]
            assert isinstance(timeout, (int, float))
            if timeout <= 60:
                raise subprocess.TimeoutExpired(command, timeout)
        return tools(command, **kwargs)

    monkeypatch.setattr(bot, "identity_config", lambda: CONFIGURATION)
    monkeypatch.setattr(bot, "real_gh", lambda: "real-gh")
    monkeypatch.setattr(bot, "tool", lambda name: name)
    assert approve.approve(
        run=slow_item_lookup, out=io.StringIO(), session_handle="codex:thread"
    ) == 0
    assert tools.commands("real-gh", "pr", "review") == [
        ["real-gh", "pr", "review", "--approve", address]
    ]


def test_discovery_timeout_stops_before_approval_without_exposing_subprocess_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = FakeTools(sessions={"codex:thread": session("codex:thread", 1)})

    def expired_lookup(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "tj":
            raise subprocess.TimeoutExpired(
                command, 120, output="gho_alex", stderr="credential-must-stay-private"
            )
        return tools(command, **kwargs)

    monkeypatch.setattr(bot, "identity_config", lambda: CONFIGURATION)
    monkeypatch.setattr(bot, "real_gh", lambda: "real-gh")
    monkeypatch.setattr(bot, "tool", lambda name: name)
    with pytest.raises(bot.IdentityError, match="tj item.*timed out") as failure:
        approve.approve(
            run=expired_lookup, out=io.StringIO(), session_handle="codex:thread"
        )
    assert "gho_alex" not in str(failure.value)
    assert "credential-must-stay-private" not in str(failure.value)
    assert not tools.commands("real-gh", "pr", "review")


@pytest.mark.parametrize(
    ("failure_detail", "expected_detail"),
    [
        ("HTTP 502: Bad Gateway", "HTTP 502: Bad Gateway"),
        ("connection reset by peer", "connection reset by peer"),
        ("request failed for gho_alex", "request failed for [redacted]"),
    ],
)
def test_failed_reviewer_lookup_reports_the_lookup_failure_without_approving(
    failure_detail: str, expected_detail: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = FakeTools(sessions={"codex:thread": session("codex:thread", 1)})

    def failed_lookup(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[1:] == ["api", "user", "--jq", ".login"]:
            return completed(command, returncode=1, stderr=failure_detail)
        return tools(command, **kwargs)

    monkeypatch.setattr(bot, "identity_config", lambda: CONFIGURATION)
    monkeypatch.setattr(bot, "real_gh", lambda: "real-gh")
    monkeypatch.setattr(bot, "tool", lambda name: name)
    with pytest.raises(approve.ApproveError, match="could not verify the configured human reviewer alex") as failure:
        approve.approve(run=failed_lookup, out=io.StringIO(), session_handle="codex:thread")
    assert expected_detail in str(failure.value)
    assert "gho_alex" not in str(failure.value)
    assert not tools.commands("real-gh", "pr")
    assert not tools.commands("tj")


@pytest.mark.parametrize("author_type", [{"type": "User"}, {"__typename": "User"}, {"is_bot": False}])
def test_a_human_cannot_impersonate_the_configured_app_slug(author_type: dict[str, object]) -> None:
    pull = details(url("example-tools/core", 1), author="alex-bot")
    pull["author"].update(author_type)
    assert not approve.bot_authored(pull, "alex-bot")


def test_descendant_discovery_walks_unlinked_ancestors_and_ignores_unrelated_cycles() -> None:
    tools = FakeTools(sessions={
        "codex:root": session("codex:root"),
        "codex:middle": session("codex:middle", parent="codex:root"),
        "claude:child": session("claude:child", 11, parent="codex:middle"),
        "codex:cycle-a": session("codex:cycle-a", 12, parent="codex:cycle-b"),
        "codex:cycle-b": session("codex:cycle-b", parent="codex:cycle-a"),
        "codex:orphan": session("codex:orphan", 13, parent="codex:missing"),
    }, launches=[launch("unbound-child", parent="codex:middle", item=10),
                 launch("unrelated", parent="codex:stranger", item=14)])
    with mock.patch.object(bot, "tool", return_value="agent-store"):
        found = approve.descendant_items("codex:root", tools)
    assert set(found) == {ref(10)["ref"], ref(11)["ref"]}
    queries = tools.commands("agent-store", "show")
    assert len(queries) == len({command[2] for command in queries})
    assert ["agent-store", "show", "codex:middle"] in queries
    assert not tools.commands("agent-store", "sessions")


def test_descendant_discovery_uses_the_installed_agent_store_contract(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable = shutil.which("agent-store")
    if executable is None:
        pytest.skip("the real agent-store CLI is required for this integration check")
    database = tmp_path / "agent-store.db"
    monkeypatch.setenv("AGENT_STORE_DATABASE", str(database))

    def command(*arguments: str) -> dict:
        result = subprocess.run([executable, "--database", str(database), *arguments],
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        assert result.returncode == 0, result.stdout or result.stderr
        document = json.loads(result.stdout)
        assert document["ok"]
        return document["data"]

    for handle, parent in (("codex:root", None), ("claude:middle", "codex:root"),
                           ("codex:child", "claude:middle"), ("codex:unrelated", None)):
        arguments = ["register", "--session", handle, "--cwd", str(tmp_path)]
        if parent:
            arguments += ["--parent", parent]
        command(*arguments)
    command("link", "--session", "codex:child", "--item", ref(11)["ref"])
    command("link", "--session", "codex:unrelated", "--item", ref(12)["ref"])
    command("launch", "--launch-id", "unbound-descendant", "--host", "codex", "--title", "child",
            "--cwd", str(tmp_path), "--wrapper-pid", str(os.getpid()), "--wrapper-started-at", "2026-11-10T00:00:00Z",
            "--parent", "claude:middle", "--item", ref(10)["ref"])
    with mock.patch.object(bot, "tool", return_value=executable):
        found = approve.descendant_items("codex:root", subprocess.run)
    assert set(found) == {ref(10)["ref"], ref(11)["ref"]}


if __name__ == "__main__":
    unittest.main()
