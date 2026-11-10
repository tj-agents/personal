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
    launcher, content = bot.gh_launcher(shim / "bot_identity.py")
    launcher.write_bytes(content)
    if os.name != "nt":
        launcher.chmod(0o755)
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
        "gh.exe" if bot.WINDOWS else "gh",
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
def test_converge_rebuilds_stale_gh_launchers(
    shim: Path, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(bot, "WINDOWS", windows)
    installed(shim, APPROVE.read_bytes())
    launcher, expected = bot.gh_launcher(shim / "bot_identity.py")
    launcher.write_bytes(b"stale launcher")

    assert bot.converge_shims() == [launcher]
    assert launcher.read_bytes() == expected
    if not windows and os.name != "nt":
        assert launcher.stat().st_mode & 0o777 == 0o755
    changed = launcher.stat().st_mtime_ns
    assert bot.converge_shims() == []
    assert launcher.stat().st_mtime_ns == changed


def test_converge_sets_posix_launcher_permissions_before_publishing(
    shim: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "WINDOWS", False)
    installed(shim, APPROVE.read_bytes())
    launcher = shim / "gh"
    launcher.write_bytes(b"stale launcher")
    chmod, replace = Path.chmod, Path.replace
    events: list[str] = []

    def set_mode(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        if path.name.endswith(".next"):
            events.append("executable" if mode == 0o755 else "wrong-mode")
        chmod(path, mode, follow_symlinks=follow_symlinks)

    def publish(path: Path, target: str | Path) -> Path:
        if target == launcher:
            events.append("published")
            if os.name != "nt":
                assert path.stat().st_mode & 0o777 == 0o755
        return replace(path, target)

    monkeypatch.setattr(Path, "chmod", set_mode)
    monkeypatch.setattr(Path, "replace", publish)

    assert bot.converge_shims() == [launcher]
    assert events == ["executable", "published"]


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
    installed(shim, APPROVE.read_bytes())
    executable = shim / "gh.exe"
    with zipfile.ZipFile(
        io.BytesIO(bot.windows_executable(shim / "bot_identity.py"))
    ) as payload:
        stale_main = payload.read("__main__.py").decode().splitlines(keepends=True)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as payload:
        payload.writestr("__main__.py", "".join(stale_main[:1] + stale_main[2:]))
    executable.write_bytes(
        bot.script_launcher()
        + f'#!"{sys.executable}" -B\n'.encode()
        + archive.getvalue()
    )
    assert executable in bot.converge_shims()
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
