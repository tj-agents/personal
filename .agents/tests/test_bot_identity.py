from __future__ import annotations

import importlib.util
import io
import json
import contextlib
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
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/bot-identity/scripts/bot_identity.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("bot_identity", SCRIPT)
bot = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bot
spec.loader.exec_module(bot)

RECORD = {"id": 12345, "slug": "alex-bot", "client_id": "fixture-client", "owner": "alex", "owner_type": "User",
          "key": "unused.pem"}
CONFIG = {"schema_version": 1, "app": {name: value for name, value in RECORD.items() if name != "key"},
          "reviewer": "alex", "accounts": ["alex", "sample-org", "sample-lab"],
          "permissions": {"sample-org": {"repository_creation": "write"}}, "key": None}
INSTALLED = {"sample-org": 7, "alex": 8}
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
            return [{"account": {"login": "sample-org"}, "id": 7}]
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
        record = {**RECORD, "key": str(self.home / "github-app" / "alex-bot.pem")}
        (self.home / "github-app" / "alex-bot.pem").write_text("unused", encoding="utf-8")
        bot.write_private(self.home / "github-app" / "identity.json", {**CONFIG, "key": record["key"]})
        bot.protect(self.home / "github-app", directory=True)
        bot.protect(self.home / "github-app" / "alex-bot.pem")
        bot.protect(self.home / "github-app" / "identity.json")

    def patch_environment(self, values):
        patcher = mock.patch.object(os, "environ", {**os.environ, **values})
        patcher.start()
        self.addCleanup(patcher.stop)


class IdentityTests(Sandbox):
    def token(self, owner, github, now=0):
        return bot.installation_token(owner, RECORD, now=now, fetch=github, sign=lambda record: "jwt")

    def test_installed_owner_gets_one_cached_token_and_others_get_none(self):
        github = FakeGitHub()
        self.assertEqual("ghs_2", self.token("Sample-Org", github))
        self.assertEqual("ghs_2", self.token("sample-org", github))
        with self.assertRaises(bot.IdentityError):
            self.token("outside-org", github)
        self.assertEqual(1, sum(method == "POST" for method, _ in github.calls))

    def test_an_expiring_token_is_reissued(self):
        github = FakeGitHub()
        first = self.token("sample-org", github)
        late = bot.datetime.fromisoformat("2030-01-01T00:00:00+00:00").timestamp() - 60
        self.assertNotEqual(first, self.token("sample-org", github, now=late))

    def test_owners_come_from_flags_urls_and_api_paths(self):
        cases = {("pr", "merge", "-R", "sample-org/core"): ["sample-org"],
                 ("pr", "view", "--repo=Concertable/auth"): ["Concertable"],
                 ("pr", "list", "-Ralex/winwrap"): ["alex"],
                 ("api", "repos/sample-org/core/pulls/1/merge", "-X", "PUT"): ["sample-org"],
                 ("api", "https://api.github.com/orgs/sample-org/rulesets"): ["sample-org"],
                 ("pr", "view", "-R", "https://github.com/Concertable/b2b"): ["Concertable"],
                 ("pr", "view", "-R", "github.com/Concertable/b2b"): ["Concertable"],
                 ("pr", "review", "--approve", "https://github.com/sample-org/core/pull/5"): ["sample-org"],
                 ("pr", "view", "--json", "title", "https://github.com/outside-org/cris/pull/5"): ["outside-org"],
                 ("repo", "delete", "alex/notes", "--yes"): ["alex"],
                 ("project", "list", "--owner", "sample-org"): ["sample-org"],
                 ("api", "graphql"): []}
        for arguments, owners in cases.items():
            with self.subTest(arguments=arguments):
                self.assertEqual(owners, bot.owners_from_arguments(list(arguments)))

    def test_checkout_owner_comes_only_from_github_remotes(self):
        cases = {"https://x-access-token@github.com/sample-org/core.git": "sample-org",
                 "git@github.com:outside-org/cris.git": "outside-org",
                 "https://notgithub.com/sample-org/core": None}
        for url, owner in cases.items():
            with self.subTest(url=url):
                remote = mock.Mock(return_value=subprocess.CompletedProcess([], 0, url + "\n"))
                self.assertEqual(owner, bot.owner_from_checkout(run=remote))


