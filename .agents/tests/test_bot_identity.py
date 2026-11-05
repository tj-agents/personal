from __future__ import annotations

import importlib.util
import io
import json
import contextlib
from collections.abc import Callable, Iterator
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/bot-identity/scripts/bot_identity.py"
spec = importlib.util.spec_from_file_location("bot_identity", SCRIPT)
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

RECORD = {"id": 5397553, "slug": "tomjseery-bot", "client_id": "Iv23liYRkDvGiQXwwzls", "owner": "tomjseery",
          "key": "unused.pem"}
INSTALLED = {"tj-agents": 7, "tomjseery": 8}
ARGV_RECORDER = "import json, sys\nprint(json.dumps(sys.argv[1:]))\n"


def without_agent_settings(environment):
    return {key: value for key, value in environment.items()
            if key not in bot.AGENT_ONLY and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def __call__(self, path, bearer, method="GET"):
        self.calls.append((method, path))
        if path == "/app/installations":
            return [{"account": {"login": "tj-agents"}, "id": 7}]
        return {"token": f"ghs_{len(self.calls)}", "expires_at": "2030-01-01T00:00:00Z"}


class FakeGh:
    def __init__(self, stdout=None, returncode=0):
        self.calls = []
        self.stdout = stdout
        self.returncode = returncode

    def __call__(self, command, env=None, check=False, **captured):
        self.calls.append((command, env))
        return subprocess.CompletedProcess(command, self.returncode, self.stdout if captured else None)


def fake_installed(owners, record):
    return {owner.lower(): INSTALLED[owner.lower()] for owner in owners if owner.lower() in INSTALLED}


class Sandbox(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        for target, value in (("store", self.home / "github-app"), ("shim_directory", self.home / "shim")):
            patcher = mock.patch.object(bot, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.home / "github-app").mkdir()
        record = {**RECORD, "key": str(self.home / "github-app" / "tomjseery-bot.pem")}
        (self.home / "github-app" / "tomjseery-bot.pem").write_text("unused", encoding="utf-8")
        (self.home / "github-app" / "tomjseery-bot.json").write_text(json.dumps(record), encoding="utf-8")
        bot.protect(self.home / "github-app", directory=True)
        bot.protect(self.home / "github-app" / "tomjseery-bot.pem")
        bot.protect(self.home / "github-app" / "tomjseery-bot.json")
        scope = mock.patch.object(bot, "personal_checkout", return_value=self.home)
        scope.start()
        self.addCleanup(scope.stop)

    def patch_environment(self, values):
        patcher = mock.patch.object(os, "environ", {**os.environ, **values})
        patcher.start()
        self.addCleanup(patcher.stop)


class IdentityTests(Sandbox):
    def token(self, owner, github, now=0):
        return bot.installation_token(owner, RECORD, now=now, fetch=github, sign=lambda record: "jwt")

    def test_installed_owner_gets_one_cached_token_and_others_get_none(self):
        github = FakeGitHub()
        self.assertEqual("ghs_2", self.token("TJ-Agents", github))
        self.assertEqual("ghs_2", self.token("tj-agents", github))
        with self.assertRaises(bot.IdentityError):
            self.token("Infonetica", github)
        self.assertEqual(1, sum(method == "POST" for method, _ in github.calls))

    def test_an_expiring_token_is_reissued(self):
        github = FakeGitHub()
        first = self.token("tj-agents", github)
        late = bot.datetime.fromisoformat("2030-01-01T00:00:00+00:00").timestamp() - 60
        self.assertNotEqual(first, self.token("tj-agents", github, now=late))

    def test_owners_come_from_flags_urls_and_api_paths(self):
        cases = {("pr", "merge", "-R", "tj-agents/core"): ["tj-agents"],
                 ("pr", "view", "--repo=Concertable/auth"): ["Concertable"],
                 ("pr", "list", "-Rtomjseery/winwrap"): ["tomjseery"],
                 ("api", "repos/tj-agents/core/pulls/1/merge", "-X", "PUT"): ["tj-agents"],
                 ("api", "https://api.github.com/orgs/tj-agents/rulesets"): ["tj-agents"],
                 ("pr", "view", "-R", "https://github.com/Concertable/b2b"): ["Concertable"],
                 ("pr", "view", "-R", "github.com/Concertable/b2b"): ["Concertable"],
                 ("pr", "review", "--approve", "https://github.com/tj-agents/core/pull/5"): ["tj-agents"],
                 ("pr", "view", "--json", "title", "https://github.com/Infonetica/cris/pull/5"): ["Infonetica"],
                 ("repo", "delete", "tomjseery/notes", "--yes"): ["tomjseery"],
                 ("project", "list", "--owner", "tj-agents"): ["tj-agents"],
                 ("api", "graphql"): []}
        for arguments, owners in cases.items():
            with self.subTest(arguments=arguments):
                self.assertEqual(owners, bot.owners_from_arguments(list(arguments)))

    def test_checkout_owner_comes_only_from_github_remotes(self):
        cases = {"https://x-access-token@github.com/tj-agents/core.git": "tj-agents",
                 "git@github.com:Infonetica/cris.git": "Infonetica",
                 "https://dev.azure.com/infonetica/_git/cris": None,
                 "https://notgithub.com/tj-agents/core": None}
        for url, owner in cases.items():
            with self.subTest(url=url):
                remote = mock.Mock(return_value=subprocess.CompletedProcess([], 0, url + "\n"))
                self.assertEqual(owner, bot.owner_from_checkout(run=remote))


class CredentialTests(Sandbox):
    def ask(self, request, token="ghs_x", fallback="username=tomjseery\npassword=gho_tommy\n"):
        calls = []

        def tommy(command, **kwargs):
            calls.append(kwargs)
            return subprocess.CompletedProcess(command, 0 if fallback else 128, fallback)

        out = io.StringIO()
        with mock.patch.object(bot, "installed", side_effect=fake_installed), \
                mock.patch.object(bot, "installation_token", return_value=token):
            bot.credential("get", io.StringIO(request + "\n"), out, run=tommy)
        return out.getvalue(), calls

    def test_installed_accounts_get_only_the_app_token(self):
        answer, calls = self.ask("protocol=https\nhost=github.com\npath=tj-agents/core.git\n")
        self.assertEqual("username=x-access-token\npassword=ghs_x\n", answer)
        self.assertEqual([], calls)

    def test_an_installed_account_never_falls_back_when_minting_fails(self):
        answer, calls = self.ask("protocol=https\nhost=github.com\npath=tomjseery/notes.git\n", token=None)
        self.assertEqual(("", []), (answer, calls))

    def test_requests_without_an_account_get_nothing(self):
        for request in ("protocol=https\nhost=github.com\n", "protocol=http\nhost=github.com\npath=Infonetica/x\n",
                        "protocol=https\nhost=gist.github.com\npath=tj-agents/x\n"):
            with self.subTest(request=request):
                self.assertEqual(("", []), self.ask(request))

    def test_a_missing_app_record_fails_closed(self):
        (self.home / "github-app" / "tomjseery-bot.json").unlink()
        with mock.patch.object(bot, "tommy_credential") as tommy:
            out = io.StringIO()
            bot.credential("get", io.StringIO("protocol=https\nhost=github.com\npath=tj-agents/x\n\n"), out)
        self.assertEqual("", out.getvalue())
        tommy.assert_not_called()

    def test_a_work_target_does_not_require_personal_enrollment(self):
        (self.home / "github-app" / "tomjseery-bot.json").unlink()
        answer, calls = self.ask("protocol=https\nhost=github.com\npath=Infonetica/cris.git\n")
        self.assertEqual("username=tomjseery\npassword=gho_tommy\n", answer)
        self.assertEqual(1, len(calls))

    def test_other_accounts_use_tommys_own_helpers_without_agent_settings(self):
        self.patch_environment(bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
        answer, calls = self.ask("protocol=https\nhost=github.com\npath=Infonetica/cris.git\n")
        self.assertEqual("username=tomjseery\npassword=gho_tommy\n", answer)
        environment = calls[0]["env"]
        self.assertEqual("0", environment["GIT_TERMINAL_PROMPT"])
        self.assertFalse({"TJ_AGENT", "GH_TOKEN", "GH_CONFIG_DIR", "GIT_CONFIG_COUNT"} & environment.keys())
        self.assertIn("path=Infonetica/cris.git\n", calls[0]["input"])


@unittest.skipUnless(shutil.which("git"), "needs git")
class GitContainmentTests(Sandbox):
    def setUp(self):
        super().setUp()
        global_config = self.home / "gitconfig"
        global_config.write_text(
            '[credential]\n\thelper = "!f() { echo username=generic; echo password=TOMMY_GENERIC; }; f"\n'
            '[credential "https://github.com"]\n\thelper =\n'
            '\thelper = "!f() { echo username=gh; echo password=TOMMY_GH; }; f"\n'
            '[credential "https://gist.github.com"]\n\thelper =\n'
            '\thelper = "!f() { echo username=gh; echo password=TOMMY_GIST; }; f"\n', encoding="utf-8")
        self.tommy = {**without_agent_settings(os.environ), "GIT_CONFIG_NOSYSTEM": "1",
                      "GIT_CONFIG_GLOBAL": str(global_config), "GIT_TERMINAL_PROMPT": "0"}

    def fill(self, request, environment):
        result = subprocess.run(["git", "credential", "fill"], input=request + "\n", env=environment,
                                capture_output=True, text=True, timeout=60, check=False)
        return "".join(line for line in result.stdout.splitlines() if line.startswith("password="))

    def agent(self, helper):
        script = self.home / "helper.py"
        script.write_text(helper, encoding="utf-8")
        settings = bot.agent_environment(script, os.environ["PATH"])
        return {**self.tommy, **{key: value for key, value in settings.items() if key.startswith("GIT_CONFIG_")}}

    def test_github_hosts_reach_only_the_bot_helper(self):
        environment = self.agent("import sys\nsys.stdin.read()\nprint('username=x-access-token')\n"
                                 "print('password=BOT')\n")
        cases = {"protocol=https\nhost=github.com\npath=tj-agents/core.git\n": "password=BOT",
                 "protocol=https\nhost=github.com\n": "password=BOT",
                 "protocol=https\nhost=gist.github.com\n": "",
                 "protocol=https\nhost=api.github.com\n": "",
                 "protocol=http\nhost=github.com\n": "",
                 "protocol=https\nhost=dev.azure.com\n": "password=TOMMY_GENERIC"}
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(expected, self.fill(request, environment))

    def test_the_fallback_reaches_tommys_helpers_and_never_reenters_the_agent_chain(self):
        self.patch_environment(self.agent("print('username=x-access-token')\nprint('password=BOT')\n"))
        os.environ.update({"TJ_AGENT": "1", "GH_TOKEN": bot.UNAUTHENTICATED})
        for key in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT"):
            os.environ[key] = self.tommy[key]
        out = io.StringIO()
        with mock.patch.object(bot, "installed", side_effect=fake_installed):
            bot.credential("get", io.StringIO("protocol=https\nhost=github.com\npath=Infonetica/cris.git\n\n"), out)
        self.assertEqual("username=gh\npassword=TOMMY_GH\n", out.getvalue())


class GhWrapperTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.patch_environment(bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
        self.gh = FakeGh()
        for target, value in (("real_gh", mock.DEFAULT), ("installed", mock.DEFAULT),
                              ("installation_token", mock.DEFAULT)):
            patcher = mock.patch.object(bot, target, value)
            started = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, target, started)
        self.real_gh.return_value = "real-gh"
        self.installed.side_effect = fake_installed
        self.installation_token.side_effect = lambda owner, record: f"ghs_{owner}"

    def environment(self, *arguments, checkout=None):
        self.assertEqual(0, bot.run_gh(list(arguments), run=self.gh, checkout=lambda: checkout))
        command, environment = self.gh.calls[-1]
        self.assertEqual(["real-gh", *arguments], command)
        return environment

    def refused(self, *arguments, checkout=None):
        with self.assertRaises(bot.IdentityError):
            bot.run_gh(list(arguments), run=self.gh, checkout=lambda: checkout)
        self.assertEqual([], self.gh.calls)

    def test_installed_accounts_get_the_app_token_and_the_agent_gh_config(self):
        environment = self.environment("pr", "merge", "5", "-R", "tj-agents/core")
        self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])
        self.assertEqual(str(bot.gh_config_directory()), environment["GH_CONFIG_DIR"])

    def test_naming_an_installed_account_wins_over_an_uncovered_checkout(self):
        environment = self.environment("pr", "review", "--approve", "https://github.com/tomjseery/notes/pull/2",
                                       checkout="Infonetica")
        self.assertEqual("ghs_tomjseery", environment["GH_TOKEN"])

    def test_an_explicit_work_target_overrides_a_personal_checkout(self):
        environment = self.environment("issue", "list", "-R", "Infonetica/cris", checkout="tj-agents")
        self.assertNotIn("GH_TOKEN", environment)
        self.installed.assert_not_called()

    def test_payload_urls_do_not_change_the_target_identity(self):
        cases = (
            ("issue", "create", "--title", "Fixture", "--body", "See https://github.com/cli/cli/issues/1"),
            ("issue", "create", "--body=https://github.com/cli/cli/issues/1", "-R", "tj-agents/personal"),
            ("api", "repos/tj-agents/personal/issues", "-f", "body=https://github.com/cli/cli/issues/1"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                environment = self.environment(*arguments, checkout="tj-agents")
                self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

    def test_a_personal_token_is_removed_when_a_gh_child_enters_work_scope(self):
        personal = self.environment("api", "repos/tj-agents/personal")
        self.patch_environment(personal)
        with mock.patch.object(bot, "personal_checkout", side_effect=bot.IdentityError("not personal")):
            work = self.environment("api", "repos/Infonetica/cris")
        self.assertNotIn("GH_TOKEN", work)
        self.assertNotIn(bot.TOKEN_FINGERPRINT, work)

    def test_an_employer_token_replacing_an_inherited_personal_token_is_preserved(self):
        self.patch_environment(self.environment("api", "repos/tj-agents/personal"))
        self.patch_environment({"GH_TOKEN": "employer-replacement-fixture"})
        with mock.patch.object(bot, "personal_checkout", side_effect=bot.IdentityError("not personal")):
            work = self.environment("api", "repos/Infonetica/cris")
        self.assertEqual("employer-replacement-fixture", work["GH_TOKEN"])
        self.assertNotIn(bot.TOKEN_FINGERPRINT, work)

    def test_a_personal_token_is_not_sent_to_a_different_host(self):
        self.refused("api", "repos/tj-agents/personal", "--hostname", "example.test")
        self.installation_token.assert_not_called()

    def test_command_specific_booleans_preserve_the_explicit_work_target(self):
        for command, flags in (("merge", ("-m", "-r", "-s")), ("review", ("-a", "-r", "-c", "--comment")),
                               ("checkout", ("-f",)), ("co", ("-f",))):
            for flag in flags:
                with self.subTest(command=command, flag=flag):
                    environment = self.environment("pr", command, flag,
                                                   "https://github.com/Infonetica/cris/pull/5", checkout="tj-agents")
                    self.assertNotIn("GH_TOKEN", environment)
        self.installation_token.assert_not_called()

    def test_a_boolean_fork_remote_option_preserves_the_explicit_work_target(self):
        environment = self.environment("repo", "fork", "--remote", "https://github.com/Infonetica/cris",
                                       checkout="tj-agents")
        self.assertNotIn("GH_TOKEN", environment)
        self.installation_token.assert_not_called()

    def test_clone_option_values_do_not_replace_the_repository_target(self):
        for flag in ("-u", "--upstream-remote-name"):
            with self.subTest(flag=flag):
                environment = self.environment("repo", "clone", flag, "upstream", "tj-agents/personal",
                                               "destination/subdirectory", checkout="tomjseery")
                self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

    def test_formatting_payload_urls_preserve_the_checkout_identity(self):
        for command in (("pr", "list"), ("issue", "list"), ("pr", "checks"), ("repo", "list")):
            for flag in ("-q", "-t"):
                with self.subTest(command=command, flag=flag):
                    environment = self.environment(*command, "--json", "url", flag,
                        '.[] | select(.url == "https://github.com/Infonetica/cris/pull/5")', checkout="tj-agents")
                    self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

    def test_issue_create_alias_excludes_payload_urls(self):
        environment = self.environment("issue", "new", "-t", "Fixture", "-b",
                                       "See https://github.com/Infonetica/cris", checkout="tj-agents")
        self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

    def test_api_preview_values_preserve_the_explicit_personal_target(self):
        for flag in ("--preview", "-p"):
            with self.subTest(flag=flag):
                environment = self.environment("api", flag, "nebula", "repos/tj-agents/personal",
                                               checkout="Infonetica")
                self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

    def test_hostname_text_in_a_payload_cannot_override_the_actual_host(self):
        self.refused("api", "repos/tj-agents/personal", "--hostname", "enterprise.example",
                     "-f", "--hostname=github.com")
        self.installation_token.assert_not_called()

    def test_hostname_text_in_a_payload_is_not_an_option(self):
        environment = self.environment("issue", "create", "--title", "--hostname", "--body",
                                       "--hostname=example.test", checkout="tj-agents")
        self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

    def test_gh_repo_target_overrides_the_checkout(self):
        self.patch_environment({"GH_REPO": "Infonetica/cris"})
        environment = self.environment("issue", "list", checkout="tj-agents")
        self.assertNotIn("GH_TOKEN", environment)
        self.installed.assert_not_called()

    def test_mixed_explicit_owners_are_rejected_before_minting(self):
        self.refused("pr", "view", "https://github.com/tj-agents/core/pull/1", "-R", "Infonetica/cris")
        self.installation_token.assert_not_called()

    def test_an_unselected_checkout_never_mints_a_personal_token(self):
        with mock.patch.object(bot, "personal_checkout", side_effect=bot.IdentityError("not personal")):
            environment = self.environment("issue", "list", "-R", "tj-agents/infonetica", checkout="tj-agents")
        self.assertNotIn("GH_TOKEN", environment)
        self.installation_token.assert_not_called()

    def test_an_unselected_checkout_retains_employer_authentication_and_unrelated_git_config(self):
        index = int(os.environ["GIT_CONFIG_COUNT"])
        self.patch_environment({"GH_TOKEN": "employer-fixture", "GITHUB_TOKEN": "other-fixture",
                                f"GIT_CONFIG_KEY_{index}": "core.autocrlf",
                                f"GIT_CONFIG_VALUE_{index}": "false", "GIT_CONFIG_COUNT": str(index + 1)})
        with mock.patch.object(bot, "personal_checkout", side_effect=bot.IdentityError("not personal")):
            environment = self.environment("api", "repos/tj-agents/infonetica")
        self.assertEqual("employer-fixture", environment["GH_TOKEN"])
        self.assertEqual("other-fixture", environment["GITHUB_TOKEN"])
        self.assertEqual("1", environment["GIT_CONFIG_COUNT"])
        self.assertEqual("core.autocrlf", environment["GIT_CONFIG_KEY_0"])
        self.assertNotIn(str(bot.shim_directory()), environment["PATH"].split(os.pathsep))

    def test_uncovered_accounts_fall_through_to_tommys_own_gh(self):
        environment = self.environment("pr", "list", checkout="Infonetica")
        self.assertFalse({"TJ_AGENT", "GH_TOKEN", "GH_CONFIG_DIR", "GIT_CONFIG_COUNT"} & environment.keys())

    def test_commands_without_an_account_stay_unauthenticated(self):
        environment = self.environment("api", "graphql", "-f", "query={viewer{login}}")
        self.assertEqual(bot.UNAUTHENTICATED, environment["GH_TOKEN"])
        self.installed.assert_not_called()

    def test_gh_auth_never_reaches_tommys_credentials(self):
        for arguments in (("auth", "token"), ("auth", "token", "-u", "tomjseery"), ("auth", "git-credential", "get"),
                          ("auth", "logout"), ("auth", "setup-git")):
            with self.subTest(arguments=arguments):
                self.refused(*arguments)
        environment = self.environment("auth", "status", "--show-token", checkout="Infonetica")
        self.assertEqual(bot.UNAUTHENTICATED, environment["GH_TOKEN"])

    def test_a_failed_mint_for_an_installed_account_stops_the_command(self):
        self.installation_token.side_effect = lambda owner, record: None
        self.refused("pr", "create", "-R", "tj-agents/core")

    def test_tommys_own_terminal_runs_the_real_gh_untouched(self):
        del os.environ["TJ_AGENT"]
        self.assertEqual(0, bot.run_gh(["pr", "list"], run=self.gh, checkout=lambda: "tj-agents"))
        self.assertEqual([(["real-gh", "pr", "list"], None)], self.gh.calls)


class ApprovalHandoffTests(GhWrapperTests):
    CORE = "https://github.com/tj-agents/core/pull/7"

    def hand_over(self, *arguments, checkout="tj-agents", stdout=None, returncode=0):
        self.gh.stdout, self.gh.returncode = stdout, returncode
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(returncode, bot.run_gh(list(arguments), run=self.gh, checkout=lambda: checkout))
        return out.getvalue(), err.getvalue()

    def test_a_created_pr_prints_its_filled_approval_command_and_keeps_its_url_on_stdout(self):
        out, err = self.hand_over("pr", "create", "--fill", stdout=self.CORE + "\n")
        self.assertEqual(self.CORE + "\n", out)
        self.assertIn(f"{self.CORE} awaits Tommy's approval", err)
        self.assertIn(bot.approval_command([self.CORE]), err)

    def test_a_payload_url_preserves_bot_authentication_and_the_approval_handoff(self):
        out, err = self.hand_over("pr", "create", "--title", "Fixture", "--body",
                                  "See https://github.com/cli/cli/issues/1", stdout=self.CORE + "\n")
        self.assertEqual(self.CORE + "\n", out)
        self.assertEqual("ghs_tj-agents", self.gh.calls[0][1]["GH_TOKEN"])
        self.assertIn(bot.approval_command([self.CORE]), err)

    def test_create_alias_preserves_bot_authentication_and_the_approval_handoff(self):
        out, err = self.hand_over("pr", "new", "-t", "Fixture", "-b",
                                  "See https://github.com/cli/cli/issues/1", stdout=self.CORE + "\n")
        self.assertEqual(self.CORE + "\n", out)
        self.assertEqual("ghs_tj-agents", self.gh.calls[0][1]["GH_TOKEN"])
        self.assertIn(bot.approval_command([self.CORE]), err)

    def test_a_readied_pr_is_looked_up_with_its_selector_and_handed_over(self):
        _, err = self.hand_over("pr", "ready", "7", "-R", "tj-agents/core", stdout=self.CORE)
        view, environment = self.gh.calls[-1]
        self.assertEqual(["real-gh", "pr", "view", "7", "-R", "tj-agents/core", "--json", "url", "--jq", ".url"],
                         view)
        self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])
        self.assertIn(bot.approval_command([self.CORE]), err)

    def test_drafts_undo_failures_and_uncovered_accounts_hand_nothing_over(self):
        for arguments, checkout, returncode in ((("pr", "create", "--draft"), "tj-agents", 0),
                                                (("pr", "create", "-d"), "tj-agents", 0),
                                                (("pr", "create", "--dry-run"), "tj-agents", 0),
                                                (("pr", "ready", "--undo"), "tj-agents", 0),
                                                (("pr", "create"), "tj-agents", 1),
                                                (("pr", "ready", "4"), "tj-agents", 1),
                                                (("pr", "create"), "Infonetica", 0),
                                                (("pr", "create"), None, 0)):
            with self.subTest(arguments=arguments, checkout=checkout, returncode=returncode):
                self.gh.calls.clear()
                _, err = self.hand_over(*arguments, checkout=checkout, stdout=self.CORE, returncode=returncode)
                self.assertEqual("", err)
                self.assertEqual(1, len(self.gh.calls))

    def test_flag_spellings_given_as_values_still_hand_the_pr_over(self):
        _, err = self.hand_over("pr", "create", "--title", "--draft", "-b", "-w", stdout=self.CORE)
        self.assertIn(bot.approval_command([self.CORE]), err)

    def test_an_unresolved_url_still_points_at_the_command_builder(self):
        _, err = self.hand_over("pr", "create", stdout="")
        self.assertIn("approval <url>", err)

    def test_one_command_approves_every_named_pr_as_tommy_and_stops_on_failure(self):
        other = "https://github.com/tomjseery/notes/pull/2"
        command = bot.approval_command([self.CORE, other])
        self.assertTrue(command.startswith("!env -u GH_TOKEN -u GITHUB_TOKEN -u GH_CONFIG_DIR bash -c 'set -e; "))
        self.assertIn('g="real-gh"', command)
        self.assertIn('auth token --user tomjseery', command)
        self.assertIn(f"for p in {self.CORE} {other}; do", command)

    def test_only_prs_in_the_apps_accounts_get_an_approval_command(self):
        for urls in ([], ["https://github.com/Infonetica/cris/pull/3"], ["https://github.com/tj-agents/core"],
                     [self.CORE + "; rm -rf ~"]):
            with self.subTest(urls=urls), self.assertRaises(bot.IdentityError):
                bot.approval_command(urls)


class AgentEnvironmentTests(Sandbox):
    def settings(self, windows, path):
        with mock.patch.object(bot, "WINDOWS", windows):
            return bot.agent_environment(Path("/s/bot_identity.py"), path)

    def test_git_reaches_github_only_through_the_bot_helper(self):
        environment = self.settings(False, "/usr/bin")
        entries = [(environment[f"GIT_CONFIG_KEY_{index}"], environment[f"GIT_CONFIG_VALUE_{index}"])
                   for index in range(int(environment["GIT_CONFIG_COUNT"]))]
        helpers = [value for key, value in entries if key == "credential.https://github.com.helper"]
        self.assertEqual("", helpers[0])
        self.assertEqual(1, len(helpers[1:]))
        self.assertTrue(helpers[1].endswith('bot_identity.py" credential'))
        cleared = {key for key, value in entries if key.endswith(".helper") and value == ""}
        self.assertEqual({f"credential.{url}.helper" for url in ("https://github.com", "https://*.github.com",
                                                                  "http://github.com", "http://*.github.com")}, cleared)

    def test_gh_has_no_saved_login_in_agent_sessions(self):
        environment = self.settings(False, "/usr/bin")
        self.assertEqual(("1", bot.UNAUTHENTICATED, str(bot.gh_config_directory())),
                         (environment["TJ_AGENT"], environment["GH_TOKEN"], environment["GH_CONFIG_DIR"]))

    def test_the_wrapper_leads_path_once_under_every_spelling(self):
        shim = str(bot.shim_directory())
        posix = self.settings(False, os.pathsep.join(["/usr/bin", shim, "/bin"]))
        self.assertEqual(os.pathsep.join([shim, "/usr/bin", "/bin"]), posix["PATH"])
        self.assertNotIn("Path", posix)
        windows = self.settings(True, "/usr/bin")
        self.assertEqual(windows["PATH"], windows["Path"])

    def test_repeated_path_entries_keep_their_first_search_position(self):
        shim = str(bot.shim_directory())
        path = os.pathsep.join(["/shell", "/shell", shim, "/tools", "/shell", "/tools"])
        self.assertEqual(os.pathsep.join([shim, "/shell", "/tools"]), bot.agent_path(path))

    @unittest.skipIf(os.name == "nt", "POSIX symlink parent traversal")
    def test_symlink_parent_paths_do_not_hide_a_later_executable(self):
        tools, child = self.home / "tools", self.home / "other" / "child"
        tools.mkdir()
        child.mkdir(parents=True)
        (tools / "link").symlink_to(child, target_is_directory=True)
        executable = tools / "gh"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        path = bot.agent_path(os.pathsep.join([str(tools / "link" / ".."), str(tools)]))
        self.assertEqual(executable, Path(shutil.which("gh", path=path)))

    def test_the_agent_path_resolves_gh_to_the_wrapper_before_the_real_gh(self):
        shim, real = bot.shim_directory(), self.home / "real"
        name = "gh.exe" if bot.WINDOWS else "gh"
        for directory in (shim, real):
            directory.mkdir()
            (directory / name).write_bytes(b"")
            (directory / name).chmod(0o755)
        path = bot.agent_environment(Path("/s/bot_identity.py"), str(real))["PATH"]
        self.assertEqual(shim / name, Path(shutil.which("gh", path=path)))


class ShimTests(Sandbox):
    ARGUMENTS = ("pr", "create", "--title", "t", "--body", 'line one\nline "two" 50% & a|b ^c')

    def install(self):
        source = self.home / "bot_identity.py"
        source.write_text(ARGV_RECORDER, encoding="utf-8")
        bot.shim_directory().mkdir()
        for retired in ("gh", "gh.cmd"):
            (bot.shim_directory() / retired).write_text("old", encoding="utf-8")
        bot.install_shims(source)

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_windows_gh_exe_passes_every_argument_through(self):
        self.install()
        self.assertEqual(["bot_identity.py", "gh.exe", "tomjseery-bot.json"],
                         sorted(path.name for path in bot.shim_directory().iterdir()))
        result = subprocess.run([str(bot.shim_directory() / "gh.exe"), *self.ARGUMENTS], capture_output=True,
                                text=True, timeout=60, check=True)
        self.assertEqual(["gh", *self.ARGUMENTS], json.loads(result.stdout))

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell")
    def test_powershell_resolves_the_wrapper_from_the_agent_path(self):
        self.install()
        environment = {**os.environ, "PATH": bot.agent_environment(Path("/s/x.py"), os.environ["PATH"])["PATH"]}
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                 "(Get-Command gh).Source; gh pr view 'a b'"], env=environment,
                                capture_output=True, text=True, timeout=120, check=True)
        source, argv = result.stdout.strip().splitlines()
        self.assertEqual(bot.shim_directory() / "gh.exe", Path(source))
        self.assertEqual(["gh", "pr", "view", "a b"], json.loads(argv))

    @unittest.skipIf(os.name == "nt", "POSIX wrapper")
    def test_posix_gh_script_passes_every_argument_through(self):
        self.install()
        result = subprocess.run([str(bot.shim_directory() / "gh"), *self.ARGUMENTS], capture_output=True, text=True,
                                timeout=60, check=True)
        self.assertEqual(["gh", *self.ARGUMENTS], json.loads(result.stdout))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.environment = {"TJ_AGENT": "1", "GH_TOKEN": "x", "PATH": "/shim:/usr/bin", "GIT_CONFIG_COUNT": "1",
                            "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": 'say "hi"'}

    def test_codex_keeps_other_settings_and_is_idempotent(self):
        path = self.root / "config.toml"
        path.write_text('model = "x"\n\n[shell_environment_policy.set]\nKEEP = "1"\nGIT_CONFIG_KEY_9 = "old"\n'
                        'Path = "old"\n\n[projects.a]\ntrust_level = "trusted"\n', encoding="utf-8")
        bot.update_codex(path, self.environment)
        once = path.read_text(encoding="utf-8")
        bot.update_codex(path, self.environment)
        self.assertEqual(once, path.read_text(encoding="utf-8"))
        parsed = bot_toml(once)
        self.assertEqual({"KEEP": "1", **self.environment}, parsed["shell_environment_policy"]["set"])
        self.assertEqual("trusted", parsed["projects"]["a"]["trust_level"])
        self.assertEqual("x", parsed["model"])

    def test_claude_merges_env_and_denies_mcp_writes(self):
        path = self.root / "settings.json"
        path.write_text(json.dumps({"env": {"KEEP": "1", "GIT_CONFIG_KEY_9": "old", "Path": "old"},
                                    "permissions": {"deny": ["Bash(rm:*)"]}}), encoding="utf-8")
        bot.update_claude(path, self.environment)
        settings = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({"KEEP": "1", **self.environment}, settings["env"])
        self.assertIn("Bash(rm:*)", settings["permissions"]["deny"])
        self.assertIn("mcp__github__merge_pull_request", settings["permissions"]["deny"])

    def test_setup_takes_the_wrapper_back_out_of_the_posix_profile(self):
        shim = self.root / "shim"
        profile = self.root / ".profile"
        profile.write_text(f'export A=1\nexport PATH="{shim}:$PATH"  # bot-identity\nexport B=2\n', encoding="utf-8")
        with mock.patch.object(bot, "WINDOWS", False), mock.patch.object(bot.Path, "home", return_value=self.root):
            self.assertTrue(bot.remove_user_path(shim))
            self.assertFalse(bot.remove_user_path(shim))
        self.assertEqual("export A=1\nexport B=2\n", profile.read_text(encoding="utf-8"))


