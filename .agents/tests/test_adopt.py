from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/adopt/scripts/adopt.py"
spec = importlib.util.spec_from_file_location("personal_adopt", SCRIPT)
adopt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adopt)


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / ".agents").mkdir()
        self.selection = self.root / ".agents/plugins.json"
        self.selection.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "marketplaces": {
                        "tj-agents": {"repository": "tj-agents/marketplace"}
                    },
                    "plugins": ["base@tj-agents", "personal@tj-agents"],
                }
            ),
            encoding="utf-8",
        )

    def test_native_delivery_preserves_import_and_unrelated_instructions(self):
        (self.root / "AGENTS.md").write_text(
            "# Project\n\nKeep this rule.\n", encoding="utf-8"
        )
        (self.root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        self.assertEqual(0, adopt.run(self.root, "write", None))
        body = (self.root / "AGENTS.md").read_text()
        self.assertTrue(body.startswith("# Project\n\nKeep this rule.\n"))
        self.assertIn("Keep one current supported solution.", body)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())
        self.assertEqual(0, adopt.run(self.root, "check", None))
        self.assertEqual(0, adopt.run(self.root, "write", None))
        self.assertEqual(body, (self.root / "AGENTS.md").read_text())

    def test_git_symlink_emulation_is_refused_before_any_native_writes(self):
        def git(*arguments, **kwargs):
            return subprocess.run(
                ["git", "-C", str(self.root), *arguments],
                capture_output=True,
                text=True,
                check=True,
                **kwargs,
            )

        git("init", "-q")
        git("config", "core.symlinks", "false")
        blob = git("hash-object", "-w", "--stdin", input="target.md").stdout.strip()
        for name in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text("target.md", encoding="utf-8")
                git("update-index", "--add", "--cacheinfo", "120000", blob, name)
                self.assertFalse(path.is_symlink())
                before = {
                    p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()
                }
                for mode in ("preview", "write", "check"):
                    with (
                        self.subTest(mode=mode),
                        self.assertRaisesRegex(ValueError, "tracked instruction link"),
                    ):
                        adopt.run(self.root, mode, None)
                    self.assertEqual(
                        before,
                        {
                            p: p.read_bytes()
                            for p in self.root.rglob("*")
                            if p.is_file()
                        },
                    )
                git("update-index", "--force-remove", name)
                path.unlink()

    def test_independent_claude_instructions_move_to_agents_before_policy_projection(
        self,
    ):
        (self.root / "CLAUDE.md").write_text("Claude-only rule.\n", encoding="utf-8")
        adopt.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertIn("Claude-only rule.", agents)
        self.assertIn(adopt.fragment(), agents)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())

    def test_documented_import_example_is_not_treated_as_actual_delivery(self):
        path = self.root / "CLAUDE.md"
        path.write_text(
            "# Documentation\n\n```markdown\n@AGENTS.md\n```\n", encoding="utf-8"
        )
        adopt.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertIn("```markdown\n@AGENTS.md\n```", agents)
        self.assertIn(adopt.fragment(), agents)
        self.assertEqual("@AGENTS.md\n", path.read_text())

    def test_claude_policy_block_is_removed_before_merging_distinct_instructions(self):
        (self.root / "CLAUDE.md").write_text(
            "Claude-only rule.\n\n" + adopt.fragment() + "\n", encoding="utf-8"
        )
        adopt.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertEqual(1, agents.count(adopt.START))
        self.assertIn("Claude-only rule.", agents)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())

    def test_check_detects_policy_drift_and_write_repairs_it(self):
        adopt.run(self.root, "write", None)
        path = self.root / "AGENTS.md"
        path.write_text(
            path.read_text().replace(
                "Keep one current supported solution.", "Keep all old paths."
            )
        )
        self.assertEqual(1, adopt.run(self.root, "check", None))
        adopt.run(self.root, "write", None)
        self.assertEqual(0, adopt.run(self.root, "check", None))

    def test_preview_writes_nothing_and_missing_selection_is_rejected(self):
        self.assertEqual(0, adopt.run(self.root, "preview", None))
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.selection.unlink()
        with self.assertRaisesRegex(ValueError, "select personal@tj-agents"):
            adopt.run(self.root, "write", None)
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_broken_or_duplicate_markers_prevent_all_native_writes(self):
        for invalid in (
            adopt.START,
            adopt.END,
            adopt.fragment() + "\n" + adopt.fragment(),
        ):
            with self.subTest(invalid=invalid):
                (self.root / "CLAUDE.md").write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "markers"):
                    adopt.run(self.root, "write", None)
                self.assertFalse((self.root / "AGENTS.md").exists())

    def test_retired_alias_reintroduction_is_rejected(self):
        path = self.root / ".agents/plugins/payloads.json"
        path.parent.mkdir()
        for field in ("compatibilityAliases", "compatibilitySkillAliases"):
            path.write_text(json.dumps({field: {"old": {"replacedBy": "current"}}}))
            with self.assertRaisesRegex(ValueError, "remove retained"):
                adopt.run(self.root, "check", None)

    def test_core_selection_failure_cannot_write_native_policy(self):
        tool = self.root / "selection.py"
        tool.write_text("raise SystemExit(7)\n")
        self.assertEqual(7, adopt.run(self.root, "write", tool))
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_this_repository_adopts_the_same_policy_it_ships(self):
        self.assertEqual(0, adopt.run(ROOT, "check", None))

    def test_packaged_canonical_utility_can_check_a_consumer(self):
        adopt.run(self.root, "write", None)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(
                    ROOT
                    / "plugins/personal/.agents/personal/utility/adopt/scripts/adopt.py"
                ),
                "--root",
                str(self.root),
                "--mode",
                "check",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
