from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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
        self.selection.write_text(json.dumps({
            "schema_version": 1,
            "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
            "plugins": ["base@tj-agents", "personal@tj-agents"],
        }), encoding="utf-8")

    def test_native_delivery_preserves_import_and_unrelated_instructions(self):
        (self.root / "AGENTS.md").write_text("# Project\n\nKeep this rule.\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        self.assertEqual(0, adopt.run(self.root, "write", None))
        body = (self.root / "AGENTS.md").read_text()
        self.assertTrue(body.startswith("# Project\n\nKeep this rule.\n"))
        self.assertIn("Keep one current supported solution.", body)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())
        self.assertEqual(0, adopt.run(self.root, "check", None))
        self.assertEqual(0, adopt.run(self.root, "write", None))
        self.assertEqual(body, (self.root / "AGENTS.md").read_text())

    def test_independent_claude_instructions_receive_the_same_policy(self):
        (self.root / "CLAUDE.md").write_text("Claude-only rule.\n", encoding="utf-8")
        adopt.run(self.root, "write", None)
        self.assertIn(adopt.fragment(), (self.root / "CLAUDE.md").read_text())
        self.assertIn(adopt.fragment(), (self.root / "AGENTS.md").read_text())

    def test_documented_import_example_is_not_treated_as_actual_delivery(self):
        path = self.root / "CLAUDE.md"
        path.write_text("# Documentation\n\n```markdown\n@AGENTS.md\n```\n", encoding="utf-8")
        adopt.run(self.root, "write", None)
        self.assertIn(adopt.fragment(), path.read_text())

    def test_check_detects_policy_drift_and_write_repairs_it(self):
        adopt.run(self.root, "write", None)
        path = self.root / "AGENTS.md"
        path.write_text(path.read_text().replace("Keep one current supported solution.", "Keep all old paths."))
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
        for invalid in (adopt.START, adopt.END, adopt.fragment() + "\n" + adopt.fragment()):
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

    def test_ci_guard_drift_is_detected_and_unrelated_workflow_is_preserved(self):
        adopt.run(self.root, "write", None)
        workflow = self.root / ".github/workflows/check-personal-policy.yml"
        workflow.unlink()
        self.assertEqual(1, adopt.run(self.root, "check", None))
        workflow.write_text("name: Unrelated workflow\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unrelated"):
            adopt.run(self.root, "write", None)
        self.assertEqual("name: Unrelated workflow\n", workflow.read_text())

    def test_this_repository_adopts_the_same_policy_it_ships(self):
        self.assertEqual(0, adopt.run(ROOT, "check", None))

    def test_packaged_canonical_utility_can_check_a_consumer(self):
        adopt.run(self.root, "write", None)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "plugins/personal/.agents/personal/utility/adopt/scripts/adopt.py"),
                                 "--root", str(self.root), "--mode", "check"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