class CredentialTests(Sandbox):
    def ask(self, request, token="ghs_x", target=None):
        out = io.StringIO()
        target = target or bot.RepositoryTarget(self.home, "sample-org", "core", True)

        def native(arguments, **_):
            return subprocess.CompletedProcess(arguments, 0, "", "")

        with mock.patch.object(bot, "installed", side_effect=fake_installed), \
                mock.patch.object(bot, "installation_token", return_value=token):
            bot.credential("get", io.StringIO(request + "\n"), out, checkout=lambda: target, run=native)
        return out.getvalue()

    def test_installed_accounts_get_only_the_app_token(self):
        answer = self.ask("protocol=https\nhost=github.com\npath=sample-org/core.git\n")
        self.assertEqual("username=x-access-token\npassword=ghs_x\n", answer)

    def test_an_installed_account_never_falls_back_when_minting_fails(self):
        target = bot.RepositoryTarget(self.home, "alex", "notes", True)
        self.assertEqual("quit=true\n", self.ask("protocol=https\nhost=github.com\npath=alex/notes.git\n", token=None, target=target))

    def test_requests_without_an_account_get_nothing(self):
        for request in ("protocol=https\nhost=github.com\n", "protocol=http\nhost=github.com\npath=outside-org/x\n",
                        "protocol=https\nhost=gist.github.com\npath=sample-org/x\n"):
            with self.subTest(request=request):
                self.assertEqual("", self.ask(request))

    def test_a_missing_app_record_fails_closed(self):
        (self.home / "github-app" / "identity.json").unlink()
        out = io.StringIO()
        bot.credential(
            "get",
            io.StringIO("protocol=https\nhost=github.com\npath=sample-org/x\n\n"),
            out,
            checkout=lambda: bot.RepositoryTarget(self.home, "sample-org", "x", True),
        )
        self.assertEqual("quit=true\n", out.getvalue())

    def test_an_account_the_app_does_not_cover_uses_no_bot_credential(self):
        calls: list[list[str]] = []

        def native(arguments, **_):
            calls.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, "username=native\npassword=native\n", "")

        output = io.StringIO()
        bot.credential(
            "get",
            io.StringIO("protocol=https\nhost=github.com\npath=outside-org/cris.git\n\n"),
            output,
            checkout=lambda: bot.RepositoryTarget(self.home, "sample-org", "x", True),
            run=native,
        )
        self.assertEqual("username=native\npassword=native\n", output.getvalue())
        self.assertEqual([["git", "credential", "fill"]], calls)

    def test_another_repository_under_the_same_owner_gets_no_bot_credential(self):
        answer = self.ask("protocol=https\nhost=github.com\npath=sample-org/other.git\n")
        self.assertEqual("", answer)

    def test_an_unadopted_checkout_gets_no_bot_credential(self):
        self.assertEqual("", answer)

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
        cases = {"protocol=https\nhost=github.com\npath=sample-org/core.git\n": "password=BOT",
                 "protocol=https\nhost=github.com\n": "password=BOT",
                 "protocol=https\nhost=gist.github.com\n": "",
                 "protocol=https\nhost=api.github.com\n": "",
                 "protocol=http\nhost=github.com\n": "",
                 "protocol=https\nhost=dev.azure.com\n": "password=TOMMY_GENERIC"}
        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(expected, self.fill(request, environment))

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

    def environment(self, *arguments, checkout=None, bot_enabled=True):
        target = bot.RepositoryTarget(self.home, checkout or "sample-org", "core", bot_enabled)
        self.assertEqual(0, bot.run_gh(list(arguments), run=self.gh, checkout=lambda: target))
        command, environment = self.gh.calls[-1]
        self.assertEqual(["real-gh", *arguments], command)
        return environment

    def refused(self, *arguments, checkout=None):
        target = bot.RepositoryTarget(self.home, checkout or "sample-org", "core", True)
        with self.assertRaises(bot.IdentityError):
            bot.run_gh(list(arguments), run=self.gh, checkout=lambda: target)
        self.assertEqual([], self.gh.calls)

    def native(self, *arguments, checkout=None, bot_enabled=True):
        environment = self.environment(*arguments, checkout=checkout, bot_enabled=bot_enabled)
        self.assertNotIn(bot.TOKEN_FINGERPRINT, environment)
        return environment

    def test_installed_accounts_get_the_app_token_and_the_agent_gh_config(self):
        environment = self.environment("pr", "merge", "5", "-R", "sample-org/core")
        self.assertEqual("ghs_sample-org", environment["GH_TOKEN"])
        self.assertEqual(str(bot.gh_config_directory()), environment["GH_CONFIG_DIR"])

    def test_naming_another_repository_uses_native_credentials(self):
        self.native("pr", "review", "--approve", "https://github.com/alex/notes/pull/2", checkout="outside-org")

    def test_an_explicit_other_target_in_an_opted_checkout_uses_native_credentials(self):
        self.native("issue", "list", "-R", "outside-org/cris", checkout="sample-org")
        self.installed.assert_not_called()

    def test_payload_urls_do_not_change_the_target_identity(self):
        cases = (
            ("issue", "create", "--title", "Fixture", "--body", "See https://github.com/cli/cli/issues/1"),
            ("issue", "create", "--body=https://github.com/cli/cli/issues/1", "-R", "sample-org/core"),
            ("api", "repos/sample-org/core/issues", "-f", "body=https://github.com/cli/cli/issues/1"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                environment = self.environment(*arguments, checkout="sample-org")
                self.assertEqual("ghs_sample-org", environment["GH_TOKEN"])

    def test_a_gh_child_entering_another_repository_uses_native_credentials(self):
        self.patch_environment(self.environment("api", "repos/sample-org/personal"))
        self.gh.calls.clear()
        self.native("api", "repos/outside-org/cris")

    def test_a_personal_token_is_not_sent_to_a_different_host(self):
        self.native("api", "repos/sample-org/personal", "--hostname", "example.test")
        self.installation_token.assert_not_called()

    def test_command_specific_booleans_preserve_the_explicit_work_target(self):
        for command, flags in (("merge", ("-m", "-r", "-s")), ("review", ("-a", "-r", "-c", "--comment")),
                               ("checkout", ("-f",)), ("co", ("-f",))):
            for flag in flags:
                with self.subTest(command=command, flag=flag):
                    self.native("pr", command, flag, "https://github.com/outside-org/cris/pull/5", checkout="sample-org")
        self.installation_token.assert_not_called()

    def test_a_boolean_fork_remote_option_preserves_the_explicit_work_target(self):
        self.native("repo", "fork", "--remote", "https://github.com/outside-org/cris", checkout="sample-org")
        self.installation_token.assert_not_called()

    def test_clone_of_another_repository_uses_native_credentials(self):
        for flag in ("-u", "--upstream-remote-name"):
            with self.subTest(flag=flag):
                self.native("repo", "clone", flag, "upstream", "sample-org/personal",
                            "destination/subdirectory", checkout="alex")

    def test_formatting_payload_urls_preserve_the_checkout_identity(self):
        for command in (("pr", "list"), ("issue", "list"), ("pr", "checks"), ("repo", "list")):
            for flag in ("-q", "-t"):
                with self.subTest(command=command, flag=flag):
                    environment = self.environment(*command, "--json", "url", flag,
                        '.[] | select(.url == "https://github.com/outside-org/cris/pull/5")', checkout="sample-org")
                    self.assertEqual("ghs_sample-org", environment["GH_TOKEN"])

    def test_issue_create_alias_excludes_payload_urls(self):
        environment = self.environment("issue", "new", "-t", "Fixture", "-b",
                                       "See https://github.com/outside-org/cris", checkout="sample-org")
        self.assertEqual("ghs_sample-org", environment["GH_TOKEN"])

    def test_api_preview_values_cannot_enable_the_bot_for_another_checkout(self):
        for flag in ("--preview", "-p"):
            with self.subTest(flag=flag):
                self.native("api", flag, "nebula", "repos/sample-org/personal", checkout="outside-org")

    def test_hostname_text_in_a_payload_cannot_override_the_actual_host(self):
        self.native("api", "repos/sample-org/personal", "--hostname", "enterprise.example",
                    "-f", "--hostname=github.com")
        self.installation_token.assert_not_called()

    def test_hostname_text_in_a_payload_is_not_an_option(self):
        environment = self.environment("issue", "create", "--title", "--hostname", "--body",
                                       "--hostname=example.test", checkout="sample-org")
        self.assertEqual("ghs_sample-org", environment["GH_TOKEN"])

    def test_gh_repo_target_overrides_the_checkout(self):
        self.patch_environment({"GH_REPO": "outside-org/cris"})
        self.native("issue", "list", checkout="sample-org")
        self.installed.assert_not_called()

    def test_mixed_explicit_owners_are_rejected_before_minting(self):
        self.native("pr", "view", "https://github.com/sample-org/core/pull/1", "-R", "outside-org/cris")
        self.installation_token.assert_not_called()

    def test_an_unopted_checkout_uses_native_credentials(self):
        environment = self.native("issue", "list", checkout="sample-org", bot_enabled=False)
        self.assertNotIn("GH_TOKEN", environment)
        self.installed.assert_not_called()

    def test_a_repository_outside_the_apps_accounts_uses_native_credentials(self):
        self.native("pr", "list", checkout="outside-org")
        self.installation_token.assert_not_called()

    def test_commands_without_a_repository_target_use_native_credentials(self):
        environment = self.native("api", "graphql", "-f", "query={viewer{login}}")
        self.assertNotIn("GH_TOKEN", environment)
        self.installed.assert_not_called()

    def test_gh_auth_never_reaches_the_humans_credentials(self):
        for arguments in (("auth", "token"), ("auth", "token", "-u", "alex"), ("auth", "git-credential", "get"),
                          ("auth", "logout"), ("auth", "setup-git")):
            with self.subTest(arguments=arguments):
                self.refused(*arguments)
        environment = self.native("auth", "status", "--show-token", checkout="outside-org")
        self.assertNotIn("GH_TOKEN", environment)

    def test_a_failed_mint_for_an_installed_account_stops_the_command(self):
        self.installation_token.side_effect = lambda owner, record: None
        self.refused("pr", "create", "-R", "sample-org/core")

    def test_the_humans_own_terminal_runs_the_real_gh_untouched(self):
        del os.environ["TJ_AGENT"]
        self.assertEqual(0, bot.run_gh(["pr", "list"], run=self.gh, checkout=lambda: "sample-org"))
        self.assertEqual([(["real-gh", "pr", "list"], None)], self.gh.calls)


class ApprovalHandoffTests(GhWrapperTests):
    CORE = "https://github.com/sample-org/core/pull/7"
    TJ_APPROVE = "Put the line `! tj approve` on the human's clipboard with cli:clip"

    def hand_over(self, *arguments, checkout="sample-org", stdout=None, returncode=0):
        self.gh.stdout, self.gh.returncode = stdout, returncode
        out, err = io.StringIO(), io.StringIO()
        target = bot.RepositoryTarget(self.home, checkout, "core", True)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(returncode, bot.run_gh(list(arguments), run=self.gh, checkout=lambda: target))
        return out.getvalue(), err.getvalue()

    def test_a_created_pr_points_the_human_at_tj_approve_and_keeps_its_url_on_stdout(self):
        out, err = self.hand_over("pr", "create", "--fill", stdout=self.CORE + "\n")
        self.assertEqual(self.CORE + "\n", out)
        self.assertIn(f"{self.CORE} awaits alex's approval", err)
        self.assertIn(self.TJ_APPROVE, err)

    def test_a_payload_url_preserves_bot_authentication_and_the_approval_handoff(self):
        out, err = self.hand_over("pr", "create", "--title", "Fixture", "--body",
                                  "See https://github.com/cli/cli/issues/1", stdout=self.CORE + "\n")
        self.assertEqual(self.CORE + "\n", out)
        self.assertEqual("ghs_sample-org", self.gh.calls[0][1]["GH_TOKEN"])
        self.assertIn(f"{self.CORE} awaits alex's approval", err)
        self.assertIn(self.TJ_APPROVE, err)

    def test_create_alias_preserves_bot_authentication_and_the_approval_handoff(self):
        out, err = self.hand_over("pr", "new", "-t", "Fixture", "-b",
                                  "See https://github.com/cli/cli/issues/1", stdout=self.CORE + "\n")
        self.assertEqual(self.CORE + "\n", out)
        self.assertEqual("ghs_sample-org", self.gh.calls[0][1]["GH_TOKEN"])
        self.assertIn(f"{self.CORE} awaits alex's approval", err)
        self.assertIn(self.TJ_APPROVE, err)

    def test_a_readied_pr_is_looked_up_with_its_selector_and_handed_over(self):
        _, err = self.hand_over("pr", "ready", "7", "-R", "sample-org/core", stdout=self.CORE)
        view, environment = self.gh.calls[-1]
        self.assertEqual(["real-gh", "pr", "view", "7", "-R", "sample-org/core", "--json", "url", "--jq", ".url"],
                         view)
        self.assertEqual("ghs_sample-org", environment["GH_TOKEN"])
        self.assertIn(f"{self.CORE} awaits alex's approval", err)
        self.assertIn(self.TJ_APPROVE, err)

    def test_drafts_undo_failures_and_uncovered_accounts_hand_nothing_over(self):
        for arguments, checkout, returncode in ((("pr", "create", "--draft"), "sample-org", 0),
                                                (("pr", "create", "-d"), "sample-org", 0),
                                                (("pr", "create", "--dry-run"), "sample-org", 0),
                                                (("pr", "ready", "--undo"), "sample-org", 0),
                                                (("pr", "create"), "sample-org", 1),
                                                (("pr", "ready", "4"), "sample-org", 1),
                                                (("pr", "create"), None, 0)):
            with self.subTest(arguments=arguments, checkout=checkout, returncode=returncode):
                self.gh.calls.clear()
                _, err = self.hand_over(*arguments, checkout=checkout, stdout=self.CORE, returncode=returncode)
                self.assertEqual("", err)
                self.assertEqual(1, len(self.gh.calls))

    def test_flag_spellings_given_as_values_still_hand_the_pr_over(self):
        _, err = self.hand_over("pr", "create", "--title", "--draft", "-b", "-w", stdout=self.CORE)
        self.assertIn(f"{self.CORE} awaits alex's approval", err)
        self.assertIn(self.TJ_APPROVE, err)

    def test_an_unresolved_url_still_points_the_human_at_tj_approve(self):
        _, err = self.hand_over("pr", "create", stdout="")
        self.assertIn("this PR awaits alex's approval", err)
        self.assertIn(self.TJ_APPROVE, err)

    def test_the_retired_approval_command_is_gone(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bot.main(["approval", self.CORE])


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
        self.assertEqual(["bot_identity.py", "gh.exe", "onboarding.html", "onboarding.py"],
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

    def test_claude_merges_env_and_denies_mcp_writes_and_tj_approve(self):
        path = self.root / "settings.json"
        path.write_text(json.dumps({"env": {"KEEP": "1", "GIT_CONFIG_KEY_9": "old", "Path": "old"},
                                    "permissions": {"deny": ["Bash(rm:*)"]}}), encoding="utf-8")
        bot.update_claude(path, self.environment)
        settings = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({"KEEP": "1", **self.environment}, settings["env"])
        self.assertIn("Bash(rm:*)", settings["permissions"]["deny"])
        self.assertIn("mcp__github__merge_pull_request", settings["permissions"]["deny"])
        self.assertIn("Bash(tj approve:*)", settings["permissions"]["deny"])
        self.assertIn("Bash(tj-approve:*)", settings["permissions"]["deny"])

class EnrollmentTests(Sandbox):
    def test_existing_app_selection_reuses_the_enrolled_key_and_permitted_accounts(self) -> None:
        before = (bot.store() / "identity.json").read_bytes()
        modified = (bot.store() / "identity.json").stat().st_mtime_ns
        actual = {**CONFIG["app"], "owner": {"login": "alex", "type": "User"}}
        calls = []

        def lookup(path, bearer, method="GET"):
            calls.append((path, bearer))
            return actual

        bot.configure_existing_app("alex-bot", fetch=lookup)
        self.assertEqual([("/apps/alex-bot", None)], calls)
        self.assertEqual(before, (bot.store() / "identity.json").read_bytes())
        self.assertEqual(modified, (bot.store() / "identity.json").stat().st_mtime_ns)
        self.assertEqual(("alex", "sample-org", "sample-lab"), bot.required_owners())
        self.assertEqual(str(bot.store() / "alex-bot.pem"), bot.app_record()["key"])

    def test_new_machine_existing_app_selection_retains_public_configuration_before_key_enrollment(self) -> None:
        (bot.store() / "identity.json").unlink()
        actual = {"id": 9876, "client_id": "another-client", "slug": "team-helper",
                  "owner": {"login": "new-team", "type": "Organization"}}
        bot.configure_existing_app("team-helper", reviewer="river", accounts=["river", "new-team"],
                                   fetch=lambda path, bearer: actual)
        configured = bot.identity_config()
        self.assertEqual("river", configured["reviewer"])
        self.assertEqual(["river", "new-team"], configured["accounts"])
        self.assertIsNone(configured["key"])
        self.assertEqual({owner: bot.onboarding.PERMISSIONS for owner in configured["accounts"]},
                         configured["permissions"])
        self.assertEqual("https://github.com/organizations/new-team/settings/apps/team-helper",
                         bot.app_settings_url(configured["app"]))
        with self.assertRaises(bot.OnboardingRequired):
            bot.app_record()

    def test_another_app_cannot_replace_an_existing_enrollment(self) -> None:
        before = (bot.store() / "identity.json").read_bytes()
        replacement = {**CONFIG, "app": {**CONFIG["app"], "id": 9876, "slug": "another-bot"}}
        with self.assertRaisesRegex(bot.IdentityError, "already enrolled"):
            bot.configure_identity(replacement)
        self.assertEqual(before, (bot.store() / "identity.json").read_bytes())
        self.assertEqual("unused", (bot.store() / "alex-bot.pem").read_text())

    def test_unsafe_or_malformed_configuration_never_restarts_enrollment(self) -> None:
        path = bot.store() / "identity.json"
        path.write_text("{}", encoding="utf-8")
        with mock.patch.object(bot, "configured_project", return_value=self.home), \
                mock.patch.object(bot, "onboard") as onboard:
            with self.assertRaisesRegex(bot.IdentityError, "configuration is invalid"):
                bot.setup(self.home, onboard_key=True)
        onboard.assert_not_called()

    def test_configuration_rejects_ambiguous_accounts_and_external_key_paths(self) -> None:
        invalid = (
            {**CONFIG, "schema_version": True},
            {**CONFIG, "reviewer": "helper[bot]"},
            {**CONFIG, "accounts": ["alex", "ALEX"]},
            {**CONFIG, "permissions": {"unselected": {"contents": "write"}}},
            {**CONFIG, "key": str(self.home / "outside.pem")},
            {**CONFIG, "app": {**CONFIG["app"], "owner_type": "unknown"}},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(bot.IdentityError):
                bot.validate_identity(value)

    def test_configuration_arguments_require_explicit_onboarding(self) -> None:
        before = (bot.store() / "identity.json").read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bot.main(["setup", "--check", "--app", "another-bot", "--reviewer", "river"])
        self.assertEqual(before, (bot.store() / "identity.json").read_bytes())

    def remove_enrollment(self):
        for path in (self.home / "github-app").glob("alex-bot.*"):
            path.unlink()
        bot.write_private(self.home / "github-app" / "identity.json", {**CONFIG, "key": None})

    def readiness_fetch(self, app_permissions, tj_agents_permissions):
        calls = []

        def fetch(path, bearer, method="GET"):
            calls.append((method, path))
            if path == "/app":
                return {**{key: value for key, value in RECORD.items() if key != "key"},
                        "owner": {"login": RECORD["owner"], "type": RECORD["owner_type"]}, "permissions": app_permissions}
            self.assertEqual("/app/installations", path)
            return [
                {"id": 7, "account": {"login": "sample-org"}, "target_type": "Organization",
                 "permissions": tj_agents_permissions},
                {"id": 8, "account": {"login": "alex"}, "target_type": "User", "permissions": {}},
                {"id": 9, "account": {"login": "sample-lab"}, "target_type": "Organization", "permissions": {}},
            ]

        return fetch, calls

    def test_readiness_reports_the_app_settings_page_for_a_missing_declaration(self):
        fetch, calls = self.readiness_fetch({}, {"repository_creation": "write"})
        with self.assertRaisesRegex(bot.IdentityError,
                                    r"configured GitHub App does not grant repository_creation:write; update it at "
                                    r"https://github.com/settings/apps/alex-bot"):
            bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app")], calls)

    def test_readiness_reports_the_tj_agents_installation_settings_page_pending_acceptance(self):
        fetch, calls = self.readiness_fetch({"repository_creation": "write"}, {})
        with self.assertRaisesRegex(bot.IdentityError,
                                    r"sample-org App installation does not grant repository_creation:write; update it at "
                                    r"https://github.com/organizations/sample-org/settings/installations/7"):
            bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_accepts_the_declared_and_accepted_creation_capability(self):
        fetch, calls = self.readiness_fetch({"repository_creation": "write"}, {"repository_creation": "write"})
        bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_rejects_administration_write_on_the_app_or_tj_agents_installation(self):
        cases = (
            ("App", {"repository_creation": "write", "administration": "write"},
             {"repository_creation": "write"}, "settings/apps/alex-bot"),
            ("installation", {"repository_creation": "write"},
             {"repository_creation": "write", "administration": "write"},
             "organizations/sample-org/settings/installations/7"),
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
        self.assertFalse((self.home / "github-app" / "alex-bot.json").exists())

        def wrong_app(path, bearer, method="GET"):
            return {"id": 1, "client_id": "wrong", "slug": "wrong", "owner": {"login": "wrong"}}

        pem = b"-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n"
        with self.assertRaises(bot.IdentityError):
            bot.persist_enrollment(pem, fetch=wrong_app, sign=lambda record: "jwt")
        self.assertFalse((self.home / "github-app" / "alex-bot.json").exists())
        self.assertFalse((self.home / "github-app" / ".candidate.pem").exists())

    def test_missing_protected_installation_fails_closed_without_human_fallback(self):
        self.patch_environment(bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
        target = bot.RepositoryTarget(self.home, "alex", "notes", True)
        with mock.patch.object(bot, "installed", return_value={}), self.assertRaises(bot.IdentityError):
            bot.agent_gh_environment(["pr", "list", "-R", "alex/notes"], target)

    def test_failed_readiness_does_not_mutate_agent_hosts(self):
        with mock.patch.object(bot, "configured_project", return_value=self.home), \
                mock.patch.object(bot, "verify_ready", side_effect=bot.IdentityError("missing installation")), \
                mock.patch.object(bot, "install_shims") as install, \
                mock.patch.object(bot, "update_claude") as claude, \
                mock.patch.object(bot, "update_codex") as codex:
            with self.assertRaises(bot.IdentityError):
                bot.setup(self.home)
        install.assert_not_called()
        claude.assert_not_called()
        codex.assert_not_called()

    def test_check_is_read_only_and_setup_flags_are_exclusive(self):
        with mock.patch.object(bot, "configured_project", return_value=self.home), \
                mock.patch.object(bot, "verify_ready"), mock.patch.object(bot, "verify_host_setup"), \
                mock.patch.object(bot, "install_shims") as install:
            with contextlib.redirect_stdout(io.StringIO()):
                bot.setup(self.home, check=True)
        install.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            bot.main(["setup", "--check", "--onboard"])

    def test_private_key_write_is_private_on_posix(self):
        if os.name == "nt":
            self.skipTest("Windows ACL exercised by protect() during the Windows suite")
        path = self.home / "github-app" / "alex-bot.pem"
        bot.write_key(path, b"private")
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
        path.chmod(0o644)
        with self.assertRaises(bot.IdentityError):
            bot.require_private_permissions(path)

    @unittest.skipUnless(os.name == "nt", "Windows ACL")
    def test_private_key_write_applies_a_private_windows_acl(self):
        path = self.home / "github-app" / "alex-bot.pem"
        bot.write_key(path, b"private")
        bot.require_private_permissions(path)
        acl = subprocess.run(["icacls", str(path)], text=True, capture_output=True, check=True).stdout
        self.assertIn("SYSTEM:", acl)
        self.assertNotIn("BUILTIN\\Users", acl)

    def test_check_rejects_broadened_secret_permissions(self):
        path = self.home / "github-app" / "alex-bot.pem"
        bot.require_private_permissions(path)
        if bot.WINDOWS:
            subprocess.run(["icacls", str(path), "/grant", "*S-1-5-32-544:(R)"],
                           capture_output=True, check=True)
        else:
            path.chmod(0o644)
        with self.assertRaisesRegex(bot.IdentityError, "permissions are unsafe"):
            bot.require_private_permissions(path)

    def test_only_revoked_credentials_restart_onboarding_after_a_github_failure(self):
        for status, starts in ((401, True), (403, False), (None, False)):
            with self.subTest(status=status), \
                    mock.patch.object(bot, "verify_ready", side_effect=[bot.GitHubError("failed", status), bot.IdentityError("stop before settings")]), \
                    mock.patch.object(bot, "configured_project", return_value=self.home), \
                    mock.patch.object(bot, "onboard") as onboard:
                with self.assertRaises(bot.IdentityError):
                    bot.setup(self.home, onboard_key=True)
                self.assertEqual(starts, onboard.called)

    @pytest.mark.allow_hosts(["127.0.0.1"])
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
    def test_repository_setup_scopes_the_bot_to_one_opted_in_checkout(self):
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
            (project / ".agents/settings.json").write_text(json.dumps({
                "configuration": {"personal": {"bot_identity": True}},
            }), encoding="utf-8")
            environment = {**without_agent_settings(os.environ), "HOME": str(home), "USERPROFILE": str(home),
                           "CLAUDE_CONFIG_DIR": str(home / "claude"), "CODEX_HOME": str(home / "codex"),
                           "TJ_BIN_DIR": str(home / "tj bin"),
                           "PATH": os.environ["PATH"]}
            with mock.patch.object(os, "environ", environment):
                key = bot.store() / "alex-bot.pem"
                bot.write_key(key, b"unused fixture key")
                bot.write_private(bot.store() / "identity.json", {**CONFIG, "key": str(key)})
                with mock.patch.object(bot, "verify_ready"), contextlib.redirect_stdout(io.StringIO()):
                    bot.setup(project)
                    bot.setup(project, check=True)
                claude = json.loads((project / ".claude/settings.json").read_text(encoding="utf-8"))
                codex = bot_toml((project / ".codex/config.toml").read_text(encoding="utf-8"))
                self.assertEqual(claude["env"], codex["shell_environment_policy"]["set"])
                self.assertEqual("1", claude["env"]["TJ_AGENT"])
                self.assertFalse((home / "claude/settings.json").exists())
                self.assertFalse((home / "codex/config.toml").exists())


def bot_toml(text):
    import tomllib
    return tomllib.loads(text)


def opted_repository(root: Path) -> None:
    subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
    (root / ".agents").mkdir()
    (root / ".agents/plugins.json").write_text(json.dumps({
        "plugins": ["personal@tj-agents"],
        "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
    }), encoding="utf-8")
    (root / ".agents/settings.json").write_text(json.dumps({
        "configuration": {"personal": {"bot_identity": True}},
    }), encoding="utf-8")


def test_repository_opt_in_requires_selection_and_true_setting(tmp_path: Path) -> None:
    opted_repository(tmp_path)
    assert bot.bot_identity_enabled(tmp_path)
    (tmp_path / ".agents/settings.json").write_text(json.dumps({
        "configuration": {"personal": {"bot_identity": False}},
    }), encoding="utf-8")
    assert not bot.bot_identity_enabled(tmp_path)
    with pytest.raises(bot.IdentityError, match="bot_identity"):
        bot.configured_project(tmp_path)


def test_cross_repository_target_uses_native_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "gh_config_directory", lambda: Path("/s/gh-agent"))
    monkeypatch.setattr(bot, "shim_directory", lambda: Path("/s/shim"))
    environment = bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"])
    environment["GH_TOKEN"] = "human-token"
    environment.pop(bot.TOKEN_FINGERPRINT, None)
    monkeypatch.setattr(os, "environ", environment)
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    native = bot.agent_gh_environment(["pr", "list", "-R", "other-org/other"], target)
    assert native["GH_TOKEN"] == "human-token"
    assert "TJ_AGENT" not in native
    assert bot.GIT_FINGERPRINT not in native


@pytest.mark.parametrize("arguments", [
    ["pr", "view", "https://github.com/sample-org/core/pull/1"],
    ["issue", "close", "https://github.com/sample-org/core/issues/1"],
])
def test_resource_url_target_uses_the_configured_bot(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "environ", bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    with mock.patch.object(bot, "required_owners", return_value=("sample-org",)), \
            mock.patch.object(bot, "app_record", return_value=RECORD), \
            mock.patch.object(bot, "installed", return_value={"sample-org": 7}), \
            mock.patch.object(bot, "installation_token", return_value="bot-token"):
        environment = bot.agent_gh_environment(arguments, target)
    assert environment["GH_TOKEN"] == "bot-token"


def test_conflicting_gh_selectors_never_mint_a_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "gh_config_directory", lambda: Path("/s/gh-agent"))
    monkeypatch.setattr(bot, "shim_directory", lambda: Path("/s/shim"))
    monkeypatch.setattr(os, "environ", bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    with mock.patch.object(bot, "required_owners", return_value=("sample-org",)), \
            mock.patch.object(bot, "installation_token") as mint:
        environment = bot.agent_gh_environment(
            ["pr", "view", "https://github.com/sample-org/core/pull/1", "-R", "outside-org/cris"], target,
        )
    assert bot.TOKEN_FINGERPRINT not in environment
    mint.assert_not_called()


def test_api_target_after_flags_routes_by_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    with mock.patch.object(bot, "required_owners", return_value=("sample-org",)), \
            mock.patch.object(bot, "app_record", return_value=RECORD), \
            mock.patch.object(bot, "installed", return_value={"sample-org": 7}), \
            mock.patch.object(bot, "installation_token", return_value="bot-token"):
        environment = bot.agent_gh_environment(["api", "-X", "GET", "repos/sample-org/core/issues"], target)
    assert environment["GH_TOKEN"] == "bot-token"


def test_graphql_after_flags_uses_native_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "gh_config_directory", lambda: Path("/s/gh-agent"))
    monkeypatch.setattr(bot, "shim_directory", lambda: Path("/s/shim"))
    monkeypatch.setattr(os, "environ", bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    environment = bot.agent_gh_environment(["api", "-f", "query={viewer{login}}", "graphql"], target)
    assert bot.TOKEN_FINGERPRINT not in environment


def test_repository_target_uses_gh_resolved_remote(tmp_path: Path) -> None:
    opted_repository(tmp_path)

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[-2:] == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, str(tmp_path) + "\n")
        if command[-2:] == ["--get-regexp", r"^remote\..*\.gh-resolved$"]:
            return subprocess.CompletedProcess(command, 0, "remote.upstream.gh-resolved base\n")
        assert command[-3:] == ["remote", "get-url", "upstream"]
        return subprocess.CompletedProcess(command, 0, "git@github.com:sample-org/core.git\n")

    target = bot.repository_target(tmp_path, run=run)
    assert target == bot.RepositoryTarget(tmp_path, "sample-org", "core", True)


def test_unselected_multiple_remotes_do_not_enable_the_bot(tmp_path: Path) -> None:
    opted_repository(tmp_path)

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[-2:] == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, str(tmp_path) + "\n")
        if command[-2:] == ["--get-regexp", r"^remote\..*\.gh-resolved$"]:
            return subprocess.CompletedProcess(command, 1, "")
        assert command[-1] == "remote"
        return subprocess.CompletedProcess(command, 0, "origin\nupstream\n")

    target = bot.repository_target(tmp_path, run=run)
    assert target == bot.RepositoryTarget(tmp_path, None, None, True)


def test_credential_restores_native_helper_for_uncovered_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, project = tmp_path / "home", tmp_path / "repository"
    home.mkdir()
    opted_repository(project)
    subprocess.run(["git", "-C", str(project), "remote", "add", "origin", "https://github.com/outside-org/cris.git"], check=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    bot.write_private(bot.store() / "identity.json", CONFIG)
    global_config = home / "gitconfig"
    global_config.write_text(
        '[credential "https://github.com"]\n\thelper = "!f() { echo username=human; echo password=NATIVE; }; f"\n',
        encoding="utf-8",
    )
    environment = {
        **without_agent_settings(os.environ),
        **bot.agent_environment(SCRIPT, os.environ["PATH"]),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "USERPROFILE": str(home),
    }
    result = subprocess.run(
        ["git", "credential", "fill"], cwd=project,
        input="protocol=https\nhost=github.com\npath=outside-org/cris.git\n\n", env=environment,
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0
    assert "password=NATIVE" in result.stdout


def test_covered_credential_failure_never_runs_native_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
    run = mock.Mock()
    out = io.StringIO()
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    with mock.patch.object(bot, "required_owners", return_value=("sample-org",)), \
            mock.patch.object(bot, "app_record", return_value=RECORD), \
            mock.patch.object(bot, "installed", return_value={"sample-org": 7}), \
            mock.patch.object(bot, "installation_token", return_value=None):
        bot.credential("get", io.StringIO("protocol=https\nhost=github.com\npath=sample-org/core.git\n\n"), out,
                       checkout=lambda: target, run=run)
    assert out.getvalue() == "quit=true\n"
    run.assert_not_called()


def test_project_configuration_rejects_hard_link(tmp_path: Path) -> None:
    opted_repository(tmp_path)
    directory, source = tmp_path / ".claude", tmp_path / "source.json"
    directory.mkdir()
    source.write_text("{}\n", encoding="utf-8")
    os.link(source, directory / "settings.json")
    with pytest.raises(bot.IdentityError, match="configuration path is unsafe"):
        bot.claude_project_settings(tmp_path)


def test_project_configuration_rejects_reparse_ancestor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opted_repository(tmp_path)
    directory = tmp_path / ".codex"
    directory.mkdir()
    monkeypatch.setattr(bot, "is_reparse", lambda path: path == directory)
    with pytest.raises(bot.IdentityError, match="configuration path is unsafe"):
        bot.codex_project_config(tmp_path)


def test_opted_covered_target_fails_when_app_installation_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", bot.agent_environment(Path("/s/bot_identity.py"), os.environ["PATH"]))
    target = bot.RepositoryTarget(Path("/repository"), "sample-org", "core", True)
    with mock.patch.object(bot, "required_owners", return_value=("sample-org",)), \
            mock.patch.object(bot, "app_record", return_value=RECORD), \
            mock.patch.object(bot, "installed", return_value={}):
        with pytest.raises(bot.IdentityError, match="not installed"):
            bot.agent_gh_environment(["pr", "list"], target)


def test_existing_protected_key_is_reused_after_selecting_the_same_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})
    key = tmp_path / "alex-bot.pem"
    bot.write_key(key, b"fixture-existing-protected-key")
    before = key.stat().st_mtime_ns

    def fetch(path: str, bearer: str, method: str = "GET") -> dict:
        assert path == "/app"
        return {**CONFIG["app"], "owner": {"login": "alex", "type": "User"}}

    bot.reuse_local_key(fetch=fetch, sign=lambda record: "fixture-jwt")
    assert bot.app_record()["key"] == str(key)
    assert key.stat().st_mtime_ns == before
    config_before = (tmp_path / "identity.json").stat().st_mtime_ns
    bot.reuse_local_key(fetch=fetch, sign=lambda record: "fixture-jwt")
    assert (tmp_path / "identity.json").stat().st_mtime_ns == config_before


def test_existing_key_network_failure_does_not_replace_or_reenroll_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})
    key = tmp_path / "alex-bot.pem"
    bot.write_key(key, b"fixture-existing-protected-key")
    before = key.stat().st_mtime_ns

    def unavailable(path: str, bearer: str, method: str = "GET") -> dict:
        raise bot.GitHubError("offline")

    with pytest.raises(bot.GitHubError, match="offline"):
        bot.reuse_local_key(fetch=unavailable, sign=lambda record: "fixture-jwt")
    assert bot.identity_config()["key"] is None
    assert key.stat().st_mtime_ns == before


@pytest.mark.parametrize("interrupted", [False, True])
def test_manifest_key_is_retained_unverified_until_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})
    pem = b"-----BEGIN PRIVATE KEY-----\nfixture-only\n-----END PRIVATE KEY-----\n"

    def unavailable(path: str, bearer: str, method: str = "GET") -> dict:
        if interrupted:
            raise KeyboardInterrupt
        raise bot.GitHubError("connection lost")

    with pytest.raises(KeyboardInterrupt if interrupted else bot.GitHubError):
        bot.persist_enrollment(pem, fetch=unavailable, sign=lambda record: "fixture-jwt")
    pending = tmp_path / "alex-bot.pending.pem"
    assert pending.read_bytes() == pem
    bot.require_private_permissions(pending)
    assert bot.identity_config()["key"] is None
    with pytest.raises(bot.OnboardingRequired):
        bot.app_record()

    def restored(path: str, bearer: str, method: str = "GET") -> dict:
        assert path == "/app"
        return {**CONFIG["app"], "owner": {"login": "alex", "type": "User"}}

    bot.reuse_local_key(fetch=restored, sign=lambda record: "fixture-jwt")
    assert bot.app_record()["key"] == str(tmp_path / "alex-bot.pem")
    assert not pending.exists()


def test_rejected_pending_key_is_retained_but_never_becomes_enrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})

    def rejected(path: str, bearer: str, method: str = "GET") -> dict:
        raise bot.GitHubError("unauthorized", 401)

    with pytest.raises(bot.GitHubError):
        bot.persist_enrollment(b"-----BEGIN PRIVATE KEY-----\nfixture\n", fetch=rejected,
                               sign=lambda record: "fixture-jwt")
    assert bot.identity_config()["key"] is None
    pending = tmp_path / "alex-bot.pending.pem"
    assert pending.exists()
    bot.require_private_permissions(pending)
    with pytest.raises(bot.OnboardingRequired):
        bot.app_record()


