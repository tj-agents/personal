import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SKILLS = {
    "use",
    "address-work-item",
    "approve",
    "bot-identity",
    "create-work-item",
    "revision",
    "rules",
    "work-item",
}
EXTERNAL_SKILLS = {
    "engineering": {
        "address-bug",
        "address-debt",
        "address-mistake",
        "feature",
    },
    "agent": {"plugins"},
    "cli": {"clip"},
    "workflow": {"run"},
    "docs": {"layout"},
}


def load(relative: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    return value


class PersonalPackagingTests(unittest.TestCase):
    def test_personal_payload_contains_only_current_skill_entries(self) -> None:
        authored = {}
        for path in (ROOT / ".agents/personal").rglob("SKILL.md"):
            content = path.read_text(encoding="utf-8")
            name_match = re.search(r"^name: (.+)$", content, re.MULTILINE)
            assert name_match is not None
            name = name_match.group(1)
            authored[name] = content
        self.assertEqual(EXPECTED_SKILLS, set(authored))
        for output in ("plugins/personal/skills", ".claude/skills", ".codex/skills"):
            generated = list((ROOT / output).rglob("SKILL.md"))
            self.assertEqual(len(EXPECTED_SKILLS), len(generated))
            for path in generated:
                content = path.read_text(encoding="utf-8")
                name_match = re.search(r"^name: (.+)$", content, re.MULTILINE)
                assert name_match is not None
                name = name_match.group(1)
                target_match = re.search(r"canonical definition\]\(([^)]+)\)", content)
                assert target_match is not None
                target = target_match.group(1)
                self.assertEqual(
                    authored[name],
                    (path.parent / target).resolve().read_text(encoding="utf-8"),
                )

    def test_personal_payload_has_no_retired_provider_runtime_or_host_binding(
        self,
    ) -> None:
        for path in (ROOT / "plugins/personal").rglob("*"):
            if path.is_file() and "bot-identity" not in path.parts:
                self.assertNotIn("credential", path.parts, str(path))
                self.assertNotEqual("credential", path.stem.casefold(), str(path))
                text = path.read_text(encoding="utf-8").casefold()
                for retired in (
                    "azure",
                    "personal:credential",
                    "mcp",
                ):
                    self.assertNotIn(retired, text, str(path))

    def test_personal_harness_owns_the_github_work_item_runtime(self) -> None:
        harness = load("plugins/personal/harness.json")
        self.assertIn(
            ".agents/personal/utility/create/work-item", harness["source_roots"]
        )
        self.assertIn(".agents/personal/utility/work-item", harness["source_roots"])
        self.assertIn(
            ".agents/personal/workflow/address/work-item", harness["source_roots"]
        )

    def test_qualified_references_resolve_to_declared_dependencies(self) -> None:
        for path in (ROOT / ".agents/personal").rglob("SKILL.md"):
            content = path.read_text(encoding="utf-8")
            for namespace, name in re.findall(
                r"`([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)`", content
            ):
                if namespace == "personal":
                    self.assertIn(name, EXPECTED_SKILLS, str(path))
                else:
                    self.assertIn(namespace, EXTERNAL_SKILLS, str(path))
                    self.assertIn(name, EXTERNAL_SKILLS[namespace], str(path))

    def test_work_item_skills_use_the_shared_tracker_cli(self) -> None:
        for skill in ("work-item", "create-work-item", "address-work-item"):
            with self.subTest(skill=skill):
                folder = next(
                    path.parent
                    for path in (ROOT / ".agents/personal").rglob("SKILL.md")
                    if f"name: {skill}\n" in path.read_text(encoding="utf-8")
                )
                text = (folder / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("tj item", text)
                self.assertEqual([], [path.name for path in folder.rglob("*.py")])


if __name__ == "__main__":
    unittest.main()
