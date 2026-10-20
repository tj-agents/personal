from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/bot-identity/scripts/bot_identity.py"
spec = importlib.util.spec_from_file_location("bot_identity", SCRIPT)
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

RECORD = {"slug": "test-bot", "client_id": "Iv1", "key": "unused.pem"}


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def __call__(self, path, bearer, method="GET"):
        self.calls.append((method, path))
        if path == "/app/installations":
            return [{"account": {"login": "tj-agents"}, "id": 7}]
        return {"token": f"ghs_{len(self.calls)}", "expires_at": "2030-01-01T00:00:00Z"}


class IdentityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        patcher = mock.patch.object(bot, "store", return_value=self.home / "github-app")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.github = FakeGitHub()

    def token(self, owner, now=0):
        return bot.installation_token(owner, RECORD, now=now, fetch=self.github, sign=lambda record: "jwt")

    def test_installed_owner_gets_one_cached_token_and_others_get_none(self):
        self.assertEqual("ghs_2", self.token("TJ-Agents"))
        self.assertEqual("ghs_2", self.token("tj-agents"))
        self.assertIsNone(self.token("Infonetica"))
        self.assertEqual(1, sum(method == "POST" for method, _ in self.github.calls))

    def test_an_expiring_token_is_reissued(self):
        first = self.token("tj-agents")
        late = bot.datetime.fromisoformat("2030-01-01T00:00:00+00:00").timestamp() - 60
        self.assertNotEqual(first, self.token("tj-agents", now=late))

    def test_owner_comes_from_repo_flags_and_api_paths(self):
        cases = {("pr", "merge", "-R", "tj-agents/core"): "tj-agents",
                 ("pr", "view", "--repo=Concertable/auth"): "Concertable",
                 ("pr", "list", "-Rtomjseery/winwrap"): "tomjseery",
                 ("api", "repos/tj-agents/core/pulls/1/merge", "-X", "PUT"): "tj-agents",
                 ("pr", "view", "-R", "https://github.com/Concertable/b2b"): "Concertable",
                 ("api", "graphql"): None}
        for arguments, owner in cases.items():
            with self.subTest(arguments=arguments):
                self.assertEqual(owner, bot.owner_from_arguments(list(arguments)))

    def test_credential_helper_answers_only_for_installed_accounts(self):
        with mock.patch.object(bot, "app_record", return_value=RECORD), \
                mock.patch.object(bot, "installation_token", side_effect=lambda owner, record: "ghs_x"
                                  if owner == "tj-agents" else None):
            for path, expected in (("tj-agents/core.git", "password=ghs_x"), ("Infonetica/x.git", "")):
                out = io.StringIO()
                bot.credential("get", io.StringIO(f"protocol=https\nhost=github.com\npath={path}\n\n"), out)
                self.assertIn(expected, out.getvalue())
                if not expected:
                    self.assertEqual("", out.getvalue())

    def test_agent_git_config_replaces_helpers_then_keeps_the_fallbacks(self):
        environment = bot.agent_environment(Path("/s/bot_identity.py"), ["manager", "store"])
        values = [environment[f"GIT_CONFIG_VALUE_{index}"] for index in range(int(environment["GIT_CONFIG_COUNT"]))]
        self.assertEqual(["true", ""], values[:2])
        self.assertTrue(values[2].endswith('bot_identity.py" credential'))
        self.assertEqual(["manager", "store"], values[3:])
        self.assertEqual("1", environment["TJ_AGENT"])


class MergeGateTests(unittest.TestCase):
    def test_sync_covers_every_installed_account_without_the_agent_flag(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs["env"]))
            return mock.Mock(returncode=0)

        with mock.patch.object(bot, "installations", return_value={"tj-agents": 1, "tomjseery": 2}),                 mock.patch.object(bot, "merge_policy_script", return_value=Path("/p/merge_policy.py")),                 mock.patch.dict(bot.os.environ, {"TJ_AGENT": "1"}):
            self.assertEqual(0, bot.merge_gates(RECORD, run=run))
        command, environment = calls[0]
        self.assertEqual(["sync", "--owner", "tj-agents", "--owner", "tomjseery"], command[3:])
        self.assertNotIn("TJ_AGENT", environment)

    def test_schedule_is_hourly_and_replaces_its_own_entry(self):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs.get("input")))
            return mock.Mock(returncode=0, stdout="0 * * * * other\n5 * * * * old # tj-agents-merge-gates\n")

        bot.schedule_merge_gates(Path("/s/bot_identity.py"), run=run)
        if bot.os.name == "nt":
            self.assertIn("hourly", calls[0][0])
            self.assertTrue(calls[0][0][-1].endswith('bot_identity.py" merge-gates'))
        else:
            written = calls[-1][1].splitlines()
            self.assertEqual("0 * * * * other", written[0])
            self.assertEqual(1, sum("tj-agents-merge-gates" in line for line in written))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.environment = {"TJ_AGENT": "1", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b",
                            "GIT_CONFIG_VALUE_0": 'say "hi"'}

    def test_codex_keeps_other_settings_and_is_idempotent(self):
        path = self.root / "config.toml"
        path.write_text('model = "x"\n\n[shell_environment_policy.set]\nKEEP = "1"\nGIT_CONFIG_KEY_9 = "old"\n\n'
                        '[projects.a]\ntrust_level = "trusted"\n', encoding="utf-8")
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
        path.write_text(json.dumps({"env": {"KEEP": "1", "GIT_CONFIG_KEY_9": "old"},
                                    "permissions": {"deny": ["Bash(rm:*)"]}}), encoding="utf-8")
        bot.update_claude(path, self.environment)
        settings = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({"KEEP": "1", **self.environment}, settings["env"])
        self.assertIn("Bash(rm:*)", settings["permissions"]["deny"])
        self.assertIn("mcp__github__merge_pull_request", settings["permissions"]["deny"])


def bot_toml(text):
    import tomllib
    return tomllib.loads(text)


if __name__ == "__main__":
    unittest.main()
