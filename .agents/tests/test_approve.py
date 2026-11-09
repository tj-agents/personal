from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/approve/scripts/approve.py"
spec = importlib.util.spec_from_file_location("approve", SCRIPT)
approve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approve)
bot = approve.bot_identity

HEAD = "a" * 40
BOT = "app/tomjseery-bot"
SESSION_VARIABLES = ("TJ_RUN_LAUNCH_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")


def ref(number):
    return {"ref": f"github:tj-agents/core:{number}", "provider": "github", "scope": "tj-agents/core",
            "native_id": str(number)}


def session(handle, *items):
    return {"session": handle, "links": [{"item": ref(item), "role": "owner"} for item in items]}


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
    def __init__(self, sessions=None, launches=(), item_prs=None, pulls=None, failing=()):
        self.sessions = sessions or {}
        self.launches = list(launches)
        self.item_prs = item_prs or {}
        self.pulls = pulls or {}
        self.failing = failing
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
            if arguments[:2] == ["show", "--launch-id"]:
                found = next((item for item in self.launches if item["launch_id"] == arguments[2]), None)
                return self.store(command, found and {"launch": found, "session": self.sessions.get(found["session"])})
            found = self.sessions.get(arguments[1])
            return self.store(command, found and {"session": found})
        if tool == "tj":
            pulls = [{"url": address, "state": state, "head": "Feature/x", "title": ""}
                     for address, state in self.item_prs.get(arguments[2], [])]
            return completed(command, json.dumps({"ref": arguments[2], "prs": pulls, "all_merged": False}))
        if arguments[:3] == ["auth", "token", "--user"]:
            return completed(command, "gho_tommy\n")
        if arguments[:2] == ["pr", "view"]:
            return completed(command, json.dumps(self.pulls[arguments[2]]))
        if arguments[:3] == ["pr", "review", "--approve"]:
            if arguments[3] in self.failing:
                return completed(command, returncode=1, stderr="GraphQL: Review cannot be submitted\n")
            return completed(command)
        raise AssertionError(command)

    def commands(self, *prefix):
        return [command for command, _ in self.calls if command[:len(prefix)] == list(prefix)]


