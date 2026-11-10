import importlib.util
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents/personal/utility"
BOT_IDENTITY = SCRIPTS / "bot-identity/scripts/bot_identity.py"
ONBOARDING = SCRIPTS / "bot-identity/scripts/onboarding.py"
PAGE = SCRIPTS / "bot-identity/scripts/onboarding.html"
APPROVE = SCRIPTS / "approve/scripts/approve.py"
PAST = 1_000_000_000_000_000_000


def load_bot_identity() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bot_identity", BOT_IDENTITY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bot = load_bot_identity()


@pytest.fixture
def shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("AGENT_STATE_DIRECTORY", str(tmp_path / "state"))
    monkeypatch.setenv("TJ_BIN_DIR", str(tmp_path / "tj bin"))
    directory = tmp_path / "shim"
    monkeypatch.setattr(bot, "shim_directory", lambda: directory)
    return directory


def installed(shim: Path, approve: bytes) -> None:
    shim.mkdir()
    (shim / "bot_identity.py").write_bytes(BOT_IDENTITY.read_bytes())
    (shim / "onboarding.py").write_bytes(ONBOARDING.read_bytes())
    (shim / "onboarding.html").write_bytes(PAGE.read_bytes())
    (shim / "approve.py").write_bytes(approve)
    for path in shim.iterdir():
        os.utime(path, ns=(PAST, PAST))


def test_converge_replaces_a_stale_copy_and_leaves_identical_ones_untouched(
    shim: Path,
) -> None:
    installed(shim, b"input('Approve these? [y/N] ')\n")

    assert bot.converge_shims() == [shim / "approve.py"]

    assert (shim / "approve.py").read_bytes() == APPROVE.read_bytes()
    for name in ("bot_identity.py", "onboarding.py", "onboarding.html"):
        assert (shim / name).stat().st_mtime_ns == PAST
    assert sorted(path.name for path in shim.iterdir()) == [
        "approve.py",
        "bot_identity.py",
        "onboarding.html",
        "onboarding.py",
    ]
    assert bot.converge_shims() == []


def test_converge_entry_point_replaces_a_stale_wrapper_script(shim: Path) -> None:
    installed(shim, APPROVE.read_bytes())
    (shim / "bot_identity.py").write_bytes(b"stale wrapper\n")

    assert bot.main(["converge"]) == 0

    assert (shim / "bot_identity.py").read_bytes() == BOT_IDENTITY.read_bytes()
    assert (shim / "approve.py").stat().st_mtime_ns == PAST


def test_converge_installs_nothing_before_setup(shim: Path) -> None:
    assert bot.converge_shims() == []
    assert not shim.exists()


@pytest.mark.parametrize("windows", [True, False])
def test_tj_approve_launcher_only_delegates_to_the_converged_copy(
    shim: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(bot, "WINDOWS", windows)
    script, python = shim / "approve.py", Path(sys.executable)

    _, content = bot.approve_launcher()

    expected = (
        f'@"{python}" -B "{script}" %*\r\n'
        if windows
        else f'#!/bin/sh\nexec "{python.as_posix()}" -B "{script.as_posix()}" "$@"\n'
    )
    assert content.decode() == expected


@pytest.mark.parametrize("windows", [True, False])
def test_gh_wrapper_launcher_only_delegates_to_the_converged_copy(
    shim: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(bot, "WINDOWS", windows)
    source = tmp_path / "bot_identity.py"
    source.write_bytes(BOT_IDENTITY.read_bytes())

    script = bot.install_shims(source)

    assert script == shim / "bot_identity.py"
    if windows:
        content = (shim / "gh.exe").read_bytes()
        assert f'#!"{sys.executable}" -B\n'.encode() in content
        with zipfile.ZipFile(io.BytesIO(content)) as payload:
            assert payload.namelist() == ["__main__.py"]
            main = payload.read("__main__.py").decode()
        assert main == (
            f"import runpy, sys\nsys.path.insert(0, {str(script.parent)!r})\n"
            f"sys.argv = [{str(script)!r}, 'gh', *sys.argv[1:]]\n"
            f"runpy.run_path({str(script)!r}, run_name='__main__')\n"
        )
    else:
        python = Path(sys.executable).as_posix()
        assert (shim / "gh").read_text(encoding="utf-8") == (
            f'#!/bin/sh\nexec "{python}" -B "{script.as_posix()}" gh "$@"\n'
        )


def test_windows_launcher_loads_the_actual_shipped_sibling_module(
    shim: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "WINDOWS", True)
    bot.install_shims(BOT_IDENTITY)
    executable = shim / "gh.exe"
    environment = {**os.environ, "TJ_AGENT": "1"}
    command = (
        [str(executable)] if os.name == "nt" else [sys.executable, str(executable)]
    )
    result = subprocess.run(
        [*command, "auth", "login"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 2
    assert "agents may run only `gh auth status`" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
