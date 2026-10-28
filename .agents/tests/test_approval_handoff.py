from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/personal/utility/bot-identity/scripts"
PULLS = [
    "https://github.com/tj-agents/core/pull/527",
    "https://github.com/tj-agents/cli/pull/21",
]


def load_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def approval(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    bot = load_module("bot_identity")
    monkeypatch.setitem(sys.modules, "bot_identity", bot)
    return load_module("prepare_approval")


def test_targets_are_validated_and_deduplicated(approval: ModuleType) -> None:
    assert approval.approval_targets(
        [PULLS[0], "https://github.com/TJ-Agents/Core/pull/527/"]
    ) == [PULLS[0]]


@pytest.mark.parametrize(
    "values",
    [
        [],
        ["https://github.com/Infonetica/work/pull/1"],
        [PULLS[0] + "\nwhoami"],
        [PULLS[0] + "?anything=true"],
        ["https://github.com/tj-agents/core/pull/0"],
    ],
)
def test_invalid_targets_are_refused(approval: ModuleType, values: list[str]) -> None:
    with pytest.raises(approval.bot_identity.IdentityError):
        approval.approval_targets(values)


def test_preparation_copies_without_authenticating_or_printing_command(
    approval: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    copier = tmp_path / "copy_draft.py"
    captured = tmp_path / "captured.json"
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
    with (
        mock.patch.object(approval.bot_identity, "real_gh", return_value="real gh"),
        mock.patch.object(
            approval.bot_identity,
            "app_record",
            side_effect=AssertionError("no credentials"),
        ),
        mock.patch.object(
            approval.bot_identity,
            "run_gh",
            side_effect=AssertionError("no GitHub calls"),
        ),
    ):
        assert (
            approval.main(
                ["--shell", "bash", "--clipboard-script", str(copier), *PULLS]
            )
            == 0
        )
    copied = json.loads(captured.read_text(encoding="utf-8"))
    output = capsys.readouterr().out
    assert copied["text"].startswith("!")
    assert "\n" not in copied["text"]
    assert "--plain-only" in copied["args"]
    assert output.startswith("Copied ")
    assert "auth token" not in output
    assert PULLS[0] not in output


def test_clipboard_failure_does_not_report_success(
    approval: ModuleType, tmp_path: Path
) -> None:
    copier = tmp_path / "copy_draft.py"
    copier.write_text("", encoding="utf-8")
    with (
        mock.patch.object(approval.bot_identity, "real_gh", return_value="real gh"),
        pytest.raises(
            approval.bot_identity.IdentityError, match="clipboard unavailable"
        ),
    ):
        approval.prepare_approval(
            PULLS,
            approval.Shell.BASH,
            copier,
            run=lambda *args, **kwargs: subprocess.CompletedProcess(
                [], 9, "", "clipboard unavailable"
            ),
        )


@pytest.mark.parametrize("shell_name", ["bash", "powershell"])
@pytest.mark.parametrize("failure_code", [0, 17, 23])
def test_human_command_preserves_arguments_and_stops_after_failures(
    approval: ModuleType, tmp_path: Path, shell_name: str, failure_code: int
) -> None:
    shell = approval.Shell(shell_name)
    executable = shutil.which("bash" if shell is approval.Shell.BASH else "pwsh")
    if executable is None:
        pytest.skip(f"{shell} is not installed")
    root = tmp_path / "approval café 'quoted'"
    root.mkdir()
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
        f"    sys.exit({17 if failure_code == 17 else 0})\n"
        f"sys.exit({23 if failure_code == 23 else 0})\n",
        encoding="utf-8",
    )
    if shell is approval.Shell.BASH:
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
    assert result.returncode == failure_code, result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["args"] == ["auth", "token", "--user", "tomjseery"]
    assert calls[0]["token"] is None
    assert calls[0]["other"] is None
    assert calls[0]["config"] is None
    reviews = calls[1:]
    assert len(reviews) == {0: 2, 17: 0, 23: 1}[failure_code]
    for target, call in zip(PULLS, reviews, strict=False):
        assert call["args"] == ["pr", "review", "--approve", target]
        assert call["token"] == "fixture-human-token"
        assert call["other"] is None
        assert call["config"] is None
    assert "fixture-human-token" not in result.stdout + result.stderr