class EnrollmentTests(Sandbox):
    @contextlib.contextmanager
    def running_wizard(self, fetch: Callable[..., object], *, setup: bool = False) -> Iterator[tuple[str, threading.Thread, list[str]]]:
        urls: list[str] = []
        errors: list[str] = []
        started = threading.Event()
        elapsed = [0.0]

        def opened(url: str) -> bool:
            urls.append(url)
            started.set()
            return True

        onboard = bot.onboard

        def run_wizard() -> None:
            onboard(open_browser=opened, fetch=fetch, sign=lambda record: "jwt", clock=lambda: elapsed[0])

        def serve() -> None:
            try:
                if setup:
                    with mock.patch.object(bot, "onboard", side_effect=run_wizard):
                        bot.setup(onboard_key=True)
                else:
                    run_wizard()
            except bot.IdentityError as error:
                errors.append(str(error))

        with contextlib.redirect_stdout(io.StringIO()):
            thread = threading.Thread(target=serve)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                yield urls[0], thread, errors
            finally:
                elapsed[0] = bot.ENROLLMENT_SECONDS + 1
                thread.join(3)
                self.assertFalse(thread.is_alive())

    def wizard_status(self, endpoint: str, body: bytes = b"") -> dict[str, object]:
        request = urllib.request.Request(endpoint, data=body, method="POST", headers={
            "Origin": endpoint.split("/enroll/", 1)[0],
            "X-Bot-Identity-State": endpoint.rsplit("/", 1)[1],
        })
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual("application/json", response.headers.get_content_type())
            result = json.load(response)
        self.assertIsInstance(result, dict)
        return result

    def test_existing_key_wizard_advances_permissions_installations_and_acceptance_without_pem(self) -> None:
        required = {"repository_creation": "write", "organization_projects": "write"}
        app_permissions: dict[str, str] = {"repository_creation": "write"}
        installation_permissions: dict[str, str] = {}
        installed = [False]

        def fetch(path: str, bearer: str, method: str = "GET") -> object:
            delegate, _ = self.readiness_fetch(app_permissions, installation_permissions)
            value = delegate(path, bearer, method)
            return value if path == "/app" or installed[0] else []

        with mock.patch.object(bot, "persist_enrollment") as persist, self.running_wizard(fetch) as (endpoint, thread, errors):
            page = urllib.request.urlopen(endpoint, timeout=2)
            with page:
                self.assertIn('id=key-step hidden', page.read().decode())
            status = self.wizard_status(endpoint)
            self.assertEqual("app", status["stage"])
            self.assertFalse(status["needs_key"])
            self.assertEqual("https://github.com/settings/apps/tomjseery-bot", status["url"])
            self.assertTrue(thread.is_alive())
            app_permissions.update(required)
            status = self.wizard_status(endpoint)
            self.assertEqual("installation", status["stage"])
            self.assertIn("tomjseery, tj-agents, concertable", status["message"])
            self.assertTrue(thread.is_alive())
            installed[0] = True
            status = self.wizard_status(endpoint)
            self.assertEqual("installation", status["stage"])
            self.assertEqual("https://github.com/organizations/tj-agents/settings/installations/7", status["url"])
            installation_permissions.update(required)
            self.assertEqual("ready", self.wizard_status(endpoint)["stage"])
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual([], errors)
        persist.assert_not_called()

    def test_existing_key_wizard_retries_api_failures_without_reenrollment(self) -> None:
        required = {"repository_creation": "write", "organization_projects": "write"}
        delegate, _ = self.readiness_fetch(required, required)
        failure: list[int | None] = [403]

        def fetch(path: str, bearer: str, method: str = "GET") -> object:
            if failure:
                raise bot.GitHubError("secret fixture must not appear", failure.pop())
            return delegate(path, bearer, method)

        with mock.patch.object(bot, "persist_enrollment") as persist, self.running_wizard(fetch) as (endpoint, thread, errors):
            for status_code in (403, None):
                if status_code is None:
                    failure.append(None)
                status = self.wizard_status(endpoint)
                self.assertEqual("retry", status["stage"])
                self.assertFalse(status["needs_key"])
                self.assertNotIn("secret fixture", json.dumps(status))
                self.assertTrue(thread.is_alive())
            self.assertEqual("ready", self.wizard_status(endpoint)["stage"])
            thread.join(2)
            self.assertEqual([], errors)
        persist.assert_not_called()

    def test_onboard_setup_guides_existing_enrollment_then_continues_in_same_invocation(self) -> None:
        with mock.patch.object(bot, "onboard") as onboard, mock.patch.object(bot, "verify_ready"), \
                mock.patch.object(bot, "install_shims", return_value=Path("fixture.py")) as install, \
                mock.patch.object(bot, "gh_config_directory", return_value=self.home / "gh"), \
                mock.patch.object(bot, "update_claude"), mock.patch.object(bot, "update_codex"), \
                mock.patch.object(bot, "remove_user_path"), mock.patch.object(bot, "validate_remote_app"), \
                contextlib.redirect_stdout(io.StringIO()):
            bot.setup(onboard_key=True)
        onboard.assert_called_once_with()
        install.assert_called_once()

    def test_http_wizard_returns_to_setup_only_after_full_readiness(self) -> None:
        required = {"repository_creation": "write", "organization_projects": "write"}
        accepted: dict[str, str] = {}
        fetch, _ = self.readiness_fetch(required, accepted)
        verify = bot.verify_ready

        def verify_local(record: dict[str, object], **kwargs: object) -> None:
            verify(record, fetch=fetch, sign=lambda value: "jwt")

        with mock.patch.object(bot, "verify_ready", side_effect=verify_local), \
                mock.patch.object(bot, "install_shims", return_value=Path("fixture.py")) as install, \
                mock.patch.object(bot, "gh_config_directory", return_value=self.home / "gh"), \
                mock.patch.object(bot, "update_claude") as claude, mock.patch.object(bot, "update_codex") as codex, \
                mock.patch.object(bot, "remove_user_path"), \
                self.running_wizard(fetch, setup=True) as (endpoint, thread, errors):
            self.assertEqual("installation", self.wizard_status(endpoint)["stage"])
            install.assert_not_called()
            claude.assert_not_called()
            codex.assert_not_called()
            accepted.update(required)
            self.assertEqual("ready", self.wizard_status(endpoint)["stage"])
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual([], errors)
            install.assert_called_once()
            claude.assert_called_once()
            codex.assert_called_once()

    def remove_enrollment(self):
        for path in (self.home / "github-app").glob("tomjseery-bot.*"):
            path.unlink()

    def readiness_fetch(self, app_permissions, tj_agents_permissions):
        calls = []

        def fetch(path, bearer, method="GET"):
            calls.append((method, path))
            if path == "/app":
                return {**{key: value for key, value in RECORD.items() if key != "key"},
                        "owner": {"login": RECORD["owner"]}, "permissions": app_permissions}
            self.assertEqual("/app/installations", path)
            return [
                {"id": 7, "account": {"login": "tj-agents"}, "target_type": "Organization",
                 "permissions": tj_agents_permissions},
                {"id": 8, "account": {"login": "tomjseery"}, "target_type": "User", "permissions": {}},
                {"id": 9, "account": {"login": "concertable"}, "target_type": "Organization", "permissions": {}},
            ]

        return fetch, calls

    def test_readiness_reports_the_app_settings_page_for_a_missing_declaration(self):
        fetch, calls = self.readiness_fetch(
            {"organization_projects": "write"},
            {"repository_creation": "write", "organization_projects": "write"},
        )
        with self.assertRaisesRegex(bot.IdentityError,
                                    r"pinned GitHub App does not grant repository_creation:write; update it at "
                                    r"https://github.com/settings/apps/tomjseery-bot"):
            bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app")], calls)

    def test_readiness_reports_the_tj_agents_installation_settings_page_pending_acceptance(self):
        fetch, calls = self.readiness_fetch(
            {"repository_creation": "write", "organization_projects": "write"},
            {"organization_projects": "write"},
        )
        with self.assertRaisesRegex(bot.IdentityError,
                                    r"tj-agents App installation does not grant repository_creation:write; update it at "
                                    r"https://github.com/organizations/tj-agents/settings/installations/7"):
            bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_rejects_missing_or_read_only_projects_on_the_app(self) -> None:
        for grant in ({}, {"organization_projects": "read"}):
            with self.subTest(grant=grant):
                fetch, calls = self.readiness_fetch(
                    {"repository_creation": "write", **grant},
                    {"repository_creation": "write", "organization_projects": "write"},
                )
                with self.assertRaisesRegex(
                    bot.IdentityError,
                    r"pinned GitHub App does not grant organization_projects:write; update it at "
                    r"https://github.com/settings/apps/tomjseery-bot",
                ):
                    bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
                self.assertEqual([("GET", "/app")], calls)

    def test_readiness_rejects_projects_not_accepted_by_the_tj_agents_installation(self) -> None:
        for grant in ({}, {"organization_projects": None}, {"organization_projects": "read"}):
            with self.subTest(grant=grant):
                fetch, calls = self.readiness_fetch(
                    {"repository_creation": "write", "organization_projects": "write"},
                    {"repository_creation": "write", **grant},
                )
                with self.assertRaisesRegex(
                    bot.IdentityError,
                    r"tj-agents App installation does not grant organization_projects:write; update it at "
                    r"https://github.com/organizations/tj-agents/settings/installations/7",
                ):
                    bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
                self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_accepts_the_declared_and_accepted_required_capabilities(self):
        fetch, calls = self.readiness_fetch(
            {"repository_creation": "write", "organization_projects": "write"},
            {"repository_creation": "write", "organization_projects": "write"},
        )
        bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_rejects_administration_write_on_the_app_or_tj_agents_installation(self):
        cases = (
            ("App", {"repository_creation": "write", "organization_projects": "write", "administration": "write"},
             {"repository_creation": "write", "organization_projects": "write"}, "settings/apps/tomjseery-bot"),
            ("installation", {"repository_creation": "write", "organization_projects": "write"},
             {"repository_creation": "write", "organization_projects": "write", "administration": "write"},
             "organizations/tj-agents/settings/installations/7"),
        )
        for subject, app_permissions, installation_permissions, url in cases:
            with self.subTest(subject=subject):
                fetch, _ = self.readiness_fetch(app_permissions, installation_permissions)
                with self.assertRaisesRegex(bot.IdentityError,
                                            rf"grants forbidden administration:write; remove it at https://github.com/{url}"):
                    bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")

    def test_invalid_or_wrong_app_key_never_creates_an_enrollment_record(self):
        self.remove_enrollment()
        with self.assertRaises(bot.IdentityError):
            bot.persist_enrollment(b"not a PEM")
        self.assertFalse((self.home / "github-app" / "tomjseery-bot.json").exists())

        def wrong_app(path, bearer, method="GET"):
            return {"id": 1, "client_id": "wrong", "slug": "wrong", "owner": {"login": "wrong"}}

        pem = b"-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n"
        with self.assertRaises(bot.IdentityError):
            bot.persist_enrollment(pem, fetch=wrong_app, sign=lambda record: "jwt")
        self.assertFalse((self.home / "github-app" / "tomjseery-bot.json").exists())
        self.assertFalse((self.home / "github-app" / ".candidate.pem").exists())

    def test_missing_protected_installation_fails_closed_without_tommy_fallback(self):
        self.patch_environment(bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
        with mock.patch.object(bot, "installed", return_value={}), \
                mock.patch.object(bot, "tommy_environment") as tommy:
            with self.assertRaises(bot.IdentityError):
                bot.agent_gh_environment(["pr", "list", "-R", "tomjseery/notes"], None)
        tommy.assert_not_called()

    def test_failed_readiness_does_not_mutate_agent_hosts(self):
        with mock.patch.object(bot, "verify_ready", side_effect=bot.IdentityError("missing installation")), \
                mock.patch.object(bot, "install_shims") as install, \
                mock.patch.object(bot, "update_claude") as claude, \
                mock.patch.object(bot, "update_codex") as codex:
            with self.assertRaises(bot.IdentityError):
                bot.setup()
        install.assert_not_called()
        claude.assert_not_called()
        codex.assert_not_called()

    def test_check_is_read_only_and_setup_flags_are_exclusive(self):
        with mock.patch.object(bot, "verify_ready"), mock.patch.object(bot, "verify_host_setup"), \
                mock.patch.object(bot, "install_shims") as install:
            with contextlib.redirect_stdout(io.StringIO()):
                bot.setup(check=True)
        install.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bot.main(["setup", "--check", "--onboard"])

    def test_private_key_write_is_private_on_posix(self):
        if os.name == "nt":
            self.skipTest("Windows ACL exercised by protect() during the Windows suite")
        path = self.home / "github-app" / "tomjseery-bot.pem"
        bot.write_key(path, b"private")
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
        path.chmod(0o644)
        with self.assertRaises(bot.IdentityError):
            bot.require_private_permissions(path)

    @unittest.skipUnless(os.name == "nt", "Windows ACL")
    def test_private_key_write_applies_a_private_windows_acl(self):
        path = self.home / "github-app" / "tomjseery-bot.pem"
        bot.write_key(path, b"private")
        bot.require_private_permissions(path)
        acl = subprocess.run(["icacls", str(path)], text=True, capture_output=True, check=True).stdout
        self.assertIn("SYSTEM:", acl)
        self.assertNotIn("BUILTIN\\Users", acl)

    def test_check_rejects_broadened_secret_permissions(self):
        path = self.home / "github-app" / "tomjseery-bot.pem"
        bot.require_private_permissions(path)
        if bot.WINDOWS:
            subprocess.run(["icacls", str(path), "/grant", "*S-1-5-32-544:(R)"],
                           capture_output=True, check=True)
        else:
            path.chmod(0o644)
        with self.assertRaisesRegex(bot.IdentityError, "permissions are unsafe"):
            bot.require_private_permissions(path)

    def test_revoked_key_requests_one_replacement_and_retains_it_while_installations_are_pending(self) -> None:
        required = {"repository_creation": "write", "organization_projects": "write"}
        delegate, _ = self.readiness_fetch(required, required)
        revoked = [True]
        installed = [False]

        def fetch(path: str, bearer: str, method: str = "GET") -> object:
            if revoked[0]:
                raise bot.GitHubError("revoked fixture", 401)
            value = delegate(path, bearer, method)
            return value if path == "/app" or installed[0] else []

        def enroll(key: bytes, **kwargs: object) -> dict[str, object]:
            self.assertEqual(b"replacement fixture", key)
            revoked[0] = False
            return RECORD

        with mock.patch.object(bot, "persist_enrollment", side_effect=enroll) as persist, \
                self.running_wizard(fetch) as (endpoint, thread, errors):
            self.assertEqual("key", self.wizard_status(endpoint)["stage"])
            self.assertTrue(self.wizard_status(endpoint)["needs_key"])
            self.assertEqual("installation", self.wizard_status(endpoint, b"replacement fixture")["stage"])
            self.assertFalse(self.wizard_status(endpoint)["needs_key"])
            self.assertEqual("installation", self.wizard_status(endpoint)["stage"])
            self.assertTrue(thread.is_alive())
            installed[0] = True
            self.assertEqual("ready", self.wizard_status(endpoint)["stage"])
            thread.join(2)
            self.assertEqual([], errors)
        persist.assert_called_once()

    def test_missing_key_enrolls_once_and_does_not_accept_replacement_uploads(self) -> None:
        self.remove_enrollment()
        required = {"repository_creation": "write", "organization_projects": "write"}
        delegate, _ = self.readiness_fetch(required, required)
        installed = [False]

        def fetch(path: str, bearer: str, method: str = "GET") -> object:
            value = delegate(path, bearer, method)
            return value if path == "/app" or installed[0] else []

        with mock.patch.object(bot, "persist_enrollment", return_value=RECORD) as persist, \
                self.running_wizard(fetch) as (endpoint, thread, errors):
            self.assertEqual("key", self.wizard_status(endpoint)["stage"])
            persist.assert_not_called()
            self.assertEqual("installation", self.wizard_status(endpoint, b"new key fixture")["stage"])
            self.assertFalse(self.wizard_status(endpoint)["needs_key"])
            self.assertEqual("retry", self.wizard_status(endpoint, b"unwanted replacement")["stage"])
            self.assertFalse(self.wizard_status(endpoint)["needs_key"])
            installed[0] = True
            self.assertEqual("ready", self.wizard_status(endpoint)["stage"])
            thread.join(2)
            self.assertEqual([], errors)
        persist.assert_called_once_with(b"new key fixture", fetch=fetch, sign=mock.ANY)

    def test_browser_open_failure_closes_the_loopback_socket(self) -> None:
        for failure in (False, OSError("sensitive fixture"), bot.webbrowser.Error("sensitive fixture")):
            urls: list[str] = []

            def opened(url: str) -> bool:
                urls.append(url)
                if isinstance(failure, Exception):
                    raise failure
                return failure

            with self.subTest(failure=type(failure).__name__), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(bot.IdentityError, "could not open") as raised:
                    bot.onboard(open_browser=opened)
                self.assertNotIn("sensitive fixture", str(raised.exception))
                with self.assertRaises(urllib.error.URLError):
                    urllib.request.urlopen(urls[0], timeout=0.2)

    def test_timeout_closes_pending_wizard_without_changing_enrollment(self) -> None:
        fetch, _ = self.readiness_fetch({}, {})
        with mock.patch.object(bot, "persist_enrollment") as persist:
            with self.running_wizard(fetch) as (endpoint, _, errors):
                self.assertEqual("app", self.wizard_status(endpoint)["stage"])
            self.assertEqual(["GitHub App enrollment did not complete within 10 minutes"], errors)
            with self.assertRaises(urllib.error.URLError):
                urllib.request.urlopen(endpoint, timeout=0.2)
        persist.assert_not_called()

    def test_plain_setup_and_check_never_open_the_onboarding_browser(self) -> None:
        with mock.patch.object(bot, "onboard") as onboard, \
                mock.patch.object(bot, "verify_ready", side_effect=bot.IdentityError("not ready")), \
                mock.patch.object(bot, "install_shims") as install:
            for check in (False, True):
                with self.subTest(check=check), self.assertRaises(bot.IdentityError):
                    bot.setup(check=check)
        onboard.assert_not_called()
        install.assert_not_called()

    def test_loopback_enrollment_rejects_host_origin_state_and_large_uploads(self):
        url, started, errors = [], threading.Event(), []
        elapsed = [0]

        def opened(value):
            url.append(value)
            started.set()
            return True

        def serve():
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    bot.onboard(open_browser=opened, clock=lambda: elapsed[0])
            except bot.IdentityError as error:
                errors.append(str(error))

        with contextlib.redirect_stdout(io.StringIO()):
            thread = threading.Thread(target=serve)
            thread.start()
            self.assertTrue(started.wait(2))
            endpoint = url[0]
            nonce = endpoint.rsplit("/", 1)[1]
            cases = (
                urllib.request.Request(endpoint, headers={"Host": "evil.example"}),
                urllib.request.Request(endpoint, data=b"x", method="POST", headers={
                    "Origin": "http://evil.example", "X-Bot-Identity-State": nonce}),
                urllib.request.Request(endpoint, data=b"", method="POST", headers={
                    "Origin": endpoint.split("/enroll/", 1)[0], "X-Bot-Identity-State": "wrong"}),
                urllib.request.Request(endpoint, data=b"", method="POST", headers={
                    "Origin": endpoint.split("/enroll/", 1)[0], "X-Bot-Identity-State": nonce,
                    "Content-Length": str(bot.MAX_ENROLLMENT_BYTES + 1)}),
            )
            for request, expected in zip(cases, (404, 403, 403, 413)):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(expected, raised.exception.code)
                raised.exception.close()
            elapsed[0] = bot.ENROLLMENT_SECONDS + 1
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)


