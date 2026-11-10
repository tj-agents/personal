import json
from pathlib import Path

import bot_identity as bot
import pytest


@pytest.fixture
def enrollment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "github-app"
    monkeypatch.setattr(bot, "store", lambda: directory)
    key = directory / "tomjseery-bot.pem"
    bot.write_key(key, b"existing private key")
    bot.write_private(
        directory / "tomjseery-bot.json",
        {
            "id": 12345,
            "client_id": "fixture-client",
            "slug": "tomjseery-bot",
            "owner": "tomjseery",
            "key": str(key),
        },
    )
    return directory


@pytest.mark.parametrize("key_field", [True, False])
def test_migrate_legacy_identity_preserves_enrollment(
    enrollment: Path, key_field: bool
) -> None:
    legacy = enrollment / "tomjseery-bot.json"
    if not key_field:
        descriptor = json.loads(legacy.read_text(encoding="utf-8"))
        del descriptor["key"]
        bot.write_private(legacy, descriptor)
    key = enrollment / "tomjseery-bot.pem"
    key_bytes = key.read_bytes()
    key_modified = key.stat().st_mtime_ns

    bot.migrate_legacy_identity()

    assert bot.app_record() == {
        "id": 12345,
        "client_id": "fixture-client",
        "slug": "tomjseery-bot",
        "owner": "tomjseery",
        "owner_type": "User",
        "key": str(key),
    }
    assert bot.identity_config()["reviewer"] == "tomjseery"
    assert bot.required_owners() == ("tomjseery", "tj-agents", "concertable")
    assert bot.required_permissions("tj-agents") == {"repository_creation": "write"}
    assert not legacy.exists()
    assert key.read_bytes() == key_bytes
    assert key.stat().st_mtime_ns == key_modified
    bot.require_private_permissions(enrollment / "identity.json")
    current = (enrollment / "identity.json").stat().st_mtime_ns
    bot.migrate_legacy_identity()
    assert (enrollment / "identity.json").stat().st_mtime_ns == current


def test_migrate_legacy_identity_preserves_current_configuration(
    enrollment: Path,
) -> None:
    bot.migrate_legacy_identity()
    current = enrollment / "identity.json"
    original = current.read_bytes()
    bot.write_private(enrollment / "tomjseery-bot.json", {"invalid": True})

    bot.migrate_legacy_identity()

    assert current.read_bytes() == original


@pytest.mark.parametrize("invalid", ["key", "descriptor", "redirected-key"])
def test_migrate_legacy_identity_rejects_unsafe_enrollment(
    enrollment: Path, invalid: str
) -> None:
    key = enrollment / "tomjseery-bot.pem"
    if invalid == "key":
        key.unlink()
    elif invalid == "descriptor":
        bot.write_private(enrollment / "tomjseery-bot.json", {"invalid": True})
    else:
        descriptor = json.loads(
            (enrollment / "tomjseery-bot.json").read_text(encoding="utf-8")
        )
        descriptor["key"] = str(enrollment.parent / "outside.pem")
        bot.write_private(enrollment / "tomjseery-bot.json", descriptor)

    with pytest.raises(bot.IdentityError, match=r"enrollment|descriptor|key"):
        bot.migrate_legacy_identity()

    assert not (enrollment / "identity.json").exists()
    assert (enrollment / "tomjseery-bot.json").exists()


def test_setup_check_does_not_migrate_enrollment(enrollment: Path) -> None:
    with pytest.raises(bot.IdentityError, match="identity setup required"):
        bot.setup(check=True)

    assert not (enrollment / "identity.json").exists()
    assert (enrollment / "tomjseery-bot.json").exists()


def test_converge_migrates_enrollment_automatically(
    enrollment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bot, "installed_script", lambda: enrollment / "absent.py")

    assert bot.converge_shims() == []

    assert bot.app_record()["key"] == str(enrollment / "tomjseery-bot.pem")
    assert not (enrollment / "tomjseery-bot.json").exists()
