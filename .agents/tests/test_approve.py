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


def pull(repository, number):
    return {"repository": {"name": repository, "nameWithOwner": f"tj-agents/{repository}"}, "number": number,
            "title": f"Change {number}", "url": f"https://github.com/tj-agents/{repository}/pull/{number}"}


def review(login, state="APPROVED", oid=HEAD):
    return {"author": {"login": login}, "state": state, "commit": {"oid": oid}}


class FakeGh:
    def __init__(self, pulls, details, failing=()):
        self.pulls, self.details, self.failing = pulls, details, failing
        self.calls = []

    def __call__(self, command, env=None, check=False, **captured):
        self.calls.append((command, env))
        arguments = command[1:]
        if arguments[:3] == ["auth", "token", "--user"]:
            return subprocess.CompletedProcess(command, 0, "gho_tommy\n", "")
        if arguments[:2] == ["search", "prs"]:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.pulls), "")
        if arguments[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(command, 0, json.dumps(self.details[arguments[2]]), "")
        if arguments[:3] == ["pr", "review", "--approve"]:
            if arguments[3] in self.failing:
                return subprocess.CompletedProcess(command, 1, "", "GraphQL: Review cannot be requested\n")
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)

    def commands(self, *prefix):
        return [command for command, _ in self.calls if command[1:1 + len(prefix)] == list(prefix)]


class ApproveTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(bot, "real_gh", return_value="real-gh")
        patcher.start()
        self.addCleanup(patcher.stop)
        environment = mock.patch.dict(os.environ, {"GH_TOKEN": "bot-identity-unauthenticated",
                                                   "GITHUB_TOKEN": "ghs_bot", "GH_CONFIG_DIR": "/agent/gh"})
        environment.start()
        self.addCleanup(environment.stop)
        self.core, self.notes, self.cli, self.docs, self.agent = (
            pull("core", 1), pull("notes", 2), pull("cli", 3), pull("docs", 4), pull("agent", 5))
        self.gh = FakeGh([self.core, self.notes, self.cli, self.docs, self.agent], {
            self.core["url"]: {"headRefOid": HEAD, "reviews": [], "reviewRequests": []},
            self.notes["url"]: {"headRefOid": HEAD, "reviews": [review("tomjseery")], "reviewRequests": []},
            self.cli["url"]: {"headRefOid": HEAD, "reviews": [review("tomjseery", oid="b" * 40)],
                              "reviewRequests": []},
            self.docs["url"]: {"headRefOid": HEAD, "reviews": [review("tomjseery")],
                               "reviewRequests": [{"__typename": "User", "login": "tomjseery"}]},
            self.agent["url"]: {"headRefOid": HEAD, "reviews": [review("someone"),
                                                                 review("tomjseery", state="COMMENTED")],
                                "reviewRequests": []},
        })

    def run_approve(self, answer="y", repository=None):
        out, prompts = io.StringIO(), []

        def ask(prompt):
            prompts.append(prompt)
            return answer

        code = approve.approve(repository, run=self.gh, ask=ask, out=out)
        return code, out.getvalue(), prompts

    def test_lists_only_bot_prs_awaiting_tommy_at_their_head(self):
        _, out, prompts = self.run_approve(answer="n")
        search = self.gh.commands("search", "prs")
        self.assertEqual(1, len(search))
        self.assertEqual(["--owner", "tj-agents"], search[0][3:5])
        self.assertEqual("app/tomjseery-bot", search[0][search[0].index("--author") + 1])
        self.assertEqual("open", search[0][search[0].index("--state") + 1])
        listed = [line.split()[0] for line in out.splitlines()[:-1]]
        self.assertEqual(["core#1", "cli#3", "docs#4", "agent#5"], listed)
        self.assertIn("core#1  Change 1", out)
        self.assertEqual(["Approve 4 pull requests? [y/N] "], prompts)

    def test_a_repository_argument_limits_the_search_to_that_tj_agents_repository(self):
        self.run_approve(answer="n", repository="core")
        search = self.gh.commands("search", "prs")[0]
        self.assertEqual(["--repo", "tj-agents/core"], search[3:5])
        self.assertNotIn("--owner", search)

    def test_declining_approves_nothing(self):
        for answer in ("", "n", "no", "anything"):
            with self.subTest(answer=answer):
                self.gh.calls.clear()
                code, out, _ = self.run_approve(answer=answer)
                self.assertEqual(0, code)
                self.assertEqual([], self.gh.commands("pr", "review"))
                self.assertIn("Nothing approved.", out)

    def test_accepting_approves_each_pr_once_as_tommy(self):
        code, out, _ = self.run_approve(answer="Y")
        self.assertEqual(0, code)
        token_calls = [(command, env) for command, env in self.gh.calls if command[1:3] == ["auth", "token"]]
        self.assertEqual([["real-gh", "auth", "token", "--user", "tomjseery"]], [c for c, _ in token_calls])
        self.assertTrue(all(key not in token_calls[0][1] for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR")))
        approvals = [(command, env) for command, env in self.gh.calls if command[1:3] == ["pr", "review"]]
        self.assertEqual([["real-gh", "pr", "review", "--approve", pr["url"]]
                          for pr in (self.core, self.cli, self.docs, self.agent)], [c for c, _ in approvals])
        for _, env in approvals:
            self.assertEqual("gho_tommy", env["GH_TOKEN"])
            self.assertNotIn("GITHUB_TOKEN", env)
            self.assertNotIn("GH_CONFIG_DIR", env)
        self.assertEqual(["approved core#1", "approved cli#3", "approved docs#4", "approved agent#5"],
                         out.splitlines()[-4:])

    def test_a_failed_approval_is_reported_and_fails_the_run_after_trying_every_pr(self):
        self.gh.failing = (self.cli["url"],)
        code, out, _ = self.run_approve()
        self.assertEqual(1, code)
        self.assertEqual(4, len(self.gh.commands("pr", "review")))
        self.assertIn("failed cli#3: GraphQL: Review cannot be requested", out)
        self.assertIn("approved agent#5", out)

    def test_nothing_waiting_says_so_without_asking(self):
        self.gh.pulls = [self.notes]
        code, out, prompts = self.run_approve()
        self.assertEqual((0, [], []), (code, prompts, self.gh.commands("pr", "review")))
        self.assertEqual("No pull requests await your approval.\n", out)

    def test_a_missing_tommy_login_stops_before_listing(self):
        def no_login(command, env=None, check=False, **captured):
            self.gh.calls.append((command, env))
            return subprocess.CompletedProcess(command, 1, "", "no account found for tomjseery\n")

        with self.assertRaisesRegex(approve.ApproveError, "no account found"):
            approve.approve(run=no_login, ask=lambda _: "y", out=io.StringIO())
        self.assertEqual(1, len(self.gh.calls))


class TerminalStub(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


class RefusalTests(unittest.TestCase):
    def refused(self, stdin_tty, stdout_tty, environment):
        error = io.StringIO()
        with mock.patch.dict(os.environ, environment), mock.patch.object(sys, "stdin", TerminalStub(stdin_tty)), \
                mock.patch.object(sys, "stdout", TerminalStub(stdout_tty)), \
                mock.patch.object(approve, "approve") as run, contextlib.redirect_stderr(error):
            code = approve.main([])
        self.assertEqual(2, code)
        run.assert_not_called()
        self.assertEqual(1, len(error.getvalue().splitlines()))
        return error.getvalue()

    def test_refuses_without_an_interactive_terminal(self):
        without_agent = {key: value for key, value in os.environ.items() if key != "TJ_AGENT"}
        with mock.patch.dict(os.environ, without_agent, clear=True):
            for stdin_tty, stdout_tty in ((False, True), (True, False), (False, False)):
                with self.subTest(stdin=stdin_tty, stdout=stdout_tty):
                    self.assertIn("interactive terminal", self.refused(stdin_tty, stdout_tty, {}))

    def test_refuses_in_an_agent_session_even_on_a_terminal(self):
        self.assertIn("agent session", self.refused(True, True, {"TJ_AGENT": "1"}))

    def test_runs_for_tommy_on_his_terminal(self):
        without_agent = {key: value for key, value in os.environ.items() if key != "TJ_AGENT"}
        with mock.patch.dict(os.environ, without_agent, clear=True), \
                mock.patch.object(sys, "stdin", TerminalStub(True)), \
                mock.patch.object(sys, "stdout", TerminalStub(True)), \
                mock.patch.object(approve, "approve", return_value=0) as run:
            self.assertEqual(0, approve.main(["core"]))
        run.assert_called_once_with("core")


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
            environment = {key: value for key, value in os.environ.items() if key != "TJ_AGENT"}
            result = subprocess.run([str(launcher)], env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertIn("tj approve: refusing without an interactive terminal", result.stderr)


if __name__ == "__main__":
    unittest.main()