def test_open_wizard_retries_pending_key_without_another_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})

    def unavailable(path: str, bearer: str, method: str = "GET") -> dict:
        raise bot.GitHubError("offline")

    with pytest.raises(bot.GitHubError):
        bot.persist_enrollment(b"-----BEGIN PRIVATE KEY-----\nfixture\n", fetch=unavailable,
                               sign=lambda record: "fixture-jwt")

    def restored(path: str, bearer: str, method: str = "GET") -> dict | list:
        if path == "/app":
            return {**CONFIG["app"], "owner": {"login": "alex", "type": "User"},
                    "permissions": {"repository_creation": "write"}}
        assert path == "/app/installations"
        return [{"id": index, "account": {"login": owner},
                 "permissions": CONFIG["permissions"].get(owner, {})}
                for index, owner in enumerate(CONFIG["accounts"], start=1)]

    def page(**callbacks: object) -> None:
        ready = callbacks["ready"]
        assert callable(ready)
        ready()

    monkeypatch.setattr(bot.onboarding, "onboard", page)
    bot.onboard(fetch=restored, sign=lambda record: "fixture-jwt")
    assert bot.app_record()["key"] == str(tmp_path / "alex-bot.pem")
    assert not (tmp_path / "alex-bot.pending.pem").exists()


