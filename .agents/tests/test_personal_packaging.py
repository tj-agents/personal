from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SKILLS = {
    "adopt",
    "bug",
    "current-solution",
    "debt",
    "feature",
    "mistake",
    "task",
    "address-bug",
    "address-debt",
    "address-feature",
    "address-mistake",
    "address-task",
}
WORK_ITEM_SKILLS = {
    "manage",
    "write-bug",
    "write-debt",
    "write-feature",
    "write-mistake",
    "write-task",
}


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class PersonalPackagingTests(unittest.TestCase):
    def test_personal_payload_contains_only_current_skill_entries(self) -> None:
        authored = {}
        for path in (ROOT / ".agents/personal").rglob("SKILL.md"):
            content = path.read_text(encoding="utf-8")
            name = re.search(r"^name: (.+)$", content, re.MULTILINE).group(1)
            authored[name] = content
        self.assertEqual(EXPECTED_SKILLS, set(authored))
        for output in ("plugins/personal/skills", ".claude/skills", ".codex/skills"):
            generated = list((ROOT / output).rglob("SKILL.md"))
            self.assertEqual(len(EXPECTED_SKILLS), len(generated))
            for path in generated:
                content = path.read_text(encoding="utf-8")
                name = re.search(r"^name: (.+)$", content, re.MULTILINE).group(1)
                target = re.search(r"canonical definition\]\(([^)]+)\)", content).group(1)
                self.assertEqual(authored[name], (path.parent / target).resolve().read_text(encoding="utf-8"))

    def test_personal_payload_has_no_retired_provider_runtime_or_host_binding(self) -> None:
        for path in (ROOT / "plugins/personal").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8").casefold()
                for retired in ("azure", "personal-work-item", "personal_work_items", "credential", "mcp"):
                    self.assertNotIn(retired, text, str(path))

    def test_personal_harness_requires_shared_github_work_items(self) -> None:
        harness = load("plugins/personal/harness.json")
        self.assertNotIn(".agents/personal/utility/work-item", harness["source_roots"])
        self.assertNotIn(".agents/personal/workflow/address/work-item", harness["source_roots"])
        self.assertIn("tj-agents/work-items", harness["requires"]["plugins"])

    def test_qualified_references_resolve_to_declared_dependencies(self) -> None:
        for path in (ROOT / "plugins/personal/skills").rglob("SKILL.md"):
            content = path.read_text(encoding="utf-8")
            for namespace, name in re.findall(r"`([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)`", content):
                if namespace == "personal":
                    self.assertIn(name, EXPECTED_SKILLS, str(path))
                elif namespace == "work-items":
                    self.assertIn(name, WORK_ITEM_SKILLS, str(path))
                else:
                    self.assertIn(name, {"address-bug", "address-debt", "address-mistake", "feature"}, str(path))


if __name__ == "__main__":
    unittest.main()
