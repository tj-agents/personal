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
    def __init__(self):
        self.calls = []

    def __call__(self, command, env=None, check=False):
        self.calls.append((command, env))
        return subprocess.CompletedProcess(command, 0)


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
            bot.credential("get", io.StringIO("protocol=https\nhost=github.com\npath=Infonetica/x\n\n"), out)
        self.assertEqual("", out.getvalue())
        tommy.assert_not_called()

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

    def test_an_installed_checkout_wins_over_an_uncovered_flag(self):
        environment = self.environment("issue", "list", "-R", "Infonetica/cris", checkout="tj-agents")
        self.assertEqual("ghs_tj-agents", environment["GH_TOKEN"])

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
        fetch, calls = self.readiness_fetch({}, {"repository_creation": "write"})
        with self.assertRaisesRegex(bot.IdentityError,
                                    r"pinned GitHub App does not grant repository_creation:write; update it at "
                                    r"https://github.com/settings/apps/tomjseery-bot"):
            bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app")], calls)

    def test_readiness_reports_the_tj_agents_installation_settings_page_pending_acceptance(self):
        fetch, calls = self.readiness_fetch({"repository_creation": "write"}, {})
        with self.assertRaisesRegex(bot.IdentityError,
                                    r"tj-agents App installation does not grant repository_creation:write; update it at "
                                    r"https://github.com/organizations/tj-agents/settings/installations/7"):
            bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_accepts_the_declared_and_accepted_creation_capability(self):
        fetch, calls = self.readiness_fetch({"repository_creation": "write"}, {"repository_creation": "write"})
        bot.verify_ready(RECORD, fetch=fetch, sign=lambda record: "jwt")
        self.assertEqual([("GET", "/app"), ("GET", "/app/installations")], calls)

    def test_readiness_rejects_administration_write_on_the_app_or_tj_agents_installation(self):
        cases = (
            ("App", {"repository_creation": "write", "administration": "write"},
             {"repository_creation": "write"}, "settings/apps/tomjseery-bot"),
            ("installation", {"repository_creation": "write"},
             {"repository_creation": "write", "administration": "write"},
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

    def test_only_revoked_credentials_restart_onboarding_after_a_github_failure(self):
        for status, starts in ((401, True), (403, False), (None, False)):
            with self.subTest(status=status), \
                    mock.patch.object(bot, "validate_remote_app", side_effect=bot.GitHubError("failed", status)), \
                    mock.patch.object(bot, "onboard") as onboard, \
                    mock.patch.object(bot, "verify_ready", side_effect=bot.IdentityError("stop before settings")):
                with self.assertRaises(bot.IdentityError):
                    bot.setup(onboard_key=True)
                self.assertEqual(starts, onboard.called)

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
                    bot.setup()
                    bot.setup(check=True)
                    original_path = os.environ["PATH"]
                    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(real), original_path])}):
                        bot.setup(check=True)
                    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([str(home / "new tools"), original_path])}):
                        with self.assertRaisesRegex(bot.IdentityError, "host settings are stale"):
                            bot.setup(check=True)
                    entries = original_path.split(os.pathsep)
                    with mock.patch.dict(os.environ, {"PATH": os.pathsep.join([*entries[1:], entries[0]])}):
                        with self.assertRaisesRegex(bot.IdentityError, "host settings are stale"):
                            bot.setup(check=True)
                    claude = home / "claude/settings.json"
                    settings = json.loads(claude.read_text(encoding="utf-8"))
                    settings["permissions"]["deny"].remove(bot.MCP_DENY[0])
                    claude.write_text(json.dumps(settings), encoding="utf-8")
                    with self.assertRaisesRegex(bot.IdentityError, "write restrictions are missing"):
                        bot.setup(check=True)
                    del settings["permissions"]
                    claude.write_text(json.dumps(settings), encoding="utf-8")
                    with self.assertRaisesRegex(bot.IdentityError, "host settings are missing"):
                        bot.setup(check=True)
                    bot.setup()
                    bot.setup(check=True)
                bot.write_private(bot.store() / "tokens/tomjseery-bot-installations.json", INSTALLED)
                bot.write_private(bot.store() / "tokens/tomjseery-bot-tomjseery.json",
                                  {"token": "fixture-token", "expires": 4102444800})
                settings = json.loads((home / "claude/settings.json").read_text(encoding="utf-8"))["env"]
                result = subprocess.run([str(bot.shim_directory() / launcher.name), "api", "repos/tomjseery/smoke"],
                                        cwd=home, env={**environment, **settings}, capture_output=True,
                                        text=True, timeout=30, check=True)
                self.assertEqual("BOT", result.stdout.strip())
                self.assertNotIn("TJ_AGENT", os.environ)
        subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, timeout=30, check=True)


def bot_toml(text):
    import tomllib
    return tomllib.loads(text)


if __name__ == "__main__":
    unittest.main()
