import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/personal/utility/work-item/work_item.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("work_item", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def example(kind="bug"):
    item = module.skeleton(kind)
    return {
        key: value if key == "kind" else f"Observed {key}: café"
        for key, value in item.items()
    }


class WorkItemTests(unittest.TestCase):
    def test_every_kind_requires_real_facts_and_renders_its_sections(self):
        for kind in module.KINDS:
            with self.subTest(kind=kind):
                with self.assertRaises(module.ItemError):
                    module.validate(module.skeleton(kind))
                item = example(kind)
                self.assertEqual(module.validate(item), item)
                first = module.render(item)
                self.assertEqual(
                    first, module.render(dict(reversed(list(item.items()))))
                )
                for name, rule in module.schema_for(kind)["properties"].items():
                    if "title" in rule and name in item:
                        self.assertIn("## " + rule["title"], first)

    def test_invalid_values_are_rejected(self):
        for patch in (
            {"evidence": " "},
            {"kind": "unknown"},
            {"kind": []},
            {"priority": "urgent"},
            {"owner": None},
            {"links": "url"},
            {"links": [None]},
            {"title": "a\nb"},
            {"title": "a" * 257},
            {"extra": "ignored?"},
        ):
            with self.subTest(patch=patch), self.assertRaises(module.ItemError):
                module.validate({**example(), **patch})
        with self.assertRaises(module.ItemError):
            module.validate([])
        with self.assertRaises(module.ItemError):
            module.validate({"kind": "bug", "title": "Bug"})

    def test_unknown_cause_is_valid_and_no_priority_is_invented(self):
        item = {**example("mistake"), "cause": "Unknown; investigation required"}
        self.assertNotIn("Priority:", module.render(item))
        self.assertIn("Unknown; investigation required", module.render(item))

    def test_story_round_trip_requires_user_outcome_facts(self):
        story = {
            key: value if key == "kind" else "Story fact for " + key
            for key, value in module.skeleton("story").items()
        }
        self.assertEqual(module.validate(story), story)
        body = module.render(story)
        for heading in ("User or role", "Goal", "Benefit", "Acceptance criteria"):
            self.assertIn("## " + heading, body)
        with self.assertRaises(module.ItemError):
            module.validate(
                {key: value for key, value in story.items() if key != "goal"}
            )
        template = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "template", "--kind", "story"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(template.returncode, 0, template.stderr)
        self.assertEqual("story", json.loads(template.stdout)["kind"])
        preview = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "preview", "--input", "-"],
            input=json.dumps(story),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(body, json.loads(preview.stdout)["body"])

    def test_legacy_ids_and_links_survive_preview(self):
        item = {
            **example(),
            "legacy_ids": ["BUGS.md#B013"],
            "links": ["https://example.test/evidence"],
        }
        body = module.render(item)
        self.assertIn("BUGS.md#B013", body)
        self.assertIn("https://example.test/evidence", body)

    def test_cli_validates_and_previews_from_stdin_without_git_or_github(self):
        for command in ("validate", "preview"):
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), command, "--input", "-"],
                input=json.dumps(example()),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsInstance(json.loads(result.stdout), dict)
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "validate", "--input", "-"],
            input="broken json",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))


if __name__ == "__main__":
    unittest.main()