class FreshSetupTests(unittest.TestCase):
    def test_setup_and_fresh_wrapper_use_the_bot_without_touching_human_settings(self):
        with tempfile.TemporaryDirectory(prefix="bot setup ü ") as temporary:
            home = Path(temporary)
            project = home / "personal project"
            project.mkdir()
            subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
            (project / ".agents").mkdir()
            (project / ".agents/plugins.json").write_text(json.dumps({
                "plugins": ["personal@tj-agents"],
                "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
            }), encoding="utf-8")
            real = home / "real gh"
            real.mkdir()
            script = real / "fake-gh.py"
            script.write_text("import os\nprint('BOT' if os.environ.get('GH_TOKEN') == 'fixture-token' else 'WRONG')\n",
                              encoding="utf-8")
            launcher = real / ("gh.exe" if bot.WINDOWS else "gh")
            if bot.WINDOWS:
                launcher.write_bytes(bot.windows_executable(script))
            else:
                launcher.write_text(f'#!{sys.executable}\n' + script.read_text(encoding="utf-8"), encoding="utf-8")
                launcher.chmod(0o755)
            environment = {**without_agent_settings(os.environ), "HOME": str(home), "USERPROFILE": str(home),
                           "CLAUDE_CONFIG_DIR": str(home / "claude"), "CODEX_HOME": str(home / "codex"),
                           "PATH": os.pathsep.join([str(real), os.environ["PATH"]])}
            with mock.patch.object(os, "environ", environment):
                key = bot.store() / "tomjseery-bot.pem"
                bot.write_key(key, b"unused fixture key")
                bot.write_private(bot.store() / "tomjseery-bot.json", {**RECORD, "key": str(key)})
                with mock.patch.object(bot, "verify_ready"), mock.patch.object(bot, "remove_user_path"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    bot.setup(root=project)
                    bot.setup(check=True, root=project)
                    original_path = os.environ["PATH"]
                    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(real), original_path])}):
                        bot.setup(check=True, root=project)
                    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(home / "new tools"), original_path])}):
                        with self.assertRaisesRegex(bot.IdentityError, "host settings are stale"):
                            bot.setup(check=True, root=project)
                    entries = original_path.split(os.pathsep)
                    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([*entries[1:], entries[0]])}):
                        with self.assertRaisesRegex(bot.IdentityError, "host settings are stale"):
                            bot.setup(check=True, root=project)
                    claude = project / ".claude/settings.local.json"
                    settings = json.loads(claude.read_text(encoding="utf-8"))
                    settings["permissions"]["deny"].remove(bot.MCP_DENY[0])
                    claude.write_text(json.dumps(settings), encoding="utf-8")
                    with self.assertRaisesRegex(bot.IdentityError, "write restrictions are missing"):
                        bot.setup(check=True, root=project)
                    del settings["permissions"]
                    claude.write_text(json.dumps(settings), encoding="utf-8")
                    with self.assertRaisesRegex(bot.IdentityError, "host settings are missing"):
                        bot.setup(check=True, root=project)
                    bot.setup(root=project)
                    bot.setup(check=True, root=project)
                bot.write_private(bot.store() / "tokens/tomjseery-bot-installations.json", INSTALLED)
                bot.write_private(bot.store() / "tokens/tomjseery-bot-tomjseery.json",
                                  {"token": "fixture-token", "expires": 4102444800})
                settings = json.loads((project / ".claude/settings.local.json").read_text(encoding="utf-8"))["env"]
                result = subprocess.run([str(bot.shim_directory() / launcher.name), "api", "repos/tomjseery/smoke"],
                                        cwd=project, env={**environment, **settings}, capture_output=True,
                                        text=True, timeout=30, check=True)
                self.assertEqual("BOT", result.stdout.strip())
                self.assertNotIn("TJ_AGENT", os.environ)
                self.assertFalse((home / "claude/settings.json").exists())
                self.assertFalse((home / "codex/config.toml").exists())


class ScopeTests(unittest.TestCase):
    def test_setup_refuses_work_and_unselected_projects_before_reading_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
            (project / ".agents").mkdir()
            for plugins in ([], ["work@tj-agents"], ["personal@tj-agents", "infonetica@tj-agents"]):
                with self.subTest(plugins=plugins):
                    (project / ".agents/plugins.json").write_text(json.dumps({
                        "plugins": plugins,
                        "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
                    }), encoding="utf-8")
                    with mock.patch.object(bot, "app_record") as record:
                        with self.assertRaisesRegex(bot.IdentityError, "explicitly adopted personal"):
                            bot.setup(root=project)
                    record.assert_not_called()
        repository = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
                                    capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(ROOT.resolve(), Path(repository.stdout.strip()).resolve())


def bot_toml(text):
    import tomllib
    return tomllib.loads(text)


if __name__ == "__main__":
    unittest.main()
