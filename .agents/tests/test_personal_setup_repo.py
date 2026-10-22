from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/setup/repo/scripts/setup_repo.py"
spec = importlib.util.spec_from_file_location("personal_setup_repo", SCRIPT)
setup_repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_repo)


class AdoptTests(unittest.TestCase):
    def plugins(self, root: Path, value: object) -> None:
        path = root / ".agents/plugins.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def generated_workflow(self, root: Path) -> Path:
        path = root / setup_repo.CI_CALLER
        path.parent.mkdir(parents=True)
        path.write_text(setup_repo.CI_CALLER_MARKER, encoding="utf-8")
        return path

    def test_malformed_selection_stops_before_a_selection_tool_or_local_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = {
                "schema_version": 1,
                "plugins": ["personal@tj-agents"],
                "marketplaces": {"tj-agents": {"repository": "tj-agents/marketplace"}},
            }
            malformed = (
                {**base, "plugins": "personal@tj-agents"},
                {**base, "plugins": ["personal@tj-agents", 1]},
                {**base, "marketplaces": "tj-agents"},
                {**base, "marketplaces": {"tj-agents": "marketplace"}},
                {
                    **base,
                    "marketplaces": {
                        "tj-agents": {"repository": ["tj-agents/marketplace"]}
                    },
                },
            )
            for selection in malformed:
                with self.subTest(selection=selection):
                    self.plugins(root, selection)
                    with (
                        mock.patch.object(setup_repo, "native_plan") as plan,
                        mock.patch.object(setup_repo.subprocess, "run") as run,
                        self.assertRaisesRegex(
                            ValueError, "invalid personal plugin selection"
                        ),
                    ):
                        setup_repo.run(root, "write", root / "selection-tool.py")
                    plan.assert_not_called()
                    run.assert_not_called()
            self.assertFalse((root / "AGENTS.md").exists())

    def test_resolver_fixture_rejects_an_external_workflow_before_retirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            path = self.generated_workflow(root)
            external = Path(directory) / "external.yml"
            external.write_text(setup_repo.CI_CALLER_MARKER, encoding="utf-8")
            original = Path.resolve

            def resolve(value: Path, strict: bool = False) -> Path:
                if value == path:
                    return external
                return original(value, strict=strict)

            with (
                mock.patch.object(
                    setup_repo.Path, "resolve", autospec=True, side_effect=resolve
                ),
                self.assertRaisesRegex(ValueError, "linked outside"),
            ):
                setup_repo.ci_caller_removal(root)
            self.assertTrue(path.exists())
            self.assertTrue(external.exists())

    @unittest.skipIf(os.name == "nt", "Windows uses the resolver fixture")
    def test_parent_symlink_to_external_workflow_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            external = Path(directory) / "external"
            external.mkdir()
            (external / "check-personal-policy.yml").write_text(
                setup_repo.CI_CALLER_MARKER, encoding="utf-8"
            )
            (root / ".github").mkdir()
            (root / ".github/workflows").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "linked outside"):
                setup_repo.ci_caller_removal(root)


if __name__ == "__main__":
    unittest.main()