class ApproveTests(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(bot, "real_gh", return_value="real-gh"),
                        mock.patch.object(approve, "tool", side_effect=lambda name: name)):
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = {key: value for key, value in os.environ.items() if key not in SESSION_VARIABLES}
        environment.update({"TJ_AGENT": "1", "GH_TOKEN": "bot-identity-unauthenticated", "GITHUB_TOKEN": "ghs_bot",
                            "GH_CONFIG_DIR": "/agent/gh", "CLAUDE_CODE_SESSION_ID": "me"})
        patcher = mock.patch.dict(os.environ, environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.first, self.second, self.approved, self.stale = (url("tj-agents/core", 1), url("tomjseery/notes", 2),
                                                             url("tj-agents/cli", 3), url("tj-agents/docs", 4))
        self.tools = FakeTools(
            sessions={"claude:me": session("claude:me", 10, 11)},
            item_prs={"github:tj-agents/core:10": [(self.first, "open"), (self.approved, "open")],
                      "github:tj-agents/core:11": [(self.first, "open"), (self.second, "open"),
                                                   (self.stale, "open"), (url("tj-agents/core", 5), "merged")]},
            pulls={self.first: details(self.first),
                   self.second: details(self.second),
                   self.approved: details(self.approved, reviews=[review("tomjseery")]),
                   self.stale: details(self.stale, reviews=[review("tomjseery", oid="b" * 40)])})

    def run_approve(self, answer=None):
        out, prompts = io.StringIO(), []

        def ask(prompt):
            prompts.append(prompt)
            return answer

        code = approve.approve(run=self.tools, ask=None if answer is None else ask, out=out)
        return code, out.getvalue(), prompts

    def approvals(self):
        return [command[4] for command in self.tools.commands("real-gh", "pr", "review")]

    def test_without_a_terminal_the_list_is_printed_then_every_pr_approved_as_tommy(self):
        code, out, prompts = self.run_approve()
        self.assertEqual((0, []), (code, prompts))
        self.assertEqual(["core#1  Change 1", "tomjseery/notes#2  Change 2", "docs#4  Change 4",
                          "approved core#1", "approved tomjseery/notes#2", "approved docs#4"], out.splitlines())
        self.assertEqual([self.first, self.second, self.stale], self.approvals())
        token = self.tools.commands("real-gh", "auth", "token")
        self.assertEqual([["real-gh", "auth", "token", "--user", "tomjseery"]], token)
        for command, env in self.tools.calls:
            if command[0] in ("real-gh", "tj"):
                self.assertTrue(all(key not in env for key in ("TJ_AGENT", "GITHUB_TOKEN", "GH_CONFIG_DIR")))
                if command[1:3] != ["auth", "token"]:
                    self.assertEqual("gho_tommy", env["GH_TOKEN"])

    def test_each_linked_item_and_pr_is_read_once(self):
        self.tools.sessions["claude:me"] = session("claude:me", 10, 11, 10)
        self.run_approve()
        self.assertEqual([["tj", "item", "prs", "github:tj-agents/core:10"],
                          ["tj", "item", "prs", "github:tj-agents/core:11"]], self.tools.commands("tj"))
        viewed = [command[3] for command in self.tools.commands("real-gh", "pr", "view")]
        self.assertEqual([self.first, self.approved, self.second, self.stale], viewed)

    def test_only_open_bot_prs_without_tommys_approval_at_head_are_kept(self):
        other, closed, requested = url("tj-agents/core", 6), url("tj-agents/core", 7), url("tj-agents/core", 8)
        self.tools.item_prs = {"github:tj-agents/core:10": [(other, "open"), (closed, "open"), (requested, "open")]}
        self.tools.pulls = {other: details(other, author="tomjseery"), closed: details(closed, state="CLOSED"),
                            requested: details(requested, reviews=[review("tomjseery")], requests=["tomjseery"])}
        self.tools.sessions["claude:me"] = session("claude:me", 10)
        self.run_approve()
        self.assertEqual([requested], self.approvals())

    def test_with_a_terminal_it_asks_once_and_declining_approves_nothing(self):
        for answer in ("", "n", "no", "anything"):
            with self.subTest(answer=answer):
                self.tools.calls.clear()
                code, out, prompts = self.run_approve(answer)
                self.assertEqual((0, ["Approve 3 pull requests? [y/N] "], []), (code, prompts, self.approvals()))
                self.assertTrue(out.endswith("Nothing approved.\n"))

    def test_with_a_terminal_accepting_approves_each_pr(self):
        code, _, prompts = self.run_approve("Y")
        self.assertEqual((0, 1), (code, len(prompts)))
        self.assertEqual([self.first, self.second, self.stale], self.approvals())

    def test_a_failed_approval_fails_the_run_after_trying_every_pr(self):
        self.tools.failing = (self.second,)
        code, out, _ = self.run_approve()
        self.assertEqual(1, code)
        self.assertEqual(3, len(self.approvals()))
        self.assertIn("failed tomjseery/notes#2: GraphQL: Review cannot be submitted", out)
        self.assertIn("approved docs#4", out)

    def test_a_launch_id_resolves_the_launch_item_and_its_bound_session(self):
        os.environ["TJ_RUN_LAUNCH_ID"] = "L1"
        self.tools.launches = [launch("L1", child="claude:bound", item=11)]
        self.tools.sessions = {"claude:bound": session("claude:bound", 10)}
        self.run_approve()
        self.assertEqual([["agent-store", "show", "--launch-id", "L1"]], self.tools.commands("agent-store", "show"))
        self.assertEqual(["github:tj-agents/core:11", "github:tj-agents/core:10"],
                         [command[3] for command in self.tools.commands("tj")])

    def test_a_codex_thread_resolves_its_native_session(self):
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        os.environ["CODEX_THREAD_ID"] = "thread"
        self.tools.sessions = {"codex:thread": session("codex:thread", 10)}
        self.run_approve()
        self.assertEqual([["agent-store", "show", "codex:thread"]], self.tools.commands("agent-store", "show"))
        self.assertEqual([self.first], self.approvals())

    def test_children_are_collected_recursively_through_bound_sessions(self):
        self.tools.sessions = {"claude:me": session("claude:me"), "claude:child": session("claude:child", 10),
                               "codex:grandchild": session("codex:grandchild", 11)}
        self.tools.launches = [launch("L1", parent="claude:me", child="claude:child"),
                               launch("L2", parent="claude:child", child="codex:grandchild"),
                               launch("L3", parent="codex:grandchild", item=11),
                               launch("L4", parent="claude:someone-else", item=12)]
        self.run_approve()
        self.assertEqual(["github:tj-agents/core:10", "github:tj-agents/core:11"],
                         [command[3] for command in self.tools.commands("tj")])
        self.assertEqual([self.first, self.second, self.stale], self.approvals())

    def test_no_session_or_nothing_linked_says_so_and_approves_nothing(self):
        cases = (({}, "No agent session found here; nothing approved.\n"),
                 ({"claude:me": session("claude:me")}, "No work items are linked to this session; nothing approved.\n"))
        for sessions, message in cases:
            with self.subTest(message=message):
                self.tools.sessions, self.tools.calls = sessions, []
                self.assertEqual((0, message), self.run_approve()[:2])
                self.assertEqual([], [command for command, _ in self.tools.calls if command[0] != "agent-store"])
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        self.tools.calls = []
        self.assertEqual((0, "No agent session found here; nothing approved.\n"), self.run_approve()[:2])
        self.assertEqual([], self.tools.calls)

    def test_nothing_waiting_says_so_without_asking(self):
        self.tools.item_prs = {"github:tj-agents/core:10": [(self.approved, "open")]}
        code, out, prompts = self.run_approve("y")
        self.assertEqual((0, [], []), (code, prompts, self.approvals()))
        self.assertEqual("No pull requests await your approval.\n", out)


class TerminalStub(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class MainTests(unittest.TestCase):
    def test_only_an_interactive_stdin_is_asked_and_agent_sessions_are_not_refused(self):
        for tty in (True, False):
            with self.subTest(tty=tty), mock.patch.dict(os.environ, {"TJ_AGENT": "1"}), \
                    mock.patch.object(sys, "stdin", TerminalStub(tty)), \
                    mock.patch.object(approve, "approve", return_value=0) as run:
                self.assertEqual(0, approve.main([]))
                self.assertEqual(input if tty else None, run.call_args.kwargs["ask"])

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
            for name in (source.name, "tomjseery-bot.json"):
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


if __name__ == "__main__":
    unittest.main()
