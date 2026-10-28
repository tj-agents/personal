from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

import bot_identity

PULL_REQUEST = re.compile(
    r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)/?"
)


def approval_targets(values: Sequence[str]) -> list[str]:
    targets = []
    for value in values:
        match = PULL_REQUEST.fullmatch(value)
        if match is None or match[1].lower() not in bot_identity.REQUIRED_OWNERS:
            raise bot_identity.IdentityError(
                "expected a PR URL in a supported personal account"
            )
        target = (
            f"https://github.com/{match[1].lower()}/{match[2].lower()}/pull/{match[3]}"
        )
        if target not in targets:
            targets.append(target)
    if not targets:
        raise bot_identity.IdentityError("provide at least one PR URL")
    return targets


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def approval_command(values: Sequence[str], gh: str, shell: str) -> str:
    targets = approval_targets(values)
    if any(character in gh for character in "\r\n\x00"):
        raise bot_identity.IdentityError("the gh executable path must fit on one line")
    if shell == "bash":
        body = (
            f"g={shlex.quote(Path(gh).as_posix())}; "
            'GH_TOKEN=$("$g" auth token --user tomjseery) || exit; export GH_TOKEN; '
            f"for p in {' '.join(shlex.quote(target) for target in targets)}; "
            'do "$g" pr review --approve "$p" || exit; done'
        )
        return (
            "!env -u GH_TOKEN -u GITHUB_TOKEN -u GH_CONFIG_DIR bash -c "
            + shlex.quote(body)
        )
    if shell == "powershell":
        pulls = ",".join(powershell_literal(target) for target in targets)
        return (
            "!& { Remove-Item Env:GH_TOKEN,Env:GITHUB_TOKEN,Env:GH_CONFIG_DIR "
            "-ErrorAction SilentlyContinue; "
            f"$g={powershell_literal(gh)}; "
            "$env:GH_TOKEN=(& $g auth token --user tomjseery); "
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
            f"foreach ($p in @({pulls})) {{ "
            "& $g pr review --approve $p; "
            "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } } }"
        )
    raise bot_identity.IdentityError("supported shells are bash and powershell")


def prepare_approval(
    values: Sequence[str],
    shell: str,
    clipboard_script: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    targets = approval_targets(values)
    clipboard_script = clipboard_script.resolve(strict=True)
    if not clipboard_script.is_file():
        raise bot_identity.IdentityError("the selected cli:clip script is not a file")
    command = approval_command(targets, bot_identity.real_gh(), shell)
    with tempfile.TemporaryDirectory(prefix="tj-approval-") as directory:
        draft = Path(directory) / "approval.txt"
        draft.write_text(command, encoding="utf-8")
        result = run(
            [
                sys.executable,
                "-B",
                str(clipboard_script),
                "--path",
                str(draft),
                "--plain-only",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=bot_identity.TIMEOUT_SECONDS,
            creationflags=bot_identity.NO_WINDOW,
        )
    if result.returncode:
        raise bot_identity.IdentityError(
            result.stderr.strip() or "clipboard copy failed"
        )
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy Tommy's PR approval command to his clipboard."
    )
    parser.add_argument("--shell", choices=("bash", "powershell"), required=True)
    parser.add_argument("--clipboard-script", type=Path, required=True)
    parser.add_argument("pull_requests", nargs="+")
    arguments = parser.parse_args(argv)
    try:
        print(
            prepare_approval(
                arguments.pull_requests, arguments.shell, arguments.clipboard_script
            )
        )
        return 0
    except (bot_identity.IdentityError, OSError, subprocess.SubprocessError) as error:
        print(f"prepare-approval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
