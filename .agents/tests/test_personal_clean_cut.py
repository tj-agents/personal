import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / ".agents/personal/policy/rules"
GATE = POLICY / "scripts/clean_cut.py"
CONTEXT = POLICY / "scripts/session-context.py"


def skill(name: str) -> str:
    return f"---\nname: {name}\ndescription: Example.\n---\n\n# {name}\n"


class CleanCutGateTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.git("init", "-q")
        self.write(
            ".agents/plugins.json", json.dumps({"plugins": ["personal@tj-agents"]})
        )
        self.write(".agents/demo/contract/old/SKILL.md", skill("old"))
        self.write(".agents/demo/contract/kept/SKILL.md", skill("kept"))
        self.write("README.md", "Use `demo:old` and `demo:old-extra`.\n")
        self.write("plugins/demo/skills/old/SKILL.md", "See `demo:old`.\n")
        self.git("add", "-A")
        self.git(
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-qm",
            "init",
        )

    def git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), *arguments], check=True, capture_output=True
        )

    def write(self, relative: str, body: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")

    def gate(self, command: str | list[str], **tool_input: str) -> str:
        payload = {
            "tool_name": "Bash",
            "cwd": str(self.root),
            "tool_input": {"command": command, **tool_input},
        }
        result = subprocess.run(
            [sys.executable, "-B", str(GATE)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=True,
        )
        if not result.stdout:
            return ""
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual("deny", output["permissionDecision"])
        reason: str = output["permissionDecisionReason"]
        return reason

    def test_deleting_a_skill_still_named_elsewhere_blocks_the_commit(self) -> None:
        self.git("rm", "-rq", ".agents/demo/contract/old")
        reason = self.gate('git commit -m "Remove old"')
        self.assertIn("README.md:1:", reason)
        self.assertNotIn("plugins/demo", reason)

    def test_renaming_a_skill_in_place_blocks_until_references_migrate(self) -> None:
        self.write(".agents/demo/contract/old/SKILL.md", skill("new"))
        self.git("add", "-A")
        self.assertTrue(self.gate("git commit -m rename"))
        self.write("README.md", "Use `demo:new` and `demo:old-extra`.\n")
        self.git("add", "-A")
        self.assertEqual("", self.gate("git commit -m rename"))

    def test_commit_all_checks_unstaged_removal(self) -> None:
        (self.root / ".agents/demo/contract/old/SKILL.md").unlink()
        self.assertEqual("", self.gate("git commit -m staged-only"))
        for command in (
            "git commit -am all",
            'git commit -m "all of it" -a',
            "git commit -m x --all",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.gate(command))

    def test_commit_directory_follows_chained_moves_and_workdir(self) -> None:
        (self.root / "sub").mkdir()
        self.git("rm", "-rq", ".agents/demo/contract/old")
        name = self.root.name
        self.assertTrue(self.gate(f"cd .. && cd {name}/sub && git commit -m x"))
        self.assertTrue(self.gate("git commit -m x", workdir=str(self.root / "sub")))

    def test_codex_list_command_and_pathspec_commits_are_inspected(self) -> None:
        (self.root / ".agents/demo/contract/old/SKILL.md").unlink()
        name = self.root.name
        self.assertTrue(self.gate(["bash", "-lc", f"cd ../{name} && git commit -am x"]))
        self.assertTrue(
            self.gate('git commit -m "drop it" .agents/demo/contract/old/SKILL.md')
        )

    def test_chained_staging_is_inspected_or_split(self) -> None:
        (self.root / ".agents/demo/contract/old/SKILL.md").unlink()
        self.assertTrue(self.gate("git add -A && git commit -m x"))
        self.git("checkout", "--", ".")
        self.assertIn(
            "separate calls",
            self.gate("git rm -r .agents/demo/contract/old && git commit -m x"),
        )

    def test_an_uninspectable_commit_is_denied(self) -> None:
        self.git("rm", "-rq", ".agents/demo/contract/old")
        (self.root / ".git/index").write_bytes(b"corrupt")
        self.assertIn("could not inspect", self.gate("git commit -m x"))

    def test_only_the_command_is_parsed(self) -> None:
        self.git("rm", "-rq", ".agents/demo/contract/old")
        self.assertEqual(
            "",
            self.gate("git grep demo:old", description="Find refs before git commit"),
        )

    def test_projects_without_personal_selection_are_not_gated(self) -> None:
        self.write(".agents/plugins.json", json.dumps({"plugins": []}))
        self.git("rm", "-rq", ".agents/demo/contract/old")
        self.assertEqual("", self.gate("git commit -m x"))


class SessionContextTests(unittest.TestCase):
    def context(self, cwd: Path) -> str:
        result = subprocess.run(
            [sys.executable, "-B", str(CONTEXT)],
            input=json.dumps({"cwd": str(cwd)}),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def test_emits_the_policy_body_in_a_selecting_project(self) -> None:
        output = json.loads(self.context(ROOT))["hookSpecificOutput"]
        self.assertEqual("SessionStart", output["hookEventName"])
        body = (
            (POLICY / "SKILL.md")
            .read_text(encoding="utf-8")
            .split("\n---\n", 1)[1]
            .strip()
        )
        self.assertIn(body, output["additionalContext"])

    def test_is_silent_outside_a_selecting_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "-C", directory, "init", "-q"], check=True)
            self.assertEqual("", self.context(Path(directory)))
