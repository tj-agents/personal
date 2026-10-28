from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/personal/utility/bot-identity/scripts"
BOT_SPEC = importlib.util.spec_from_file_location(
    "bot_identity", SCRIPTS / "bot_identity.py"
)
assert BOT_SPEC is not None and BOT_SPEC.loader is not None
bot = importlib.util.module_from_spec(BOT_SPEC)
BOT_SPEC.loader.exec_module(bot)
SPEC = importlib.util.spec_from_file_location(
    "prepare_approval", SCRIPTS / "prepare_approval.py"
)
assert SPEC is not None and SPEC.loader is not None
approval = importlib.util.module_from_spec(SPEC)
with mock.patch.dict(sys.modules, {"bot_identity": bot}):
    SPEC.loader.exec_module(approval)

PULLS = [
    "https://github.com/tj-agents/core/pull/527",
    "https://github.com/tj-agents/cli/pull/21",
]


class ApprovalPreparationTests(unittest.TestCase):
    def test_targets_are_validated_and_deduplicated(self) -> None:
        self.assertEqual(
            [PULLS[0]],
            approval.approval_targets(
                [PULLS[0], "https://github.com/TJ-Agents/Core/pull/527/"]
            ),
        )
        for values in (
            [],
            ["https://github.com/Infonetica/work/pull/1"],
            [PULLS[0] + "\nwhoami"],
            [PULLS[0] + "?anything=true"],
            ["https://github.com/tj-agents/core/pull/0"],
        ):
            with self.subTest(values=values), self.assertRaises(bot.IdentityError):
                approval.approval_targets(values)

    def test_preparation_copies_a_literal_line_without_authenticating_or_printing_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="approval café ") as directory:
            root = Path(directory)
            copier = root / "copy_draft.py"
            captured = root / "captured.json"
            copier.write_text(
                "import json, pathlib, sys\n"
                "source = pathlib.Path(sys.argv[sys.argv.index('--path') + 1])\n"
                "draft = source.read_text(encoding='utf-8')\n"
                "record = {'text': draft, 'args': sys.argv[1:]}\n"
                f"target = pathlib.Path({str(captured)!r})\n"
                "target.write_text(json.dumps(record), encoding='utf-8')\n"
                "print(f'Copied {len(draft)} chars (plain text only).')\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                mock.patch.object(bot, "real_gh", return_value="real gh"),
                mock.patch.object(
                    bot, "app_record", side_effect=AssertionError("no credentials")
                ),
                mock.patch.object(
                    bot, "run_gh", side_effect=AssertionError("no GitHub calls")
                ),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(
                    0,
                    approval.main(
                        ["--shell", "bash", "--clipboard-script", str(copier), *PULLS]
                    ),
                )
            copied = json.loads(captured.read_text(encoding="utf-8"))
            self.assertTrue(copied["text"].startswith("!"))
            self.assertNotIn("\n", copied["text"])
            self.assertIn("--plain-only", copied["args"])
            self.assertTrue(output.getvalue().startswith("Copied "))
            self.assertNotIn("auth token", output.getvalue())
            self.assertNotIn(PULLS[0], output.getvalue())

    def test_clipboard_failure_does_not_report_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copier = Path(directory) / "copy_draft.py"
            copier.write_text("", encoding="utf-8")
            with (
                mock.patch.object(bot, "real_gh", return_value="real gh"),
                self.assertRaisesRegex(bot.IdentityError, "clipboard unavailable"),
            ):
                approval.prepare_approval(
                    PULLS,
                    "bash",
                    copier,
                    run=lambda *args, **kwargs: subprocess.CompletedProcess(
                        [], 9, "", "clipboard unavailable"
                    ),
                )


class HumanCommandTests(unittest.TestCase):
    def exercise(
        self, shell: str, auth_failure: bool = False, review_failure: bool = False
    ) -> None:
        executable = shutil.which("bash" if shell == "bash" else "pwsh")
        if executable is None:
            self.skipTest(f"{shell} is not installed")
        with tempfile.TemporaryDirectory(prefix="approval café ") as directory:
            root = Path(directory)
            log = root / "calls.jsonl"
            recorder = root / "record.py"
            recorder.write_text(
                "import json, os, pathlib, sys\n"
                f"target = pathlib.Path({str(log)!r})\n"
                "record = {'args': sys.argv[1:],\n"
                "          'token': os.environ.get('GH_TOKEN'),\n"
                "          'other': os.environ.get('GITHUB_TOKEN'),\n"
                "          'config': os.environ.get('GH_CONFIG_DIR')}\n"
                "with target.open('a', encoding='utf-8') as stream:\n"
                "    stream.write(json.dumps(record) + '\\n')\n"
                "if sys.argv[1:2] == ['auth']:\n"
                "    print('fixture-human-token')\n"
                f"    sys.exit({17 if auth_failure else 0})\n"
                f"sys.exit({23 if review_failure else 0})\n",
                encoding="utf-8",
            )
            if shell == "bash":
                fake_gh = root / "gh fixture"
                fake_gh.write_text(
                    f"#!/bin/sh\nexec {shlex.quote(Path(sys.executable).as_posix())} "
                    f'{shlex.quote(recorder.as_posix())} "$@"\n',
                    encoding="utf-8",
                    newline="\n",
                )
                fake_gh.chmod(0o755)
                command = [
                    executable,
                    "-c",
                    approval.approval_command(PULLS, str(fake_gh), shell)[1:],
                ]
            else:
                fake_gh = root / "gh fixture.ps1"
                fake_gh.write_text(
                    f"& {approval.powershell_literal(sys.executable)} "
                    f"{approval.powershell_literal(str(recorder))} @args\n"
                    "exit $LASTEXITCODE\n",
                    encoding="utf-8",
                )
                command = [
                    executable,
                    "-NoProfile",
                    "-Command",
                    approval.approval_command(PULLS, str(fake_gh), shell)[1:],
                ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
                env={
                    **os.environ,
                    "GH_TOKEN": "agent-token",
                    "GITHUB_TOKEN": "other-token",
                    "GH_CONFIG_DIR": "agent-config",
                },
            )
            self.assertEqual(
                17 if auth_failure else 23 if review_failure else 0,
                result.returncode,
                result.stderr,
            )
            calls = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(["auth", "token", "--user", "tomjseery"], calls[0]["args"])
            self.assertIsNone(calls[0]["token"])
            self.assertIsNone(calls[0]["other"])
            self.assertIsNone(calls[0]["config"])
            reviews = calls[1:]
            self.assertEqual(
                0 if auth_failure else 1 if review_failure else 2, len(reviews)
            )
            for target, call in zip(PULLS, reviews, strict=False):
                self.assertEqual(["pr", "review", "--approve", target], call["args"])
                self.assertEqual("fixture-human-token", call["token"])
                self.assertIsNone(call["other"])
                self.assertIsNone(call["config"])
            self.assertNotIn("fixture-human-token", result.stdout + result.stderr)

    def test_bash_command_preserves_arguments_and_stops_after_failures(self) -> None:
        for auth_failure, review_failure in (
            (False, False),
            (True, False),
            (False, True),
        ):
            with self.subTest(auth_failure=auth_failure, review_failure=review_failure):
                self.exercise("bash", auth_failure, review_failure)

    def test_powershell_command_preserves_arguments_and_stops_after_failures(
        self,
    ) -> None:
        for auth_failure, review_failure in (
            (False, False),
            (True, False),
            (False, True),
        ):
            with self.subTest(auth_failure=auth_failure, review_failure=review_failure):
                self.exercise("powershell", auth_failure, review_failure)


if __name__ == "__main__":
    unittest.main()