def test_missing_signing_tool_keeps_the_manifest_key_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})
    monkeypatch.setattr(bot.shutil, "which", lambda name: None)
    pem = b"-----BEGIN PRIVATE KEY-----\nfixture-key\n"
    with pytest.raises(bot.IdentityError, match="openssl"):
        bot.persist_enrollment(pem)
    assert (tmp_path / "alex-bot.pending.pem").read_bytes() == pem
    assert bot.identity_config()["key"] is None


def test_rejected_replacement_does_not_overwrite_the_only_pending_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    bot.configure_identity({**CONFIG, "key": None})
    original = b"-----BEGIN PRIVATE KEY-----\noriginal-fixture\n"

    def offline(path: str, bearer: str, method: str = "GET") -> dict:
        raise bot.GitHubError("offline")

    with pytest.raises(bot.GitHubError):
        bot.persist_enrollment(original, fetch=offline, sign=lambda record: "fixture")

    def wrong_app(path: str, bearer: str, method: str = "GET") -> dict:
        return {"id": 999, "slug": "different-app"}

    with pytest.raises(bot.IdentityError):
        bot.persist_enrollment(b"-----BEGIN PRIVATE KEY-----\nreplacement-fixture\n",
                               fetch=wrong_app, sign=lambda record: "fixture")
    assert (tmp_path / "alex-bot.pending.pem").read_bytes() == original
    assert not (tmp_path / ".replacement.pem").exists()
    assert bot.identity_config()["key"] is None


