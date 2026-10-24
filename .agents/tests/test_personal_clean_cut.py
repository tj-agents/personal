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

    def gate(self, command: str) -> subprocess.CompletedProcess[str]:
        payload = {
            "tool_name": "Bash",
            "cwd": str(self.root),
            "tool_input": {"command": command},
        }
        return subprocess.run(
            [sys.executable, "-B", str(GATE)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_deleting_a_skill_still_named_elsewhere_blocks_the_commit(self) -> None:
        self.git("rm", "-rq", ".agents/demo/contract/old")
        result = self.gate('git commit -m "Remove old"')
        self.assertEqual(2, result.returncode)
        self.assertIn("README.md:1:", result.stderr)
        self.assertNotIn("plugins/demo", result.stderr)

    def test_renaming_a_skill_in_place_blocks_until_references_migrate(self) -> None:
        self.write(".agents/demo/contract/old/SKILL.md", skill("new"))
        self.git("add", "-A")
        self.assertEqual(2, self.gate("git commit -m rename").returncode)
        self.write("README.md", "Use `demo:new` and `demo:old-extra`.\n")
        self.git("add", "-A")
        self.assertEqual(0, self.gate("git commit -m rename").returncode)

    def test_commit_all_checks_unstaged_removal(self) -> None:
        (self.root / ".agents/demo/contract/old/SKILL.md").unlink()
        self.assertEqual(0, self.gate("git commit -m staged-only").returncode)
        self.assertEqual(2, self.gate("git commit -am all").returncode)

    def test_projects_without_personal_selection_are_not_gated(self) -> None:
        self.write(".agents/plugins.json", json.dumps({"plugins": []}))
        self.git("rm", "-rq", ".agents/demo/contract/old")
        self.assertEqual(0, self.gate("git commit -m x").returncode)


class SessionContextTests(unittest.TestCase):
    def test_emits_the_policy_body_as_session_start_context(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(CONTEXT)],
            capture_output=True,
            text=True,
            check=True,
        )
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual("SessionStart", output["hookEventName"])
        body = (
            (POLICY / "SKILL.md")
            .read_text(encoding="utf-8")
            .split("\n---\n", 1)[1]
            .strip()
        )
        self.assertIn(body, output["additionalContext"])
