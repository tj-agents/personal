import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.mark.parametrize(
    "entry",
    [
        ".claude/skills/bot-identity/scripts/bot_identity.py",
        ".codex/skills/bot-identity/scripts/bot_identity.py",
        "plugins/personal/skills/bot-identity/scripts/bot_identity.py",
        "plugins/personal/.agents/personal/utility/bot-identity/scripts/bot_identity.py",
    ],
)
def test_generated_entry_imports_its_bundled_library_without_site_packages(
    entry: str,
    tmp_path: Path,
) -> None:
    script = Path(__file__).resolve().parents[2] / entry

    result = subprocess.run(
        [sys.executable, "-E", "-S", "-B", str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )

    assert "usage:" in result.stdout


@pytest.fixture
def bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    script = (
        Path(__file__).resolve().parents[2]
        / ".agents/personal/utility/bot-identity/scripts/bot_identity.py"
    )
    spec = importlib.util.spec_from_file_location("shared_paths_identity", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "shim_directory", lambda: tmp_path / "shim")
    return module


def test_install_converges_owned_library_and_removes_stale_code(
    bot: ModuleType,
    tmp_path: Path,
) -> None:
    package = tmp_path / "tj_cli"
    bot.install_cli_package(package)
    (package / "retired.py").write_text("obsolete = True", encoding="utf-8")
    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "retired.pyc").write_bytes(b"obsolete cache")

    bot.install_cli_package(package)

    assert bot.cli_package_contents() == bot.package_contents(package)
    assert not (package / "retired.py").exists()
    assert not cache.exists()


def test_setup_check_detects_stale_library_before_accepting_host_configuration(
    bot: ModuleType,
) -> None:
    package = bot.shim_directory() / "tj_cli"
    bot.install_cli_package(package)
    (package / "paths/search.py").write_text("stale", encoding="utf-8")

    with pytest.raises(bot.IdentityError, match="shared CLI package is stale"):
        bot.verify_host_setup()


def test_library_install_refuses_linked_destinations(
    bot: ModuleType,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "linked"
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(bot.IdentityError, match="unsafe"):
        bot.install_cli_package(destination)

    assert not list(outside.iterdir())
