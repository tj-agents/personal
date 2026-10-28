from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/use/scripts/use.py"
spec = importlib.util.spec_from_file_location("personal_use", SCRIPT)
use = importlib.util.module_from_spec(spec)
spec.loader.exec_module(use)


class UseTests(unittest.TestCase):
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
        self.assertEqual(0, use.run(self.root, "write", None))
        body = (self.root / "AGENTS.md").read_text()
        self.assertTrue(body.startswith("# Project\n\nKeep this rule.\n"))
        self.assertIn("Keep one current supported solution.", body)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())
        self.assertEqual(0, use.run(self.root, "check", None))
        self.assertEqual(0, use.run(self.root, "write", None))
        self.assertEqual(body, (self.root / "AGENTS.md").read_text())

    def test_git_symlink_emulation_is_refused_before_any_native_writes(self):
        def git(*arguments, **kwargs):
            return subprocess.run(["git", "-C", str(self.root), *arguments],
                                  capture_output=True, text=True, check=True, **kwargs)

        git("init", "-q")
        git("config", "core.symlinks", "false")
        blob = git("hash-object", "-w", "--stdin", input="target.md").stdout.strip()
        for name in ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(name=name):
                path = self.root / name
                path.write_text("target.md", encoding="utf-8")
                git("update-index", "--add", "--cacheinfo", "120000", blob, name)
                self.assertFalse(path.is_symlink())
                before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                for mode in ("preview", "write", "check"):
                    with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "tracked instruction link"):
                        use.run(self.root, mode, None)
                    self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
                git("update-index", "--force-remove", name)
                path.unlink()

    def test_independent_claude_instructions_move_to_agents_before_policy_projection(self):
        (self.root / "CLAUDE.md").write_text("Claude-only rule.\n", encoding="utf-8")
        use.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertIn("Claude-only rule.", agents)
        self.assertIn(use.fragment(), agents)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())

    def test_documented_import_example_is_not_treated_as_actual_delivery(self):
        path = self.root / "CLAUDE.md"
        path.write_text("# Documentation\n\n```markdown\n@AGENTS.md\n```\n", encoding="utf-8")
        use.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertIn("```markdown\n@AGENTS.md\n```", agents)
        self.assertIn(use.fragment(), agents)
        self.assertEqual("@AGENTS.md\n", path.read_text())

    def test_claude_policy_block_is_removed_before_merging_distinct_instructions(self):
        (self.root / "CLAUDE.md").write_text("Claude-only rule.\n\n" + use.fragment() + "\n", encoding="utf-8")
        use.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertEqual(1, agents.count(use.START))
        self.assertIn("Claude-only rule.", agents)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())

    def test_relative_agents_import_is_treated_as_the_same_pointer(self):
        (self.root / "CLAUDE.md").write_text("@./AGENTS.md\n", encoding="utf-8")
        use.run(self.root, "write", None)
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())
        self.assertNotIn("@./AGENTS.md", (self.root / "AGENTS.md").read_text())

    def test_other_claude_only_imports_are_refused_rather_than_copied(self):
        (self.root / "CLAUDE.md").write_text("@docs/extra.md\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "imports docs/extra.md"):
            use.run(self.root, "write", None)
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_retry_after_partial_write_does_not_duplicate_merged_content(self):
        claude = self.root / "CLAUDE.md"
        claude.write_text("Claude-only rule.\n", encoding="utf-8")
        use.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        self.assertEqual(1, agents.count("Claude-only rule."))
        claude.write_text("Claude-only rule.\n", encoding="utf-8")
        use.run(self.root, "write", None)
        agents_again = (self.root / "AGENTS.md").read_text()
        self.assertEqual(agents, agents_again)
        self.assertEqual(1, agents_again.count("Claude-only rule."))

    def test_mirrored_claude_md_is_not_merged_again(self):
        (self.root / "AGENTS.md").write_text("# Project\n\nKeep this rule.\n", encoding="utf-8")
        use.run(self.root, "write", None)
        agents = (self.root / "AGENTS.md").read_text()
        (self.root / "CLAUDE.md").write_text(agents, encoding="utf-8")
        use.run(self.root, "write", None)
        self.assertEqual(agents, (self.root / "AGENTS.md").read_text())
        self.assertEqual("@AGENTS.md\n", (self.root / "CLAUDE.md").read_text())

    def test_check_detects_policy_drift_and_write_repairs_it(self):
        use.run(self.root, "write", None)
        path = self.root / "AGENTS.md"
        path.write_text(path.read_text().replace("Keep one current supported solution.", "Keep all old paths."))
        self.assertEqual(1, use.run(self.root, "check", None))
        use.run(self.root, "write", None)
        self.assertEqual(0, use.run(self.root, "check", None))

    def test_retired_current_solution_block_fails_check_and_write_replaces_it_in_place(self):
        retired = ("<!-- BEGIN personal:current-solution sha256:" + "0" * 64 + " -->\nOld policy.\n"
                   "<!-- END personal:current-solution -->")
        path = self.root / "AGENTS.md"
        for existing in (f"# Project\n\n{retired}\n\nKeep this rule.\n",
                         f"# Project\n\n{retired}\n\nKeep this rule.\n\n{use.fragment()}\n"):
            with self.subTest(existing=existing):
                path.write_text(existing, encoding="utf-8")
                self.assertEqual(1, use.run(self.root, "check", None))
                self.assertEqual(0, use.run(self.root, "write", None))
                self.assertEqual(f"# Project\n\n{use.fragment()}\n\nKeep this rule.\n", path.read_text())
                self.assertEqual(0, use.run(self.root, "check", None))

    def test_preview_writes_nothing_and_missing_selection_is_rejected(self):
        self.assertEqual(0, use.run(self.root, "preview", None))
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.selection.unlink()
        with self.assertRaisesRegex(ValueError, "select personal@tj-agents"):
            use.run(self.root, "write", None)
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_broken_or_duplicate_markers_prevent_all_native_writes(self):
        for invalid in (use.START, use.END, use.fragment() + "\n" + use.fragment(), use.RETIRED_START):
            with self.subTest(invalid=invalid):
                (self.root / "CLAUDE.md").write_text(invalid, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "markers"):
                    use.run(self.root, "write", None)
                self.assertFalse((self.root / "AGENTS.md").exists())

    def test_retired_alias_reintroduction_is_rejected(self):
        path = self.root / ".agents/plugins/payloads.json"
        path.parent.mkdir()
        for field in ("compatibilityAliases", "compatibilitySkillAliases"):
            path.write_text(json.dumps({field: {"old": {"replacedBy": "current"}}}))
            with self.assertRaisesRegex(ValueError, "remove retained"):
                use.run(self.root, "check", None)

    def test_core_selection_failure_cannot_write_native_policy(self):
        tool = self.root / "selection.py"
        tool.write_text("raise SystemExit(7)\n")
        self.assertEqual(7, use.run(self.root, "write", tool))
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_generated_ci_caller_is_retired_and_unrelated_workflow_is_preserved(self):
        use.run(self.root, "write", None)
        caller = self.root / ".github/workflows/check-personal-policy.yml"
        caller.parent.mkdir(parents=True, exist_ok=True)
        caller.write_text(use.CI_CALLER_MARKER + "name: Check personal policy\n", encoding="utf-8")
        self.assertEqual(1, use.run(self.root, "check", None))
        use.run(self.root, "write", None)
        self.assertFalse(caller.exists())
        caller.write_text("name: Unrelated workflow\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unrelated"):
            use.run(self.root, "write", None)
        self.assertEqual("name: Unrelated workflow\n", caller.read_text())

    def test_the_merge_answer_is_declared_once_and_changed_only_when_given(self):
        policy = self.root / ".github/merge-policy.json"
        self.assertEqual(0, use.run(self.root, "write", None))
        self.assertFalse(policy.exists())
        self.assertEqual(0, use.run(self.root, "write", None, False))
        self.assertEqual({"agents_may_merge": False}, json.loads(policy.read_text()))
        policy.write_text(json.dumps({"agents_may_merge": False, "required_checks": ["ci-required"]}))
        self.assertEqual(0, use.run(self.root, "write", None))
        self.assertEqual(0, use.run(self.root, "write", None, True))
        self.assertEqual({"agents_may_merge": True, "required_checks": ["ci-required"]}, json.loads(policy.read_text()))
        self.assertEqual(0, use.run(self.root, "check", None))

    def test_preview_shows_the_merge_policy_without_writing_it(self):
        self.assertEqual(0, use.run(self.root, "preview", None, True))
        self.assertFalse((self.root / ".github/merge-policy.json").exists())

    def test_invalid_merge_policy_stops_before_any_write(self):
        (self.root / ".github").mkdir()
        (self.root / ".github/merge-policy.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            use.run(self.root, "write", None, True)
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_this_repository_adopts_the_same_policy_it_ships(self):
        self.assertEqual(0, use.run(ROOT, "check", None))

    def test_packaged_canonical_utility_can_check_a_consumer(self):
        use.run(self.root, "write", None)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "plugins/personal/.agents/personal/utility/use/scripts/use.py"),
                                 "--root", str(self.root), "--mode", "check"], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