def test_unverified_replacement_does_not_block_a_working_enrollment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "store", lambda: tmp_path)
    active = tmp_path / "alex-bot.pem"
    bot.write_key(active, b"accepted-fixture-key")
    bot.configure_identity({**CONFIG, "key": str(active)})
    pending = tmp_path / "alex-bot.pending.pem"
    bot.write_key(pending, b"unverified-fixture-key")

    def sign(record: dict) -> str:
        assert record["key"] == str(active)
        return "active-key-signature"

    def fetch(path: str, bearer: str, method: str = "GET") -> dict | list:
        if path == "/app":
            return {**CONFIG["app"], "owner": {"login": "alex", "type": "User"},
                    "permissions": {"repository_creation": "write"}}
        assert path == "/app/installations"
        return [{"id": index, "account": {"login": owner},
                 "permissions": CONFIG["permissions"].get(owner, {})}
                for index, owner in enumerate(CONFIG["accounts"], start=1)]

    bot.verify_enrollment(fetch=fetch, sign=sign)
    assert active.read_bytes() == b"accepted-fixture-key"
    assert pending.read_bytes() == b"unverified-fixture-key"
    assert bot.app_record()["key"] == str(active)


def test_unreadable_key_has_a_distinct_replaceable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot.shutil, "which", lambda name: "fixture-openssl")

    def rejected(command: list[str], **arguments: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, 1, b"", b"fixture-signing-failure")

    with pytest.raises(bot.KeyVerificationError, match="could not sign"):
        bot.app_jwt(RECORD, run=rejected)


def test_explicit_onboarding_can_replace_an_unreadable_retained_key() -> None:
    with mock.patch.object(bot, "configured_project", return_value=Path.cwd()), \
            mock.patch.object(bot, "verify_enrollment", side_effect=bot.KeyVerificationError("unreadable")), \
            mock.patch.object(bot, "onboard", side_effect=bot.IdentityError("stop after UI")) as opened:
        with pytest.raises(bot.IdentityError, match="stop after UI"):
            bot.setup(Path.cwd(), onboard_key=True)
    opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
